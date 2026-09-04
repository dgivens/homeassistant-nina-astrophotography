"""Per-frame image statistics store for N.I.N.A. Astrophotography.

This module maintains an in-memory ring buffer of every IMAGE-SAVE WebSocket
event received during the current HA session.  It derives running statistics
(rolling averages, trends, per-filter totals) that are exposed as HA sensor
entities via NinaFrameStatisticsSensor.

Data model
----------
Each frame is stored as a FrameRecord dataclass.  The store keeps up to
MAX_FRAMES frames in a deque (newest last).  On SEQUENCE-STARTING the store
optionally resets so per-session stats start fresh.

All state lives in memory — it is intentionally not persisted across HA
restarts.  The goal is live session feedback, not long-term logging
(use HA's recorder / statistics platform for that).
"""
from __future__ import annotations

import logging
import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Maximum frames to keep in memory per session
MAX_FRAMES = 500

# Rolling window size for "recent" averages (last N frames)
ROLLING_WINDOW = 10


@dataclass
class FrameRecord:
    """One saved frame from the IMAGE-SAVE WebSocket event."""

    index: int                  # sequential 0-based index within session
    timestamp: datetime
    filter_name: str
    exposure: float             # seconds
    hfr: float | None
    hfr_std_dev: float | None
    stars: int | None
    mean_adu: float | None
    median_adu: float | None
    std_dev_adu: float | None
    min_adu: float | None
    max_adu: float | None
    rms_text: str               # guider RMS string at capture time
    camera_temp: float | None
    gain: int | None
    offset: int | None
    target_name: str
    filename: str
    focal_length: float | None
    telescope_name: str


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _to_int(v: Any) -> int | None:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _hfr(v: Any) -> float | None:
    """HFR, or None when star detection did not run.

    Calibration frames report 0 rather than omitting the field, and a real HFR
    is always positive, so 0 means "not measured", not "perfect focus".
    """
    value = _to_float(v)
    return None if value is None or value <= 0 else value


def _star_count(v: Any) -> int | None:
    """Star count, or None when star detection did not run (reported as -1).

    0 is a real measurement — detection ran and found nothing, which is what a
    clouded-out frame looks like — so only negatives mean absent.
    """
    value = _to_int(v)
    return None if value is None or value < 0 else value


class NinaFrameStatisticsStore:
    """Central store for per-frame statistics.  One instance per config entry.

    Consumers (sensor entities) hold a reference and read derived properties.
    The WebSocket IMAGE-SAVE callback calls push_frame() on every new frame.
    SEQUENCE-STARTING calls reset() to start a new session.
    """

    def __init__(self) -> None:
        self._frames: deque[FrameRecord] = deque(maxlen=MAX_FRAMES)
        self._session_index: int = 0
        # Callbacks to notify when new frame arrives (sensor entities subscribe)
        self._listeners: list[Any] = []

    # ── Subscription ─────────────────────────────────────────────────────────

    def add_update_listener(self, callback) -> None:
        """Register a no-arg callable called after every frame push."""
        self._listeners.append(callback)

    def remove_update_listener(self, callback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    # ── Mutation ─────────────────────────────────────────────────────────────

    def push_frame(self, response: dict) -> None:
        """Parse an IMAGE-SAVE response payload and store the frame."""
        stats = response.get("ImageStatistics", {})
        if not stats:
            _LOGGER.debug("IMAGE-SAVE payload missing ImageStatistics")
            return

        record = FrameRecord(
            index=self._session_index,
            timestamp=datetime.now(),
            filter_name=stats.get("Filter", "Unknown"),
            exposure=_to_float(stats.get("ExposureTime")) or 0.0,
            # Star detection reports its own absence: HFR 0, Stars -1. Check
            # those rather than ImageType, which the payload also carries — a
            # light frame whose detection was skipped or failed reports the
            # same values and has to be excluded too. Aggregates skip None,
            # which is what keeps unmeasured frames out of bests and averages.
            hfr=_hfr(stats.get("HFR")),
            # HFRStDev reports "NaN" instead, which _to_float already drops.
            hfr_std_dev=_to_float(stats.get("HFRStDev")),
            stars=_star_count(stats.get("Stars")),
            mean_adu=_to_float(stats.get("Mean")),
            median_adu=_to_float(stats.get("Median")),
            std_dev_adu=_to_float(stats.get("StDev")),
            min_adu=_to_float(stats.get("Min")),
            max_adu=_to_float(stats.get("Max")),
            rms_text=stats.get("RmsText", ""),
            camera_temp=_to_float(stats.get("Temperature")),
            gain=_to_int(stats.get("Gain")),
            offset=_to_int(stats.get("Offset")),
            target_name=stats.get("TargetName", ""),
            filename=stats.get("Filename", ""),
            focal_length=_to_float(stats.get("FocalLength")),
            telescope_name=stats.get("TelescopeName", ""),
        )

        self._frames.append(record)
        self._session_index += 1
        _LOGGER.debug(
            "Frame %d stored: filter=%s HFR=%.2f stars=%s",
            record.index,
            record.filter_name,
            record.hfr or 0,
            record.stars,
        )

        # Notify all sensor entities so they can schedule a state write
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Frame statistics listener error")

    def reset(self) -> None:
        """Clear all frames — called at SEQUENCE-STARTING."""
        _LOGGER.debug("Frame statistics store reset for new sequence")
        self._frames.clear()
        self._session_index = 0
        for cb in list(self._listeners):
            try:
                cb()
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Frame statistics listener error")

    # ── Read-only derived properties ─────────────────────────────────────────

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def frames(self) -> list[FrameRecord]:
        """Return a snapshot list (newest last)."""
        return list(self._frames)

    @property
    def latest(self) -> FrameRecord | None:
        return self._frames[-1] if self._frames else None

    # ── Last frame scalars ────────────────────────────────────────────────────

    @property
    def last_hfr(self) -> float | None:
        return self.latest.hfr if self.latest else None

    @property
    def last_stars(self) -> int | None:
        return self.latest.stars if self.latest else None

    @property
    def last_mean_adu(self) -> float | None:
        return self.latest.mean_adu if self.latest else None

    @property
    def last_median_adu(self) -> float | None:
        return self.latest.median_adu if self.latest else None

    @property
    def last_filter(self) -> str | None:
        return self.latest.filter_name if self.latest else None

    @property
    def last_exposure(self) -> float | None:
        return self.latest.exposure if self.latest else None

    @property
    def last_rms(self) -> str | None:
        return self.latest.rms_text if self.latest else None

    @property
    def last_camera_temp(self) -> float | None:
        return self.latest.camera_temp if self.latest else None

    @property
    def last_target(self) -> str | None:
        return self.latest.target_name if self.latest else None

    # ── Session aggregates ────────────────────────────────────────────────────

    @property
    def session_frame_count(self) -> int:
        return self._session_index

    @property
    def frames_per_filter(self) -> dict[str, int]:
        """{ filter_name: count } for entire session."""
        counts: dict[str, int] = {}
        for f in self._frames:
            counts[f.filter_name] = counts.get(f.filter_name, 0) + 1
        return counts

    @property
    def total_integration_seconds(self) -> float:
        return sum(f.exposure for f in self._frames)

    @property
    def total_integration_minutes(self) -> float:
        return round(self.total_integration_seconds / 60, 1)

    # ── Rolling window statistics (last ROLLING_WINDOW frames) ───────────────

    def _rolling_hfr(self) -> list[float]:
        return [f.hfr for f in self._frames if f.hfr is not None][-ROLLING_WINDOW:]

    def _rolling_stars(self) -> list[int]:
        return [f.stars for f in self._frames if f.stars is not None][-ROLLING_WINDOW:]

    def _rolling_adu(self) -> list[float]:
        return [f.mean_adu for f in self._frames if f.mean_adu is not None][-ROLLING_WINDOW:]

    @property
    def rolling_avg_hfr(self) -> float | None:
        vals = self._rolling_hfr()
        return round(statistics.mean(vals), 3) if vals else None

    @property
    def rolling_avg_stars(self) -> float | None:
        vals = self._rolling_stars()
        return round(statistics.mean(vals), 1) if vals else None

    @property
    def rolling_avg_adu(self) -> float | None:
        vals = self._rolling_adu()
        return round(statistics.mean(vals), 1) if vals else None

    # ── Session-wide statistics ───────────────────────────────────────────────

    @property
    def session_avg_hfr(self) -> float | None:
        vals = [f.hfr for f in self._frames if f.hfr is not None]
        return round(statistics.mean(vals), 3) if vals else None

    @property
    def session_min_hfr(self) -> float | None:
        vals = [f.hfr for f in self._frames if f.hfr is not None]
        return round(min(vals), 3) if vals else None

    @property
    def session_max_hfr(self) -> float | None:
        vals = [f.hfr for f in self._frames if f.hfr is not None]
        return round(max(vals), 3) if vals else None

    @property
    def session_avg_stars(self) -> float | None:
        vals = [f.stars for f in self._frames if f.stars is not None]
        return round(statistics.mean(vals), 1) if vals else None

    # ── HFR trend ────────────────────────────────────────────────────────────

    @property
    def hfr_trend(self) -> str:
        """Return 'improving', 'degrading', 'stable', or 'unknown'.

        Compares the average of the last 5 frames vs the previous 5.
        """
        hfrs = [f.hfr for f in self._frames if f.hfr is not None]
        if len(hfrs) < 6:
            return "unknown"
        recent = statistics.mean(hfrs[-5:])
        previous = statistics.mean(hfrs[-10:-5]) if len(hfrs) >= 10 else statistics.mean(hfrs[:-5])
        delta = recent - previous
        if delta < -0.05:
            return "improving"   # lower HFR = sharper
        if delta > 0.05:
            return "degrading"   # higher HFR = worse
        return "stable"

    @property
    def hfr_trend_delta(self) -> float | None:
        """Return the HFR delta (last 5 vs previous 5). Negative = improving."""
        hfrs = [f.hfr for f in self._frames if f.hfr is not None]
        if len(hfrs) < 6:
            return None
        recent = statistics.mean(hfrs[-5:])
        previous = statistics.mean(hfrs[-10:-5]) if len(hfrs) >= 10 else statistics.mean(hfrs[:-5])
        return round(recent - previous, 4)

    # ── Sparkline data (for Lovelace card) ───────────────────────────────────

    def hfr_sparkline(self, n: int = 30) -> list[float | None]:
        """Return last *n* HFR values for charting (newest last)."""
        frames = list(self._frames)[-n:]
        return [f.hfr for f in frames]

    def stars_sparkline(self, n: int = 30) -> list[int | None]:
        """Return last *n* star count values."""
        frames = list(self._frames)[-n:]
        return [f.stars for f in frames]

    def adu_sparkline(self, n: int = 30) -> list[float | None]:
        """Return last *n* mean ADU values."""
        frames = list(self._frames)[-n:]
        return [f.mean_adu for f in frames]

    def filter_timeline(self, n: int = 30) -> list[str]:
        """Return last *n* filter names (for colour-coding sparklines)."""
        frames = list(self._frames)[-n:]
        return [f.filter_name for f in frames]

    # ── Serialisable snapshot (for diagnostics / WS push to frontend) ────────

    def as_dict(self) -> dict:
        """Return a JSON-serialisable summary of the current session."""
        return {
            "frame_count": self.frame_count,
            "session_frame_count": self.session_frame_count,
            "total_integration_minutes": self.total_integration_minutes,
            "frames_per_filter": self.frames_per_filter,
            "last_hfr": self.last_hfr,
            "last_stars": self.last_stars,
            "last_mean_adu": self.last_mean_adu,
            "last_filter": self.last_filter,
            "last_target": self.last_target,
            "rolling_avg_hfr": self.rolling_avg_hfr,
            "rolling_avg_stars": self.rolling_avg_stars,
            "rolling_avg_adu": self.rolling_avg_adu,
            "session_avg_hfr": self.session_avg_hfr,
            "session_min_hfr": self.session_min_hfr,
            "session_max_hfr": self.session_max_hfr,
            "hfr_trend": self.hfr_trend,
            "hfr_trend_delta": self.hfr_trend_delta,
            "hfr_sparkline": self.hfr_sparkline(),
            "stars_sparkline": self.stars_sparkline(),
            "adu_sparkline": self.adu_sparkline(),
        }

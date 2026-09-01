"""Shared value-extraction helpers for the N.I.N.A. integration.

Keeps the response-shape knowledge (nullable numerics, the sequence container
tree, filter lists) in one place so the entity platforms stay declarative.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    SEQUENCE_CONTAINER_SUFFIX,
    SEQUENCE_STATUS_RUNNING,
    SEQUENCE_STATUS_SEALED,
)


def safe(data: Any, *keys: str, default=None):
    """Traverse nested dicts, returning ``default`` if any hop is missing."""
    d = data
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def safe_float(data: Any, *keys: str, default=None, digits: int = 2):
    """Traverse and coerce to float.

    The API reports unavailable sensor readings as the string ``"NaN"`` (and
    weather fields are typed as strings throughout), so anything that is not a
    finite number becomes ``None`` rather than a bogus reading.
    """
    v = safe(data, *keys, default=default)
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def safe_int(data: Any, *keys: str, default=None):
    v = safe_float(data, *keys, default=default)
    return None if v is None else int(v)


def positive_int(data: Any, *keys: str):
    """Like :func:`safe_int` but maps the API's -1 "not available" to None."""
    v = safe_int(data, *keys)
    return None if v is None or v < 0 else v


def safe_bool(data: Any, *keys: str) -> bool:
    return bool(safe(data, *keys))


def safe_datetime(data: Any, *keys: str, assume_utc: bool = False) -> datetime | None:
    """Traverse and parse an API timestamp string.

    Sensors with SensorDeviceClass.TIMESTAMP must return an aware datetime.
    Most N.I.N.A. timestamps carry an explicit UTC offset; MountInfo.UTCDate is
    the exception — it is naive but, as the name says, already UTC, so callers
    pass ``assume_utc`` for it. Anything unparseable becomes None.
    """
    value = safe(data, *keys)
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = dt_util.parse_datetime(value.strip())
    else:
        return None
    if parsed is None:
        return None
    if parsed.tzinfo:
        return parsed
    return parsed.replace(
        tzinfo=dt_util.UTC if assume_utc else dt_util.DEFAULT_TIME_ZONE
    )


# ─── Image history ────────────────────────────────────────────────────────────

def image_history(data: dict) -> list[dict]:
    """Session image history, oldest first. Empty list when unavailable."""
    resp = safe(data, "image_history", "Response")
    return resp if isinstance(resp, list) else []


def latest_frame(data: dict) -> dict:
    """The most recent frame of any type."""
    history = image_history(data)
    return history[-1] if history else {}


def latest_image(data: dict) -> dict:
    """The most recent LIGHT frame.

    Calibration frames are deliberately skipped: N.I.N.A. does not run star
    detection on them, so every FLAT/DARK/BIAS reports HFR 0 and Stars -1. A
    dawn flat run would otherwise pin the last-image sensors to those sentinels
    for the rest of the day.
    """
    for frame in reversed(image_history(data)):
        if isinstance(frame, dict) and frame.get("ImageType") == "LIGHT":
            return frame
    return {}


def latest_image_stat(data: dict, key: str):
    """One statistic from the most recent light frame.

    Star detection reports its "not measured" case in-band as HFR 0 or a
    negative star count, so those are mapped to None rather than published as
    readings.
    """
    frame = latest_image(data)
    if key not in frame:
        return None
    value = safe_float(frame, key)
    if value is None:
        return None
    if key in ("HFR", "HFRStDev") and value <= 0:
        return None
    if key == "Stars" and value < 0:
        return None
    return value


def readout_mode_name(data: dict, field: str = "ReadoutMode"):
    """Resolve a readout-mode index against the camera's mode list.

    The raw value is an index, which is meaningless as a state. On QHY and
    PlayerOne sensors the mode selects the amplifier — read noise and full-well
    capacity differ substantially between them — so the name is what matters.
    """
    index = safe_int(data, "camera", "Response", field)
    if index is None:
        return None
    modes = safe(data, "camera", "Response", "ReadoutModes")
    if isinstance(modes, list) and 0 <= index < len(modes):
        return modes[index]
    return index


# ─── Imaging train geometry ───────────────────────────────────────────────────
#
# Image scale ties the camera's pixels to the sky, and it is what makes HFR
# comparable between rigs, between nights and across an equipment change.
# N.I.N.A. reports HFR in pixels, so a threshold like "HFR > 4" silently means
# something different the moment binning, the camera or the focal length
# changes. In arcseconds it stays meaningful and can be compared against seeing.
#
#     scale (arcsec/px) = 206.265 * pixel size (µm) / focal length (mm)
#
# Focal length is read live from the active profile rather than cached: a
# focal reducer changes it mid-session, and every value below has to follow.

ARCSEC_PER_RADIAN_SCALED = 206.265  # 206265 arcsec/rad, with µm/mm folded in


def focal_length(data: dict) -> float | None:
    """Focal length in mm from the active profile, reducer included."""
    return safe_float(
        data, "profile", "Response", "TelescopeSettings", "FocalLength", digits=1
    )


def pixel_size(data: dict) -> float | None:
    """Sensor pixel pitch in µm."""
    return safe_float(data, "camera", "Response", "PixelSize", digits=3)


def _binning(data: dict) -> int:
    """Current binning factor, defaulting to 1 when unknown."""
    return safe_int(data, "camera", "Response", "BinX") or 1


def _scale_from(pixel_um: float | None, focal_mm: float | None,
                binning: int) -> float | None:
    if not pixel_um or not focal_mm:
        return None
    return ARCSEC_PER_RADIAN_SCALED * pixel_um / focal_mm * binning


def image_scale(data: dict) -> float | None:
    """Arcseconds per pixel at the current focal length and binning."""
    scale = _scale_from(pixel_size(data), focal_length(data), _binning(data))
    return None if scale is None else round(scale, 3)


def last_image_hfr_arcsec(data: dict) -> float | None:
    """HFR of the most recent frame, converted from pixels to arcseconds.

    Uses the focal length recorded with that frame where available, so the
    value stays correct for frames taken before a reducer was swapped in.
    """
    frame = latest_image(data)
    hfr = safe_float(frame, "HFR")
    if hfr is None or hfr <= 0:
        return None
    focal = safe_float(frame, "FocalLength", digits=1) or focal_length(data)
    scale = _scale_from(pixel_size(data), focal, _binning(data))
    return None if scale is None else round(hfr * scale, 2)


# ─── Filter wheel ─────────────────────────────────────────────────────────────

def available_filters(data: dict) -> list[dict]:
    """Filters configured on the wheel, as ``{"Name": ..., "Id": ...}`` dicts."""
    filters = safe(data, "filterwheel", "Response", "AvailableFilters")
    return filters if isinstance(filters, list) else []


# ─── Sequence container tree ──────────────────────────────────────────────────
#
# /sequence/state returns a list of root containers rather than a flat status
# object. Each container carries a Name, a Status and an Items list holding
# further containers and instructions; one root entry holds GlobalTriggers
# instead. Everything below walks that tree.

def sequence_roots(data: dict) -> list[dict]:
    """Root sequence containers. Empty list when no sequence is loaded."""
    resp = safe(data, "sequence", "Response")
    if not isinstance(resp, list):
        return []
    return [r for r in resp if isinstance(r, dict) and "GlobalTriggers" not in r]


def _walk(nodes: list, depth: int = 0):
    """Yield ``(node, depth)`` for every container/instruction in the tree."""
    for node in nodes:
        if not isinstance(node, dict):
            continue
        yield node, depth
        items = node.get("Items")
        if isinstance(items, list):
            yield from _walk(items, depth + 1)


def _status(node: dict) -> str:
    status = node.get("Status")
    return status.upper() if isinstance(status, str) else ""


def _display_name(node: dict) -> str | None:
    """Container name without N.I.N.A.'s "_Container" suffix."""
    name = node.get("Name")
    if not isinstance(name, str) or not name:
        return None
    if name.endswith(SEQUENCE_CONTAINER_SUFFIX):
        name = name[: -len(SEQUENCE_CONTAINER_SUFFIX)]
    return name or None


def sequence_is_running(data: dict) -> bool:
    """True while any node in the tree reports RUNNING."""
    return any(
        _status(node) == SEQUENCE_STATUS_RUNNING
        for node, _ in _walk(sequence_roots(data))
    )


def sequence_state(data: dict) -> str | None:
    """Overall sequence state: Running, Finished or Idle."""
    roots = sequence_roots(data)
    if not roots:
        return None
    if sequence_is_running(data):
        return "Running"
    statuses = {_status(node) for node, _ in _walk(roots)}
    if statuses and statuses <= SEQUENCE_STATUS_SEALED | {""}:
        return "Finished"
    return "Idle"


def sequence_target(data: dict) -> str | None:
    """Name of the target currently being imaged.

    Read from the most recent light frame rather than the sequence tree. Under
    the Target Scheduler plugin the tree only ever names its own container, and
    conditional wrappers (Sequencer+) push real targets to an unpredictable
    depth, so the frames themselves are the reliable source. Falls back to the
    shallowest running container for hand-built sequences.
    """
    target = latest_image(data).get("TargetName")
    if isinstance(target, str) and target:
        return target

    running = [
        (node, depth)
        for node, depth in _walk(sequence_roots(data))
        if _status(node) == SEQUENCE_STATUS_RUNNING
        and isinstance(node.get("Items"), list)
        and depth > 0
    ]
    if not running:
        return None
    node, _ = min(running, key=lambda pair: pair[1])
    return _display_name(node)


def sequence_current_instruction(data: dict) -> str | None:
    """Name of the deepest running leaf — the instruction executing now."""
    leaves = [
        (node, depth)
        for node, depth in _walk(sequence_roots(data))
        if _status(node) == SEQUENCE_STATUS_RUNNING
        and not isinstance(node.get("Items"), list)
    ]
    if not leaves:
        return None
    node, _ = max(leaves, key=lambda pair: pair[1])
    return _display_name(node)


def _reachable_leaves(nodes: list, sealed: bool = False):
    """Yield leaves that can still run or already ran.

    Conditional branches that were never taken stay CREATED forever, so a naive
    finished/total ratio can never reach 100%. A leaf under a container that
    already finished or was skipped is unreachable and does not count.
    """
    for node in nodes:
        if not isinstance(node, dict) or "GlobalTriggers" in node:
            continue
        status = _status(node)
        items = node.get("Items")
        if not isinstance(items, list):
            if status and not (status == "CREATED" and sealed):
                yield node
            continue
        yield from _reachable_leaves(items, sealed or status in SEQUENCE_STATUS_SEALED)


def sequence_progress(data: dict) -> float | None:
    """Percentage of reachable sequence instructions that have completed."""
    leaves = list(_reachable_leaves(sequence_roots(data)))
    if not leaves:
        return None
    done = sum(1 for node in leaves if _status(node) in SEQUENCE_STATUS_SEALED)
    return round(done / len(leaves) * 100, 1)


# ─── Entity attributes ────────────────────────────────────────────────────────

def device_attributes(data: dict, subsystem: str, keys: tuple[str, ...]) -> dict:
    """Collect static capability/driver fields as entity attributes.

    Keys are snake_cased for Home Assistant; absent fields are dropped so a
    disconnected device does not litter the state machine with nulls.
    """
    resp = safe(data, subsystem, "Response")
    if not isinstance(resp, dict):
        return {}
    attrs = {}
    for key in keys:
        if key in resp and resp[key] is not None:
            attrs[_snake(key)] = resp[key]
    return attrs


def _snake(name: str) -> str:
    out = []
    for i, ch in enumerate(name):
        if ch.isupper() and i and not name[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)

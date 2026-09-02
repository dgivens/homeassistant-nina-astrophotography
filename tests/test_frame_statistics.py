"""Tests for sentinel handling when a frame is pushed into the store.

N.I.N.A. runs no star detection on FLAT/DARK/BIAS frames and reports the
absence in-band as `HFR: 0` and `Stars: -1`. push_frame maps those to None so
the aggregates, which all skip None, stop treating them as measurements.

The fixture is a real 89-frame session — 44 lights followed by a dawn flat
run — because that ordering is what made the bug visible.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nina_astrophotography.frame_statistics import NinaFrameStatisticsStore

FIXTURE = Path(__file__).parent / "fixtures" / "image_history_session.json"


@pytest.fixture(scope="module")
def session_frames() -> list[dict]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def store(session_frames) -> NinaFrameStatisticsStore:
    s = NinaFrameStatisticsStore()
    for frame in session_frames:
        s.push_frame({"ImageStatistics": frame})
    return s


def test_a_calibration_frame_reports_no_star_measurements(session_frames):
    flat = next(f for f in session_frames if f["ImageType"] == "FLAT")
    store = NinaFrameStatisticsStore()

    store.push_frame({"ImageStatistics": flat})

    assert store.last_hfr is None
    assert store.last_stars is None


def test_a_light_frame_keeps_its_star_measurements(session_frames):
    light = next(f for f in session_frames if f["ImageType"] == "LIGHT")
    store = NinaFrameStatisticsStore()

    store.push_frame({"ImageStatistics": light})

    assert store.last_hfr == pytest.approx(light["HFR"], abs=0.001)
    assert store.last_stars == light["Stars"]


def test_a_calibration_frame_keeps_its_non_star_measurements(session_frames):
    """Mean ADU and exposure are real on a flat; only star detection is absent."""
    flat = next(f for f in session_frames if f["ImageType"] == "FLAT")
    store = NinaFrameStatisticsStore()

    store.push_frame({"ImageStatistics": flat})

    assert store.last_mean_adu == pytest.approx(flat["Mean"], abs=0.01)
    assert store.last_exposure == pytest.approx(flat["ExposureTime"], abs=0.001)


def test_session_best_hfr_ignores_a_flat_run(store, session_frames):
    """The headline symptom: best HFR used to latch onto a flat's 0."""
    lights = [f for f in session_frames if f["ImageType"] == "LIGHT"]

    assert store.session_min_hfr == pytest.approx(min(f["HFR"] for f in lights), abs=0.01)


def test_session_average_stars_ignores_a_flat_run(store, session_frames):
    """Stars use the -1 sentinel, so they need their own coverage."""
    lights = [f for f in session_frames if f["ImageType"] == "LIGHT"]
    expected = sum(f["Stars"] for f in lights) / len(lights)

    assert store.session_avg_stars == pytest.approx(expected, rel=0.01)


def test_every_frame_is_still_counted(store, session_frames):
    """Calibration frames are dropped from measurements, not from the buffer."""
    assert store.session_frame_count == len(session_frames)


def test_zero_stars_is_a_measurement_not_a_sentinel():
    """A clouded-out light frame really does detect zero stars.

    Only -1 means star detection was skipped, so the check has to be `< 0`,
    not falsiness. The real-session fixture has no such frame to catch this.
    """
    store = NinaFrameStatisticsStore()

    store.push_frame({"ImageStatistics": {"Stars": 0, "HFR": 0}})

    assert store.last_stars == 0
    assert store.last_hfr is None

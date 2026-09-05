"""fold() is pure, idempotent, and order-independent."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nina_astrophotography.api.models import AutoFocusState, Frame, NinaEvent
from nina_astrophotography.api.v2.mapper import map_event, map_frame
from nina_astrophotography.session import fold

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _load(name: str) -> list[dict]:
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    document.pop("_meta", None)
    return document["Response"]


@pytest.fixture
def night() -> list:
    return [map_frame(f, generation="g1") for f in _load("dawn_image_history_with_flats.json")]


@pytest.fixture
def night_events() -> list:
    return [map_event(e, "g1") for e in _load("dawn_event_history.json")]


def _light(**overrides) -> Frame:
    """One LIGHT frame, defaulted so a test names only the field it is about."""
    fields = {
        "date": datetime.fromisoformat("2026-09-03T23:00:00-05:00"),
        "filename": "frame_0001.fits",
        "target_name": "NGC 281",
        "filter_name": "L",
        "image_type": "LIGHT",
        "exposure_time": 300.0,
        "hfr": 1.5,
        "stars": 4158,
        "mean": 548.6,
        "median": 540.0,
        "std_dev": 30.0,
        "rms_arcsec": 0.29,
        "temperature": -10.0,
        "gain": 100,
        "offset": 50,
        "focal_length": 1000.0,
        "generation": "g1",
    }
    return Frame(**{**fields, **overrides})


def test_integration_time_sums_actual_exposures_of_lights_only(night) -> None:
    """Lights sum to 6.2000 h; all 122 frames sum to 6.2301 h.

    The tolerance is tight deliberately: at abs=0.02 an all-frames
    implementation passes, and integration time is light-frame time.
    """
    stats = fold(night, [], generation="g1")
    assert stats.integration_seconds / 3600 == pytest.approx(6.2000, abs=0.001)


def test_calibration_frames_do_not_drag_the_hfr_aggregate(night) -> None:
    """67 of 122 frames are flats reporting HFR 0."""
    stats = fold(night, [], generation="g1")
    assert stats.hfr_mean == pytest.approx(1.513, abs=0.01)


def test_the_last_frame_is_the_last_light_not_the_last_flat(night) -> None:
    """A dawn flat run left `Last Image Mean ADU` reading 33,139 on 1.4.4."""
    stats = fold(night, [], generation="g1")
    assert stats.last_frame.image_type == "LIGHT"
    assert stats.last_frame.mean == pytest.approx(548.6, rel=0.2)


def test_frames_from_a_previous_generation_are_filtered_not_cleared(night) -> None:
    """A restart is a generation change; clearing races a concurrent poll."""
    stats = fold(night, [], generation="g2")
    assert stats.image_count == 0


def test_the_breakdown_covers_every_target_imaged(night) -> None:
    assert len(fold(night, [], generation="g1").by_target) == 4


def test_the_filter_breakdown_excludes_filters_only_flats_used(night) -> None:
    """All 122 frames carry six filters; the 55 lights carry five — the flats
    add G. A per-filter row for a G flat with no G lights is noise."""
    assert len(fold(night, [], generation="g1").by_filter) == 5


def test_image_count_counts_calibration_frames_too(night) -> None:
    """image_count is every frame; the aggregates are lights only."""
    assert fold(night, [], generation="g1").image_count == 122
    assert fold(night, [], generation="g1").light_count == 55


def test_an_unmatched_autofocus_start_past_the_timeout_is_a_failure() -> None:
    """8 AUTOFOCUS-STARTING against 7 AUTOFOCUS-FINISHED on an ordinary night."""
    start = datetime.fromisoformat("2026-09-03T23:00:00-05:00")
    events = [NinaEvent("AUTOFOCUS-STARTING", start, {}, "g1")]
    stats = fold([], events, generation="g1",
                 autofocus_timeout_seconds=300,
                 now=start + timedelta(seconds=301))
    assert stats.autofocus.failed is True


def test_an_autofocus_still_inside_its_timeout_has_not_failed() -> None:
    start = datetime.fromisoformat("2026-09-03T23:00:00-05:00")
    stats = fold([], [NinaEvent("AUTOFOCUS-STARTING", start, {}, "g1")], generation="g1",
                 autofocus_timeout_seconds=300, now=start + timedelta(seconds=60))
    assert stats.autofocus.failed is False


def test_a_fold_of_nothing_has_no_session_start() -> None:
    """Before the first frame there is no clock to derive a session from."""
    assert fold([], [], generation="g1").session_start is None


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("image_count", 0),
        ("light_count", 0),
        ("integration_seconds", 0.0),
        ("hfr_mean", None),
        ("hfr_best", None),
        ("hfr_worst", None),
        ("star_count_mean", None),
        ("last_frame", None),
        ("by_target", ()),
        ("by_filter", ()),
    ],
)
def test_a_fold_of_nothing_reports_empty_aggregates(field, expected) -> None:
    assert getattr(fold([], [], generation="g1"), field) == expected


@pytest.mark.parametrize("reversed_arrival", [False, True])
def test_a_stale_copy_of_a_refetched_frame_never_wins_the_dedupe(
    night, reversed_arrival
) -> None:
    """A restart leaves the pre-restart and refetched copies of one frame in the
    store. Deduplicating before filtering would let the stale copy win and then
    be discarded, so the frame would vanish.
    """
    light = next(f for f in night if f.image_type == "LIGHT")
    both = [replace(light, generation="g2"), replace(light, generation="g1")]
    stats = fold(both[::-1] if reversed_arrival else both, [], generation="g2")
    assert (stats.image_count, stats.last_frame.generation) == (1, "g2")


def test_an_untagged_frame_folds_under_an_untagged_generation() -> None:
    """Frames received before `/application-start` answered carry no tag."""
    assert fold([_light(generation=None)], [], generation=None).image_count == 1


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("integration_seconds", 0.0),
        ("hfr_mean", None),
        ("hfr_best", None),
        ("hfr_worst", None),
        ("star_count_mean", None),
    ],
)
def test_a_light_with_no_readings_fakes_no_aggregate(field, expected) -> None:
    """`None` is "no reading" — it must not read as a zero."""
    bare = _light(exposure_time=None, hfr=None, stars=None)
    assert getattr(fold([bare], [], generation="g1"), field) == expected


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("image_count", 1),
        ("light_count", 0),
        ("integration_seconds", 0.0),
        ("by_target", ()),
        ("last_frame", None),
    ],
)
def test_an_unclassified_frame_is_counted_but_never_aggregated(field, expected) -> None:
    """A frame with no ImageType is neither calibration nor light; it is counted
    because it exists, and aggregated nowhere because nothing says it is a sub.
    """
    unclassified = _light(image_type=None)
    assert getattr(fold([unclassified], [], generation="g1"), field) == expected


def test_a_breakdown_row_with_no_measured_hfr_reports_none() -> None:
    row, = fold([_light(hfr=None)], [], generation="g1").by_target
    assert row.hfr_mean is None


@pytest.mark.parametrize("field", ["by_target", "by_filter"])
def test_an_unnamed_group_gets_no_breakdown_row(field) -> None:
    """A row headed by nothing is noise on a dashboard."""
    unnamed = _light(target_name=None, filter_name=None)
    assert getattr(fold([unnamed], [], generation="g1"), field) == ()


def test_a_session_of_only_calibration_frames_has_no_last_frame(night) -> None:
    flats = [f for f in night if f.image_type != "LIGHT"]
    assert fold(flats, [], generation="g1").last_frame is None


def test_the_hfr_extremes_are_the_best_and_worst_light(night) -> None:
    """Best is the tightest star, so the smallest HFR."""
    stats = fold(night, [], generation="g1")
    assert (stats.hfr_best, stats.hfr_worst) == pytest.approx((1.42873, 1.89118), abs=1e-5)


def test_frames_before_the_noon_rollover_are_outside_the_session(night) -> None:
    """A session runs noon to noon, so last night's frames are last night's."""
    tomorrow = max(f.date for f in night) + timedelta(days=1)
    assert fold(night, [], generation="g1", now=tomorrow).image_count == 0


def test_the_last_autofocus_to_finish_is_the_last_success(night_events) -> None:
    stats = fold([], night_events, generation="g1")
    assert stats.autofocus.last_success_at == datetime.fromisoformat(
        "2026-09-04T03:21:11.414439-05:00")


def test_an_autofocus_start_with_no_finish_after_it_is_still_running(night_events) -> None:
    """The night's eighth AUTOFOCUS-STARTING never answered."""
    stats = fold([], night_events, generation="g1")
    assert stats.autofocus.running_since == datetime.fromisoformat(
        "2026-09-04T04:26:09.812467-05:00")


def test_an_autofocus_that_finished_is_no_longer_running() -> None:
    start = datetime.fromisoformat("2026-09-03T23:00:00-05:00")
    events = [
        NinaEvent("AUTOFOCUS-STARTING", start, {}, "g1"),
        NinaEvent("AUTOFOCUS-FINISHED", start + timedelta(seconds=200), {}, "g1"),
    ]
    assert fold([], events, generation="g1").autofocus.running_since is None


def test_events_from_a_previous_session_do_not_report_an_autofocus(night_events) -> None:
    tomorrow = max(e.time for e in night_events) + timedelta(days=1)
    stats = fold([], night_events, generation="g1", now=tomorrow)
    assert stats.autofocus == AutoFocusState(None, None, False)

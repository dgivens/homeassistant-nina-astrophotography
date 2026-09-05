"""Pure, version-independent maths. No wire vocabulary reaches this module."""
from datetime import datetime, timedelta

import pytest

from nina_astrophotography.derive import (
    flip_threshold_minutes,
    hfr_arcsec,
    hours_to_meridian,
    image_scale_arcsec_per_px,
    session_start,
    time_to_meridian_flip,
)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # A real midnight-spanning night: both frames belong to one session.
        ("2026-09-03T21:39:10-05:00", "2026-09-03T12:00:00-05:00"),
        ("2026-09-04T02:35:12-05:00", "2026-09-03T12:00:00-05:00"),
        # Exactly noon starts the new session.
        ("2026-09-04T12:00:00-05:00", "2026-09-04T12:00:00-05:00"),
        ("2026-09-04T11:59:59-05:00", "2026-09-03T12:00:00-05:00"),
    ],
)
def test_the_session_boundary_is_the_most_recent_local_noon(moment, expected) -> None:
    assert session_start(datetime.fromisoformat(moment)) == datetime.fromisoformat(expected)


def test_the_rollover_hour_is_configurable() -> None:
    moment = datetime.fromisoformat("2026-09-04T10:00:00-05:00")
    assert session_start(moment, rollover_hour=8) == datetime.fromisoformat(
        "2026-09-04T08:00:00-05:00"
    )


def test_image_scale_is_the_standard_206_265_formula() -> None:
    """This rig: CameraInfo.PixelSize 3.76 um, every frame's FocalLength 500 mm."""
    assert image_scale_arcsec_per_px(3.76, 500.0) == pytest.approx(1.5511, abs=1e-4)


def test_image_scale_is_none_without_a_focal_length() -> None:
    """Absent, not zero: a missing reading must not become a division by zero."""
    assert image_scale_arcsec_per_px(3.76, 0.0) is None


def test_binning_multiplies_the_scale() -> None:
    """At bin 2 the true scale is 2x, so an unbinned formula halves every
    derived arcsecond figure."""
    assert image_scale_arcsec_per_px(3.76, 500.0, binning=2) == pytest.approx(
        3.1022, abs=1e-4)


def test_hfr_in_arcseconds_is_pixels_times_scale() -> None:
    """The last light frame of the captured night: HFR 1.4545 px at 1.5511."""
    assert hfr_arcsec(1.4545, 1.5511) == pytest.approx(2.2561, abs=1e-4)


def test_hfr_in_arcseconds_is_none_without_an_hfr() -> None:
    """A calibration frame's HFR is nulled by the mapper, not zeroed."""
    assert hfr_arcsec(None, 1.5511) is None


def test_hours_to_meridian_matches_the_rig() -> None:
    """LST 21.021944, RA 22.071111 → 01:02:57, verified to the second (§11)."""
    assert hours_to_meridian(22.071111, 21.021944) * 3600 == pytest.approx(
        1 * 3600 + 2 * 60 + 57, abs=1
    )


def test_hours_to_meridian_wraps_just_after_transit() -> None:
    """Past the meridian the target is nearly a full 12 hours from the next one."""
    assert hours_to_meridian(21.9, 22.0) == pytest.approx(11.9)


def test_time_to_meridian_flip_adds_the_profile_offset() -> None:
    assert time_to_meridian_flip(1.0, max_minutes_after_meridian=15.0) == pytest.approx(1.25)


def test_an_already_flipped_mount_is_twelve_hours_out() -> None:
    assert time_to_meridian_flip(1.0, 15.0, flipped=True) == pytest.approx(13.25)


def test_a_mount_just_past_a_flip_is_not_minutes_from_the_next_one() -> None:
    """Just flipped: the next flip is a sidereal day away, not five minutes; a
    wrap here was the bug."""
    assert time_to_meridian_flip(11.8333, 15.0, flipped=True) == pytest.approx(24.0833)


def test_the_flip_warning_threshold_is_not_a_bare_number() -> None:
    """The flip fires at (Max − Min), not zero, so `below: 10` warns AT the flip."""
    assert flip_threshold_minutes(warning_minutes=10, min_minutes_after=5,
                                  max_minutes_after=15) == 20

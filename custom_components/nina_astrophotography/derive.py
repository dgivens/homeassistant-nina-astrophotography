"""Pure, version-independent maths.

Nothing here knows a wire format, and nothing here sees a sentinel: by the time
a value arrives, api/v2/mapper.py has already turned "NaN", HFR 0 and the
meridian 24 into None.

The /sequence/json walk is deliberately absent — the tree shape is partly a
Target Scheduler fact, so the mapper normalizes it into a SequenceNode first.
"""
from __future__ import annotations

from datetime import datetime, timedelta

_ARCSEC_PER_RADIAN_MICRON_MM = 206.265


def session_start(moment: datetime, rollover_hour: int = 12) -> datetime:
    """The most recent local noon at or before `moment`.

    This is what an astrophotographer means by a session, and what N.I.N.A.'s
    own image-history dockable and Target Scheduler mean. It needs no events,
    and it is correct both when N.I.N.A. restarts mid-day and when it runs for
    days across several nights. Offset-aware and naive datetimes both work, and
    the result carries whichever `moment` had.
    """
    boundary = moment.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
    return boundary if moment >= boundary else boundary - timedelta(days=1)


def image_scale_arcsec_per_px(pixel_size_um: float, focal_length_mm: float,
                              binning: int = 1) -> float | None:
    """206.265 × pixel size (µm) × binning ÷ focal length (mm).

    The focal length is the frame's own, not the active profile's — it is the
    value in force for that frame.

    Binning comes from CameraInfo.BinX on the fast tier, because /image-history
    frames do not carry it. So an arcsecond figure is only trustworthy for
    frames shot at the camera's current binning; a historical frame shot at a
    different bin is scaled wrongly and there is no wire field that would let us
    know. Say so wherever the derived value is surfaced.
    """
    if not focal_length_mm or not pixel_size_um:
        return None
    return _ARCSEC_PER_RADIAN_MICRON_MM * pixel_size_um * binning / focal_length_mm


def hfr_arcsec(hfr_px: float | None, scale_arcsec_per_px: float | None) -> float | None:
    """HFR in arcseconds — the figure that is comparable between rigs."""
    if hfr_px is None or scale_arcsec_per_px is None:
        return None
    return hfr_px * scale_arcsec_per_px


def hours_to_meridian(right_ascension_hours: float, sidereal_time_hours: float) -> float:
    """(RA_JNOW − LST) mod 12.

    RA here is the mount's own epoch and in hours, as MountInfo reports it —
    never the J2000 degrees /equipment/mount/slew takes. RA must be in the same
    frame as the mount's apparent LST (JNOW here); `MountModel.epoch` tells you
    which frame the mount reports in.
    """
    return (right_ascension_hours - sidereal_time_hours) % 12


def time_to_meridian_flip(hours_to_meridian_value: float,
                          max_minutes_after_meridian: float) -> float:
    """Hours until the flip fires: `(HoursToMeridian + Max/60) mod 12`.

    `MountInfo.TimeToMeridianFlip` is AUTHORITATIVE — it is the number N.I.N.A.
    itself acts on, and publishing a derived value that disagrees with it is
    worse than not deriving one. This exists for the MeridianFlipSettings-aware
    secondary warning threshold only.

    Wrapped, because N.I.N.A. wraps: its own figure is
    `mod12(RA − (LST − Max/60))`. Five minutes past transit `HoursToMeridian`
    reads 11.92, and with a 15-minute limit the flip is ten minutes away — not
    twelve hours and ten. N.I.N.A. adds 12 h only inside two one-hour windows
    where the mount's pier side disagrees with the side the coordinates expect,
    and subtracts 24 from anything that reaches it, so its value always lies in
    [0, 24). Those windows need the ASCOM `DestinationSideOfPier`, which the
    API does not report; `MountInfo.TimeToMeridianFlip` already carries them.
    """
    return (hours_to_meridian_value + max_minutes_after_meridian / 60) % 12


def flip_threshold_minutes(warning_minutes: float, min_minutes_after: float,
                           max_minutes_after: float) -> float:
    """Minutes-to-flip at which a warning should fire.

    The flip fires when TimeToMeridianFlip reaches (Max − Min), not zero, so a
    bare `below: 10` warns exactly at the flip. Both bounds are per-profile, so
    a bare numeric threshold is not portable between rigs.
    """
    return warning_minutes + (max_minutes_after - min_minutes_after)

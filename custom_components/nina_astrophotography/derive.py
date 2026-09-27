"""Pure maths. Values arrive with the mapper's sentinels already `None`."""

from datetime import datetime, timedelta

_ARCSEC_PER_RADIAN_MICRON_MM = 206.265


def session_start(moment: datetime, rollover_hour: int = 12) -> datetime:
    """The latest `rollover_hour` at or before `moment`, in `moment`'s zone.

    A night, as N.I.N.A.'s image history and Target Scheduler count one.
    """
    boundary = moment.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
    return boundary if moment >= boundary else boundary - timedelta(days=1)


def image_scale_arcsec_per_px(
    pixel_size_um: float, focal_length_mm: float, binning: int = 1
) -> float | None:
    """206.265 × pixel size (µm) × binning ÷ focal length (mm).

    Frames carry their focal length but not their binning, which comes from
    the camera's current `BinX`: a frame shot at another binning is scaled
    wrongly, undetectably.
    """
    if not focal_length_mm or not pixel_size_um:
        return None
    return _ARCSEC_PER_RADIAN_MICRON_MM * pixel_size_um * binning / focal_length_mm


def hfr_arcsec(hfr_px: float | None, scale_arcsec_per_px: float | None) -> float | None:
    """HFR in arcseconds, comparable between rigs."""
    if hfr_px is None or scale_arcsec_per_px is None:
        return None
    return hfr_px * scale_arcsec_per_px


def hours_to_meridian(
    right_ascension_hours: float, sidereal_time_hours: float
) -> float:
    """(RA_JNOW − LST) mod 12.

    RA in hours, in the mount's own epoch like its LST, as `MountInfo`
    reports it; `MountModel.epoch` names the epoch.
    """
    return (right_ascension_hours - sidereal_time_hours) % 12


def time_to_meridian_flip(
    hours_to_meridian_value: float, max_minutes_after_meridian: float
) -> float:
    """Hours until the flip fires: `(HoursToMeridian + Max/60) mod 12`.

    `MountInfo.TimeToMeridianFlip` is authoritative: it is what N.I.N.A. acts
    on. This matches it except inside the two one-hour windows where N.I.N.A.
    adds 12 h for a pier side the coordinates do not expect, which needs
    ASCOM's `DestinationSideOfPier`, not on the wire.
    """
    return (hours_to_meridian_value + max_minutes_after_meridian / 60) % 12


def flip_offset_minutes(min_minutes_after: float, max_minutes_after: float) -> float:
    """The `TimeToMeridianFlip` reading at which the flip actually fires.

    (Max − Min), not zero, and per profile.
    """
    return max_minutes_after - min_minutes_after

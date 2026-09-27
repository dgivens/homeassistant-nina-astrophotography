"""Sensors: the equipment readings, the session family, the sequence, the flat
wizard and the weather channels.

**The session family is one stateless fold**, so push, poll and
`/event-history` replay give the same numbers. Every aggregate but
`session_image_count` is over lights only: a flat's HFR sentinel of 0 looks
like a measurement.

**A read-only channel of the N.I.N.A. switch device is a sensor** — a voltage
or current gauge. `ReadonlySwitches` carry no range; the writable ones are
`number`s and `switch`es.

**A weather channel is created on its first non-`NaN` reading**, and reads
`unavailable` whenever the active source is not the one that established it.
Two sources are routinely disjoint (a station reports sky brightness, a
forecast cloud cover), so `unknown` would claim a missing reading where the
source cannot produce one.

**This create-on-sight rule is only for fields whose absence is permanent.**
`CoolerPower` and `TimeToMeridianFlip` are transiently `NaN`, and a camera
warm at setup must not lose its cooler-power entity.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    DOMAIN as SENSOR_DOMAIN,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    LIGHT_LUX,
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
    UnitOfVolumetricFlux,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import derive
from .api.models import Frame, TargetBreakdown
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .device import channel_key, channels_of, observed, read_field
from .entity import NinaChannelEntity, NinaEntity
from .sequence import progress_percent

PARALLEL_UPDATES = 0

# The registry option recording which weather source established a channel; it
# survives a restart, so a restored channel can tell a source that never
# reports it from one momentarily quiet.
ESTABLISHED_BY = "established_by"

_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, kw_only=True)
class NinaSensorDescription(SensorEntityDescription):
    """A sensor, plus how to read it out of the published snapshot.

    `kind` names the child device; `None` puts it on the hub. `verified` is
    False only for the dome, which no hardware has validated.
    """

    value: Callable[[NinaData], float | int | str | datetime | None]
    kind: str | None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`, so an upgraded entity keeps
    its registry row. `unique_id` is `{entry_id}_{unique_id_suffix or key}`."""
    attributes: Callable[[NinaData], Mapping[str, Any]] | None = None


def _frame(field: str) -> Callable[[NinaData], Any]:
    """One field off the newest LIGHT frame; `None` before the first one."""

    def value(data: NinaData) -> Any:
        frame: Frame | None = data.session.last_frame
        return None if frame is None else getattr(frame, field)

    return value


def _breakdown(field: str) -> Callable[[NinaData], Mapping[str, Any]]:
    """One breakdown as a name-keyed dict, for attributes.

    A session-wide mean is dominated by the target with the most frames. The
    target list changes nightly, so these are attributes, not entities.
    """

    def value(data: NinaData) -> Mapping[str, Any]:
        rows: tuple[TargetBreakdown, ...] = getattr(data.session, field)
        return {
            row.name: {
                "count": row.count,
                "integration_hours": round(
                    row.integration_seconds / _SECONDS_PER_HOUR, 2
                ),
                "hfr_mean": None if row.hfr_mean is None else round(row.hfr_mean, 3),
            }
            for row in rows
        }

    return value


def _minutes_to_meridian_flip(data: NinaData) -> float | None:
    """`TimeToMeridianFlip`, which N.I.N.A. reports in hours, in minutes.

    The mapper has already made the untracked 24-hour sentinel `None`.
    """
    mount = data.snapshot.mount
    if mount is None or mount.time_to_meridian_flip is None:
        return None
    return mount.time_to_meridian_flip * 60.0


def _flip_bounds(data: NinaData) -> Mapping[str, Any]:
    """The reading at which N.I.N.A. actually flips: (Max − Min), not zero,
    and per profile.
    """
    minimum = data.profile.min_minutes_after_meridian
    maximum = data.profile.max_minutes_after_meridian
    return {
        "flip_fires_at_minutes": None
        if minimum is None or maximum is None
        else derive.flip_offset_minutes(minimum, maximum)
    }


def _autofocus(field: str) -> Callable[[NinaData], Any]:
    """One field off the newest autofocus report; `None` until a run reports.

    Not dated against the session: a previous night's run is still the
    focuser's last known state, and `autofocus_last_run` says how old it is.
    """

    def value(data: NinaData) -> Any:
        report = data.autofocus_report
        return None if report is None else getattr(report, field)

    return value


def _autofocus_run(data: NinaData) -> Mapping[str, Any]:
    """How the run was measured, and its curve.

    The method, fitting, autofocuser and star detector say whether two runs'
    HFRs are on the same scale (Hocus Focus's PSF fit and the built-in
    detector are not). `curve` is the V a card plots, one row per position,
    `value` None where that frame measured nothing. `fits` and `minima` are
    the overlay N.I.N.A.'s chart draws, which a card cannot re-derive: which
    points each fit used is undocumented.
    """
    report = data.autofocus_report
    if report is None:
        return {}
    return {
        "method": report.method,
        "fitting": report.fitting,
        "autofocuser": report.autofocuser,
        "star_detector": report.star_detector,
        "measured_points": report.measured_points,
        "curve": [asdict(point) for point in report.curve],
        "fits": [asdict(fit) for fit in report.fits],
        "minima": [asdict(minimum) for minimum in report.minima],
    }


def _weather_source(data: NinaData) -> str | None:
    """The weather source's name, or its `DeviceId` where the driver gives none."""
    weather = data.snapshot.weather
    if weather is None:
        return None
    return weather.meta.name or weather.meta.device_id


_BY_TARGET = _breakdown("by_target")
_BY_FILTER = _breakdown("by_filter")


def _recent_frames(data: NinaData) -> tuple[Mapping[str, Any], ...]:
    """Recent frames of every type, newest first, for the image panel card.

    Hand-picked fields rather than `asdict(frame)`: this is the card's
    contract, not `Frame`'s.
    """
    return tuple(
        {
            "date": frame.date.isoformat(),
            "filename": frame.filename,
            "image_type": frame.image_type,
            "filter": frame.filter_name,
            "mean": frame.mean,
            "median": frame.median,
            "min": frame.min,
            "max": frame.max,
        }
        for frame in data.recent_frames
    )


def _recent_lights(data: NinaData) -> tuple[Mapping[str, Any], ...]:
    """Recent lights, oldest first, for the frame statistics card's sparklines."""
    return tuple(
        {
            "date": frame.date.isoformat(),
            "target": frame.target_name,
            "filter": frame.filter_name,
            "exposure": frame.exposure_time,
            "hfr": frame.hfr,
            "stars": frame.stars,
            "mean": frame.mean,
        }
        for frame in data.session.recent_lights
    )


SESSION: tuple[NinaSensorDescription, ...] = (
    NinaSensorDescription(
        key="session_image_count",
        translation_key="session_image_count",
        unique_id_suffix="frame_session_count",
        state_class=SensorStateClass.MEASUREMENT,
        kind=None,
        # Every frame, calibration included: "did the flats run?" is a question.
        value=lambda data: data.session.image_count,
        attributes=lambda data: {"light_count": data.session.light_count},
    ),
    NinaSensorDescription(
        key="session_integration_time",
        translation_key="session_integration_time",
        unique_id_suffix="frame_session_integration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        # Summed exposures, not count × nominal: a night mixes exposure lengths.
        value=lambda data: data.session.integration_seconds / _SECONDS_PER_HOUR,
    ),
    NinaSensorDescription(
        key="session_avg_hfr",
        translation_key="session_avg_hfr",
        unique_id_suffix="frame_session_avg_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        value=lambda data: data.session.hfr_mean,
        attributes=lambda data: {
            "by_target": _BY_TARGET(data),
            "by_filter": _BY_FILTER(data),
        },
    ),
    NinaSensorDescription(
        key="session_best_hfr",
        translation_key="session_best_hfr",
        unique_id_suffix="frame_session_min_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        value=lambda data: data.session.hfr_best,
    ),
    NinaSensorDescription(
        key="session_worst_hfr",
        translation_key="session_worst_hfr",
        unique_id_suffix="frame_session_max_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        value=lambda data: data.session.hfr_worst,
    ),
    NinaSensorDescription(
        key="session_avg_stars",
        translation_key="session_avg_stars",
        unique_id_suffix="frame_session_avg_stars",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        kind=None,
        value=lambda data: data.session.star_count_mean,
    ),
    NinaSensorDescription(
        key="session_start",
        translation_key="session_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind=None,
        # The latest rollover in the rig's time zone. Any hour but
        # `rollover_hour` means the rig's clock offset is not being honoured.
        value=lambda data: data.session.session_start,
    ),
    NinaSensorDescription(
        key="last_image_hfr",
        translation_key="last_image_hfr",
        unique_id_suffix="frame_last_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        value=_frame("hfr"),
        attributes=lambda data: {"recent_lights": _recent_lights(data)},
    ),
    NinaSensorDescription(
        key="last_image_star_count",
        translation_key="last_image_star_count",
        unique_id_suffix="frame_last_stars",
        state_class=SensorStateClass.MEASUREMENT,
        kind=None,
        value=_frame("stars"),
    ),
    NinaSensorDescription(
        key="last_image_mean_adu",
        translation_key="last_image_mean_adu",
        unique_id_suffix="frame_last_mean_adu",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        kind=None,
        value=_frame("mean"),
        attributes=lambda data: {"recent_frames": _recent_frames(data)},
    ),
    NinaSensorDescription(
        key="last_image_exposure",
        translation_key="last_image_exposure",
        unique_id_suffix="frame_last_exposure",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        kind=None,
        value=_frame("exposure_time"),
    ),
    NinaSensorDescription(
        key="last_image_rms",
        translation_key="last_image_rms",
        unique_id_suffix="frame_last_rms",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        # Arcseconds, comparable across rigs. An unguided frame is None.
        value=_frame("rms_arcsec"),
    ),
    NinaSensorDescription(
        key="last_image_target",
        translation_key="last_image_target",
        unique_id_suffix="frame_last_target",
        kind=None,
        value=_frame("target_name"),
    ),
    NinaSensorDescription(
        key="last_image_filter",
        translation_key="last_image_filter",
        unique_id_suffix="frame_last_filter",
        kind=None,
        value=_frame("filter_name"),
    ),
    NinaSensorDescription(
        key="weather_source",
        translation_key="weather_source",
        unique_id_suffix="weather_name",
        entity_category=EntityCategory.DIAGNOSTIC,
        # On the hub, so it stays readable across a source swap.
        kind=None,
        value=_weather_source,
    ),
    NinaSensorDescription(
        key="site_latitude",
        translation_key="site_latitude",
        native_unit_of_measurement=DEGREE,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        # Enabled: the sky map card needs it, and a card cannot resolve a
        # disabled entity. No `state_class`: the site does not move.
        kind=None,
        value=lambda data: data.profile.site_latitude,
    ),
)


EQUIPMENT: tuple[NinaSensorDescription, ...] = (
    # ── Camera ───────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="camera_temperature",
        translation_key="camera_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        kind="camera",
        value=read_field("camera", "temperature"),
    ),
    NinaSensorDescription(
        key="camera_cooler_power",
        translation_key="camera_cooler_power",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        kind="camera",
        value=read_field("camera", "cooler_power"),
    ),
    NinaSensorDescription(
        key="camera_gain",
        translation_key="camera_gain",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="camera",
        value=read_field("camera", "gain"),
    ),
    NinaSensorDescription(
        key="camera_offset",
        translation_key="camera_offset",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="camera",
        value=read_field("camera", "offset"),
    ),
    NinaSensorDescription(
        key="camera_state",
        translation_key="camera_state",
        unique_id_suffix="camera_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="camera",
        # Beside `camera_exposing`: `Download`, `Waiting` and `Error` are what
        # an automation about a stalled camera needs.
        value=read_field("camera", "camera_state"),
    ),
    # ── Mount ────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="mount_right_ascension",
        translation_key="mount_right_ascension",
        unique_id_suffix="mount_ra",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        kind="mount",
        # Hours, in the mount's epoch (usually JNOW): not what `mount_slew` takes.
        value=read_field("mount", "right_ascension"),
    ),
    NinaSensorDescription(
        key="mount_declination",
        translation_key="mount_declination",
        unique_id_suffix="mount_dec",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        kind="mount",
        value=read_field("mount", "declination"),
    ),
    NinaSensorDescription(
        key="mount_altitude",
        translation_key="mount_altitude",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="mount",
        value=read_field("mount", "altitude"),
    ),
    NinaSensorDescription(
        key="mount_azimuth",
        translation_key="mount_azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="mount",
        value=read_field("mount", "azimuth"),
    ),
    NinaSensorDescription(
        key="mount_sidereal_time",
        translation_key="mount_sidereal_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="mount",
        value=read_field("mount", "sidereal_time"),
    ),
    NinaSensorDescription(
        key="mount_side_of_pier",
        translation_key="mount_side_of_pier",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="mount",
        # Not whether a flip has happened: that needs ASCOM's
        # `DestinationSideOfPier`, which this API does not expose.
        value=read_field("mount", "side_of_pier"),
    ),
    NinaSensorDescription(
        key="mount_time_to_meridian_flip",
        translation_key="mount_time_to_meridian_flip",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        kind="mount",
        value=_minutes_to_meridian_flip,
        attributes=_flip_bounds,
    ),
    # ── Focuser ──────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="focuser_position",
        translation_key="focuser_position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        kind="focuser",
        # Beside `number.focuser_position`, which has no `state_class`, so
        # position can be charted against temperature.
        value=read_field("focuser", "position"),
    ),
    NinaSensorDescription(
        key="focuser_temperature",
        translation_key="focuser_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        kind="focuser",
        value=read_field("focuser", "temperature"),
    ),
    NinaSensorDescription(
        key="focuser_step_size",
        translation_key="focuser_step_size",
        native_unit_of_measurement="µm",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="focuser",
        # A driver constant, so no `state_class`.
        value=read_field("focuser", "step_size"),
    ),
    # ── The last autofocus run ───────────────────────────────────────────
    # Sensors rather than attributes, so they get long-term statistics.
    NinaSensorDescription(
        key="autofocus_last_run",
        translation_key="autofocus_last_run",
        device_class=SensorDeviceClass.TIMESTAMP,
        kind="focuser",
        value=_autofocus("timestamp"),
        attributes=_autofocus_run,
    ),
    NinaSensorDescription(
        key="autofocus_position",
        translation_key="autofocus_position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        kind="focuser",
        value=_autofocus("position"),
    ),
    NinaSensorDescription(
        key="autofocus_hfr",
        translation_key="autofocus_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="focuser",
        # The sweep's lowest measured point, which compares run to run; the
        # fitted value does not. Unknown on a contrast-detection run.
        value=_autofocus("hfr"),
    ),
    NinaSensorDescription(
        key="autofocus_fitted_hfr",
        translation_key="autofocus_fitted_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="focuser",
        # The fit's minimum, which N.I.N.A. moved to: an artifact of the curve
        # fitting, often far below any frame the camera measured.
        value=_autofocus("fitted_hfr"),
    ),
    NinaSensorDescription(
        key="autofocus_starting_position",
        translation_key="autofocus_starting_position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        kind="focuser",
        # Against `autofocus_position`, how far the run moved: the drift since
        # the last run, or with temperature compensation on, what it missed.
        value=_autofocus("initial_position"),
    ),
    NinaSensorDescription(
        key="autofocus_starting_hfr",
        translation_key="autofocus_starting_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="focuser",
        # Measured, like `autofocus_hfr`, so the two compare.
        value=_autofocus("initial_hfr"),
    ),
    NinaSensorDescription(
        key="autofocus_temperature",
        translation_key="autofocus_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        kind="focuser",
        # The temperature at the run, held until the next one.
        value=_autofocus("temperature"),
    ),
    NinaSensorDescription(
        key="autofocus_duration",
        translation_key="autofocus_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        kind="focuser",
        # Per attempt, like the whole report: retries cost more than this.
        value=_autofocus("duration_seconds"),
    ),
    NinaSensorDescription(
        key="autofocus_r_squared",
        translation_key="autofocus_r_squared",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="focuser",
        # The run's worst fit. `autofocus_failed` judges it against the
        # profile's threshold.
        value=_autofocus("r_squared"),
    ),
    NinaSensorDescription(
        key="autofocus_filter",
        translation_key="autofocus_filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="focuser",
        # Enabled so its history exists: filter offsets on a non-parfocal set
        # would otherwise read as thermal drift.
        value=_autofocus("filter_name"),
    ),
    # ── Guider ───────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="guider_status",
        translation_key="guider_status",
        kind="guider",
        # `switch.guider` cannot tell a lost lock from a settled one; this can.
        value=read_field("guider", "state"),
    ),
    NinaSensorDescription(
        key="guider_rms_total",
        translation_key="guider_rms_total",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="guider",
        # Arcseconds, like `last_image_rms`.
        value=read_field("guider", "rms_total"),
    ),
    NinaSensorDescription(
        key="guider_rms_ra",
        translation_key="guider_rms_ra",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="guider",
        value=read_field("guider", "rms_ra"),
    ),
    NinaSensorDescription(
        key="guider_rms_dec",
        translation_key="guider_rms_dec",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="guider",
        value=read_field("guider", "rms_dec"),
    ),
    # ── Flat panel ───────────────────────────────────────────────────────
    NinaSensorDescription(
        key="flat_panel_cover_state",
        translation_key="flat_panel_cover_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="flat_device",
        # Beside `switch.flat_panel_cover`, which cannot express a cover stuck
        # half-way (`NeitherOpenNorClosed`).
        value=read_field("flat_device", "cover_state"),
    ),
    # ── Sequence ─────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="sequence_target",
        translation_key="sequence_target",
        unique_id_suffix="sequence_target_name",
        kind=None,
        # What is being shot now; `last_image_target` lags a target change.
        value=lambda data: data.target,
    ),
    NinaSensorDescription(
        key="wait_ends_at",
        translation_key="wait_ends_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        kind=None,
        # A timestamp, which a time trigger takes directly.
        value=lambda data: data.wait_ends_at,
    ),
    NinaSensorDescription(
        key="last_frame_at",
        translation_key="last_frame_at",
        device_class=SensorDeviceClass.TIMESTAMP,
        kind=None,
        # The newest frame of any type, so flats count as the rig working.
        value=lambda data: (
            None if data.newest_frame is None else data.newest_frame.date
        ),
    ),
    NinaSensorDescription(
        key="sequence_progress",
        translation_key="sequence_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        # Disabled: Target Scheduler publishes no iteration count, so it is
        # always unknown there.
        entity_registry_enabled_default=False,
        kind=None,
        value=lambda data: progress_percent(data.sequence),
    ),
    # ── Dome ─────────────────────────────────────────────────────────────
    # From the spec alone; no hardware has validated it.
    NinaSensorDescription(
        key="dome_shutter_status",
        translation_key="dome_shutter_status",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "shutter_status"),
    ),
)

FLATS: tuple[NinaSensorDescription, ...] = (
    # Disabled: `/flats/status` sees only flats started through the API, and
    # reads a stale "Finished" through Target Scheduler's or the wizard's.
    NinaSensorDescription(
        key="flats_state",
        translation_key="flats_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind=None,
        value=lambda data: data.flats.state,
    ),
    NinaSensorDescription(
        key="flats_total_iterations",
        translation_key="flats_total_iterations",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind=None,
        value=lambda data: data.flats.total_iterations,
    ),
    NinaSensorDescription(
        key="flats_completed_iterations",
        translation_key="flats_completed_iterations",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind=None,
        value=lambda data: data.flats.completed_iterations,
    ),
)

# Created once their equipment is observed. The weather channels are created
# per channel instead.
DESCRIPTIONS: tuple[NinaSensorDescription, ...] = SESSION + EQUIPMENT + FLATS


def _channel(key: str) -> Callable[[NinaData], float | None]:
    def value(data: NinaData) -> float | None:
        weather = data.snapshot.weather
        return None if weather is None else weather.channels.get(key)

    return value


def _weather(key: str, unique_id_suffix: str, **fields: Any) -> NinaSensorDescription:
    """One ObservingConditions channel."""
    return NinaSensorDescription(
        key=key,
        translation_key=key,
        unique_id_suffix=unique_id_suffix,
        kind="weather",
        value=_channel(key),
        **fields,
    )


WEATHER_CHANNELS: tuple[NinaSensorDescription, ...] = (
    _weather(
        "cloud_cover",
        "weather_cloud_cover",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "dew_point",
        "weather_dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "humidity",
        "weather_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "pressure",
        "weather_pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "rain_rate",
        "weather_rain_rate",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
        # The class defaults to whole mm/h, which prints light rain as 0.
        suggested_display_precision=2,
    ),
    _weather(
        "sky_brightness",
        "weather_sky_brightness",
        # Lux. Sky quality in mag/arcsec² is a separate ASCOM property.
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "sky_quality",
        "weather_sky_quality",
        native_unit_of_measurement="mag/arcsec²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    _weather(
        "sky_temperature",
        "weather_sky_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "star_fwhm",
        "weather_seeing",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    _weather(
        "temperature",
        "weather_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "wind_direction",
        "weather_wind_direction",
        # An ordinary mean of bearings puts north between east and west.
        device_class=SensorDeviceClass.WIND_DIRECTION,
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
    ),
    _weather(
        "wind_gust",
        "weather_wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "wind_speed",
        "weather_wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
)


class NinaSensor(NinaEntity, SensorEntity):
    """One descriptor, read out of the published snapshot."""

    entity_description: NinaSensorDescription
    # Cards read these live; recorded, each would write KBs per frame.
    _unrecorded_attributes = frozenset({"recent_frames", "recent_lights"})

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaSensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description

    @property
    def native_value(self) -> float | int | str | datetime | None:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        build = self.entity_description.attributes
        return None if build is None else build(self.coordinator.data)


class NinaWeatherSensor(NinaSensor):
    """One ObservingConditions channel.

    `unique_id` does not name the source, so swapping sources keeps entity ids.
    """

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaSensorDescription,
        established_by: str | None,
    ) -> None:
        """`established_by` is what the registry holds; `None` for a new channel."""
        super().__init__(coordinator, entry, description)
        self._established_by = established_by
        self._recorded = established_by

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._note_source()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._note_source()
        super()._handle_coordinator_update()

    @callback
    def _note_source(self) -> None:
        """Record the source of the newest reading in the entity registry.

        `_recorded` mirrors the registry, so an unchanged source costs no write.
        """
        weather = self.coordinator.data.snapshot.weather
        if weather is None:
            return
        device_id = weather.meta.device_id
        if device_id is None or device_id == self._recorded:
            return
        if weather.channels.get(self.entity_description.key) is None:
            return
        self._established_by = device_id
        self._recorded = device_id
        er.async_get(self.hass).async_update_entity_options(
            self.entity_id, DOMAIN, {ESTABLISHED_BY: device_id}
        )

    @property
    def available(self) -> bool:
        weather = self.coordinator.data.snapshot.weather
        if not super().available or weather is None:
            return False
        # Without a reading, available only if the active source established
        # the channel: otherwise it cannot produce one at all.
        return (
            weather.channels.get(self.entity_description.key) is not None
            or self._established_by == weather.meta.device_id
        )


class NinaSensorChannel(NinaChannelEntity, SensorEntity):
    """One read-only channel of the N.I.N.A. switch device.

    No unit or device class: `ReadonlySwitches` carry neither, and a guess
    from the name would mislabel some.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        return self.channel_value


def _established_channels(
    registry: er.EntityRegistry, entry: NinaConfigEntry
) -> dict[str, str | None]:
    """The weather channels this entry already has, and what established each.

    Read from the registry, because a channel whose source is down or swapped
    at setup would otherwise stay a dead `restored` placeholder.
    """
    by_suffix = {
        description.unique_id_suffix or description.key: description
        for description in WEATHER_CHANNELS
    }
    established: dict[str, str | None] = {}
    for row in er.async_entries_for_config_entry(registry, entry.entry_id):
        if row.domain != SENSOR_DOMAIN:
            continue
        description = by_suffix.get(row.unique_id.removeprefix(f"{entry.entry_id}_"))
        if description is None:
            continue
        established[description.key] = row.options.get(DOMAIN, {}).get(ESTABLISHED_BY)
    return established


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    added: set[str] = set()

    @callback
    def _add_observed() -> None:
        """Create the entities whose equipment has now been observed."""
        descriptions = [
            description
            for description in DESCRIPTIONS
            if description.key not in added
            and observed(coordinator.data, description.kind)
        ]
        gauges = [
            channel
            for channel in channels_of(coordinator.data)
            if not channel.writable and channel_key(channel) not in added
        ]
        if not descriptions and not gauges:
            return
        added.update(description.key for description in descriptions)
        added.update(channel_key(channel) for channel in gauges)
        async_add_entities(
            [NinaSensor(coordinator, entry, d) for d in descriptions]
            + [NinaSensorChannel(coordinator, entry, c) for c in gauges]
        )

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

    # Not gated on `observed()`: a station down at startup still owns its
    # channels, and their device row survives from the run that created them.
    established = _established_channels(er.async_get(hass), entry)
    channels = set(established)
    async_add_entities(
        NinaWeatherSensor(coordinator, entry, description, established[description.key])
        for description in WEATHER_CHANNELS
        if description.key in established
    )

    @callback
    def _add_newly_seen() -> None:
        """Create each channel on its first non-`NaN` reading."""
        weather = coordinator.data.snapshot.weather
        if weather is None:
            return
        fresh = [
            description
            for description in WEATHER_CHANNELS
            if description.key not in channels
            and weather.channels.get(description.key) is not None
        ]
        if not fresh:
            return
        channels.update(description.key for description in fresh)
        async_add_entities(
            NinaWeatherSensor(coordinator, entry, description, None)
            for description in fresh
        )

    _add_newly_seen()
    entry.async_on_unload(coordinator.async_add_listener(_add_newly_seen))

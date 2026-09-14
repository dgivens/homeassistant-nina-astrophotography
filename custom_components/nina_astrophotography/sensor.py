"""Sensors: the equipment readings, the session family, the sequence and the
weather channels.

**One session family, fed by both paths (§5.2.4).** 1.4.5 shipped two — a
polled set read off `/image-history` and a pushed set fed by `IMAGE-SAVE` — and
they disagreed. The pushed semantics win: after a dawn flat run the polled
`Last Image HFR` read `0` and `Last Image Mean ADU` read `33139.77`, which is
exactly the last FLAT's mean, because a calibration frame's HFR sentinel of
zero looks like a measurement. Every aggregate here but `session_image_count`
is over LIGHT frames only, and all of it comes from one stateless fold, so
push, poll and `/event-history` replay produce the same numbers.

**A channel of the N.I.N.A. switch device belongs here when it is read-only**
(§5.3.5) — a Pegasus voltage or current gauge. `ReadonlySwitches` carry no
range, which is what separates them from the writable channels the `number` and
`switch` platforms take.

**Weather channels are created on sight and kept (§5.2.2).** A channel exists
for this entry once it has produced one non-`NaN` reading; thereafter it reads
`unavailable` whenever the ACTIVE source is not the one that established it.
Two sources on a rig are routinely disjoint in both directions — a physical
station reports `SkyBrightness`/`SkyTemperature` but not `CloudCover`, an
internet forecast the reverse — so accumulating the union would leave channels
at `unknown` forever, which claims a reading is merely missing when the source
cannot produce it at all.

**Do not generalise the create-on-sight rule to every `"NaN"` field.** It
applies only where absence is a permanent driver property. `CoolerPower` and
`TimeToMeridianFlip` are transiently `NaN`, and a rig whose camera is warm at
setup must not lose its cooler-power entity.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
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

from .api.models import Frame, SwitchChannelModel, TargetBreakdown
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .device import channel_key, channel_name, channel_of
from .entity import NinaEntity
from .sequence import progress_percent

# Read-only: nothing here commands the rig, so there is nothing to serialize.
PARALLEL_UPDATES = 0

# The registry option that records the last weather source to feed a channel.
# The registry row is the only per-entity store that outlives a restart, and
# without it a recovered channel cannot tell a source that will never report it
# from one that is momentarily quiet.
ESTABLISHED_BY = "established_by"

_SECONDS_PER_HOUR = 3600.0


@dataclass(frozen=True, kw_only=True)
class NinaSensorDescription(SensorEntityDescription):
    """A sensor, plus how to read it out of the published snapshot.

    `kind` names the child device the entity hangs off (§5.1); `None` puts it on
    the hub, which is where anything session- or rig-scoped belongs. `verified`
    is False only for the dome, which cannot be validated against hardware.

    **A 1.4.5 entity that survives keeps its 1.4.5 `unique_id`**, through
    `unique_id_suffix` where the new `key` reads better than the old one. Home
    Assistant keys the registry on `unique_id`, so changing it mints a fresh
    entity and strands the old row as `unavailable`.
    """

    value: Callable[[NinaData], float | int | str | datetime | None]
    kind: str | None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`. `unique_id` is
    `{entry_id}_{unique_id_suffix or key}`."""
    attributes: Callable[[NinaData], Mapping[str, Any]] | None = None


def _frame(field: str) -> Callable[[NinaData], Any]:
    """One field off the newest LIGHT frame; `None` before the first one."""
    def value(data: NinaData) -> Any:
        frame: Frame | None = data.session.last_frame
        return None if frame is None else getattr(frame, field)

    return value


def _breakdown(field: str) -> Callable[[NinaData], Mapping[str, Any]]:
    """One breakdown as a name-keyed dict, small enough to sit in attributes.

    Session-wide aggregates are dominated by whichever target got the most
    frames — per-target HFR means ranged 1.429 to 1.667 against a session-wide
    1.513 on one observed night — so the split is worth carrying. As attributes
    rather than entities: the target list changes with the night.
    """
    def value(data: NinaData) -> Mapping[str, Any]:
        rows: tuple[TargetBreakdown, ...] = getattr(data.session, field)
        return {
            row.name: {
                "count": row.count,
                "integration_hours": round(row.integration_seconds / _SECONDS_PER_HOUR, 2),
                "hfr_mean": None if row.hfr_mean is None else round(row.hfr_mean, 3),
            }
            for row in rows
        }

    return value


def _device(kind: str, field: str) -> Callable[[NinaData], Any]:
    """One reading off one equipment model, `None` while the device is absent.

    A disconnected device's readings are already `None` from the mapper, so
    this yields `unknown` rather than a driver template default.
    """
    def value(data: NinaData) -> Any:
        device = getattr(data.snapshot, kind)
        return None if device is None else getattr(device, field)

    return value


def _minutes_to_meridian_flip(data: NinaData) -> float | None:
    """`TimeToMeridianFlip` is HOURS; minutes is the useful unit for a flip
    warning, and is what 1.4.5 published.

    The 24-hour untracked sentinel is already `None` from the mapper. Twelve
    hours is not: a mount inside a pier-side window reports it legitimately.
    """
    mount = data.snapshot.mount
    if mount is None or mount.time_to_meridian_flip is None:
        return None
    return mount.time_to_meridian_flip * 60.0


def _weather_source(data: NinaData) -> str | None:
    """Which source the readings are coming from. Some drivers report an empty
    name, and the opaque `DeviceId` is still better than nothing."""
    weather = data.snapshot.weather
    if weather is None:
        return None
    return weather.meta.name or weather.meta.device_id


_BY_TARGET = _breakdown("by_target")
_BY_FILTER = _breakdown("by_filter")


SESSION: tuple[NinaSensorDescription, ...] = (
    NinaSensorDescription(
        key="session_image_count",
        translation_key="session_image_count",
        unique_id_suffix="frame_session_count",
        state_class=SensorStateClass.MEASUREMENT,
        kind=None,
        # Every frame in the window, calibration included — the one aggregate
        # that is not lights-only, because "did the flats run?" is a question.
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
        # Summed exposures, never count x nominal: a session spans exposure
        # lengths, and on one observed night the two differ by 2.25x.
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
        attributes=lambda data: {"by_target": _BY_TARGET(data),
                                 "by_filter": _BY_FILTER(data)},
    ),
    NinaSensorDescription(
        key="session_best_hfr",
        translation_key="session_best_hfr",
        unique_id_suffix="frame_session_min_hfr",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind=None,
        # The smallest HFR: a tighter star is a better one.
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
        kind=None,
        # The most recent rollover in the RIG's local time, not Home
        # Assistant's: 12:00 UTC is 07:00 on a UTC-5 rig, inside its dawn flats.
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
        # Arcseconds, not pixels, so it is comparable with the guider's own RMS
        # and across rigs. A total of 0 is no guiding, and is already None.
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
        # On the hub, not the weather device: it says WHICH source is feeding
        # the channels, and it has to stay readable across a source swap.
        kind=None,
        value=_weather_source,
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
        value=_device("camera", "temperature"),
    ),
    NinaSensorDescription(
        key="camera_cooler_power",
        translation_key="camera_cooler_power",
        # No device class: Home Assistant has none for a cooler duty cycle.
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        kind="camera",
        # Transiently `NaN` on a warm camera, so it is NOT under §5.2.2's
        # create-on-sight rule: a rig configured by day must keep the entity.
        value=_device("camera", "cooler_power"),
    ),
    NinaSensorDescription(
        key="camera_gain",
        translation_key="camera_gain",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="camera",
        value=_device("camera", "gain"),
    ),
    NinaSensorDescription(
        key="camera_offset",
        translation_key="camera_offset",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="camera",
        value=_device("camera", "offset"),
    ),
    NinaSensorDescription(
        key="camera_state",
        translation_key="camera_state",
        unique_id_suffix="camera_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="camera",
        # Retained beside `binary_sensor.camera_is_exposing` for the same
        # reason `guider_status` is retained beside `switch.guider` (§5.2.3):
        # the flag answers "is it exposing", while `Downloading`, `Waiting` and
        # `Error` are the states an automation about a stalled camera needs.
        value=_device("camera", "camera_state"),
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
        # In the MOUNT's epoch — JNOW on this rig — never J2000, and in hours.
        # Feeding it back into a slew is wrong twice (§3.7).
        value=_device("mount", "right_ascension"),
    ),
    NinaSensorDescription(
        key="mount_declination",
        translation_key="mount_declination",
        unique_id_suffix="mount_dec",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        kind="mount",
        value=_device("mount", "declination"),
    ),
    NinaSensorDescription(
        key="mount_altitude",
        translation_key="mount_altitude",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="mount",
        value=_device("mount", "altitude"),
    ),
    NinaSensorDescription(
        key="mount_azimuth",
        translation_key="mount_azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="mount",
        value=_device("mount", "azimuth"),
    ),
    NinaSensorDescription(
        key="mount_sidereal_time",
        translation_key="mount_sidereal_time",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=4,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="mount",
        value=_device("mount", "sidereal_time"),
    ),
    NinaSensorDescription(
        key="mount_side_of_pier",
        translation_key="mount_side_of_pier",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="mount",
        # New. The meridian-flip maths needs it (§11), and it is the one field
        # that says whether a flip has already happened.
        value=_device("mount", "side_of_pier"),
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
    ),
    # ── Focuser ──────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="focuser_position",
        translation_key="focuser_position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_enabled_default=False,
        kind="focuser",
        # Reinstated beside `number.focuser_position` (§5.2.3): NumberEntity
        # carries no `state_class`, and position against temperature is the
        # standard temp-comp-slope diagnostic — which this rig needs, because
        # it reports `TempCompAvailable: false`.
        value=_device("focuser", "position"),
    ),
    NinaSensorDescription(
        key="focuser_temperature",
        translation_key="focuser_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        kind="focuser",
        value=_device("focuser", "temperature"),
    ),
    NinaSensorDescription(
        key="focuser_step_size",
        translation_key="focuser_step_size",
        native_unit_of_measurement="µm",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="focuser",
        # A driver constant, not a reading: no `state_class`, because a
        # statistic over an unchanging number is noise.
        value=_device("focuser", "step_size"),
    ),
    # ── Guider ───────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="guider_status",
        translation_key="guider_status",
        kind="guider",
        # Retained (§5.2.3). `switch.guider` is on for every state but
        # `Stopped` — the guider is RUNNING — so it cannot tell a lost lock
        # from a settled one, and that is what this reports.
        value=_device("guider", "state"),
    ),
    NinaSensorDescription(
        key="guider_rms_total",
        translation_key="guider_rms_total",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        kind="guider",
        # Arcseconds, not pixels: comparable across rigs, and the same
        # convention as `sensor.last_image_rms`.
        value=_device("guider", "rms_total"),
    ),
    NinaSensorDescription(
        key="guider_rms_ra",
        translation_key="guider_rms_ra",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="guider",
        value=_device("guider", "rms_ra"),
    ),
    NinaSensorDescription(
        key="guider_rms_dec",
        translation_key="guider_rms_dec",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="guider",
        value=_device("guider", "rms_dec"),
    ),
    # ── Flat panel ───────────────────────────────────────────────────────
    NinaSensorDescription(
        key="flat_panel_cover_state",
        translation_key="flat_panel_cover_state",
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="flat_device",
        # Retained beside `switch.flat_panel_cover`: `CoverState` is
        # Open | Closed | NeitherOpenNorClosed | Unknown | Error, and a switch
        # cannot express a cover that is stuck between the two.
        value=_device("flat_device", "cover_state"),
    ),
    # ── Sequence ─────────────────────────────────────────────────────────
    # On the hub: sequence control is rig-scoped, not any one device's.
    NinaSensorDescription(
        key="sequence_target",
        translation_key="sequence_target",
        unique_id_suffix="sequence_target_name",
        kind=None,
        # What is being shot NOW, where `last_image_target` is what was shot
        # last: across a target change the two disagree, and before the first
        # sub only this one has a name at all.
        value=lambda data: data.target,
    ),
    NinaSensorDescription(
        key="sequence_progress",
        translation_key="sequence_progress",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        kind=None,
        # `unknown` on a Target Scheduler rig, which keeps its target list
        # inside the imaging container and publishes no iteration count. That
        # is what this API exposes, and inventing a percentage from the node
        # statuses would be worse (§6.2).
        value=lambda data: progress_percent(data.sequence),
    ),
    # ── Dome ─────────────────────────────────────────────────────────────
    # Spec-derived and untested against hardware (§5.3.1): a bare field read,
    # no derived state, `verified=False`.
    NinaSensorDescription(
        key="dome_shutter_status",
        translation_key="dome_shutter_status",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=_device("dome", "shutter_status"),
    ),
)

# The table `async_setup_entry` creates statically, gated on the entity's
# equipment having been observed. The weather channels are not here: they are
# created per channel rather than per device, and have their own lifecycle.
DESCRIPTIONS: tuple[NinaSensorDescription, ...] = SESSION + EQUIPMENT


def _channel(key: str) -> Callable[[NinaData], float | None]:
    def value(data: NinaData) -> float | None:
        weather = data.snapshot.weather
        return None if weather is None else weather.channels.get(key)

    return value


def _weather(
    key: str, unique_id_suffix: str, **fields: Any
) -> NinaSensorDescription:
    """One ObservingConditions channel. Every one is the same four lines."""
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
        "cloud_cover", "weather_cloud_cover",
        # No device class: Home Assistant has none for cloud cover.
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "dew_point", "weather_dew_point",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "humidity", "weather_humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "pressure", "weather_pressure",
        device_class=SensorDeviceClass.ATMOSPHERIC_PRESSURE,
        native_unit_of_measurement=UnitOfPressure.HPA,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "rain_rate", "weather_rain_rate",
        device_class=SensorDeviceClass.PRECIPITATION_INTENSITY,
        native_unit_of_measurement=UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "sky_brightness", "weather_sky_brightness",
        # LUX, not mag/arcsec2. SkyBrightness and SkyQuality are two distinct
        # ASCOM ObservingConditions properties: a station reports SkyBrightness
        # 5692 (lux, at dawn) alongside SkyQuality "NaN".
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _weather(
        "sky_quality", "weather_sky_quality",
        # No device class: Home Assistant has none for mag/arcsec².
        native_unit_of_measurement="mag/arcsec²",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    _weather(
        "sky_temperature", "weather_sky_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "star_fwhm", "weather_seeing",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
    ),
    _weather(
        "temperature", "weather_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "wind_direction", "weather_wind_direction",
        # MEASUREMENT_ANGLE, not MEASUREMENT: averaging a compass bearing the
        # ordinary way puts north between east and west.
        device_class=SensorDeviceClass.WIND_DIRECTION,
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT_ANGLE,
    ),
    _weather(
        "wind_gust", "weather_wind_gust",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
    _weather(
        "wind_speed", "weather_wind_speed",
        device_class=SensorDeviceClass.WIND_SPEED,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
    ),
)


class NinaSensor(NinaEntity, SensorEntity):
    """One descriptor, read out of the published snapshot."""

    entity_description: NinaSensorDescription

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

    `unique_id` is deliberately source-INDEPENDENT. Keying it on `DeviceId`
    would change entity ids whenever the active source swapped, breaking
    automations permanently to avoid a rare event.
    """

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaSensorDescription,
        established_by: str | None,
    ) -> None:
        """`established_by` is what the registry already holds, or `None` for a
        channel seen for the first time — which records itself once added."""
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
        """Record the source of the newest reading, so a restart can read it back.

        Written to the entity registry rather than held in memory: the whole
        point of the channel surviving a restart is that it comes back still
        knowing whether the active source is one that can feed it. `_recorded`
        is what the registry holds, so an unchanged source costs no write.
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
        # A reading in hand needs no further argument. Without one, the
        # question is whether the ACTIVE source is the one that established the
        # channel: if it is, the reading is merely missing this poll; if it is
        # not, the source cannot produce it at all and `unavailable` is the
        # honest state.
        return (
            weather.channels.get(self.entity_description.key) is not None
            or self._established_by == weather.meta.device_id
        )


class NinaSensorChannel(NinaEntity, SensorEntity):
    """One read-only channel of the N.I.N.A. switch device.

    No unit and no device class: `ReadonlySwitches` carry neither, and a guess
    — volts for anything named "voltage" — would mislabel every channel the
    guess is wrong about.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        channel: SwitchChannelModel,
    ) -> None:
        super().__init__(
            coordinator, entry, channel_key(channel), kind="switch_device"
        )
        self._index = channel.index
        # Named by the driver, so there is no translation key to name it by.
        self._attr_name = channel_name(channel)

    @property
    def native_value(self) -> float | None:
        channel = channel_of(self.coordinator.data, self._index)
        return None if channel is None else channel.value


def _established_channels(
    registry: er.EntityRegistry, entry: NinaConfigEntry
) -> dict[str, str | None]:
    """The weather channels this entry already has, and what established each.

    `async_setup_entry` runs BEFORE any data arrives, and a source that cannot
    report a channel never will — so without the registry a channel would come
    back only if some other source happened to feed it. Home Assistant leaves a
    `restored` placeholder for the row in the meantime, which reads
    `unavailable` and never updates, so the symptom is a permanently dead
    entity rather than a missing one. The registry, not the poll, is the truth.
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
        """Create the entities whose equipment the snapshot now carries.

        Gated on the slot being non-`None`, because an identifiers-only
        `DeviceInfo` naming a kind `device.py` has not created leaves the entity
        platform to create a nameless device. Re-run on every publish, so
        equipment that connects hours after Home Assistant started still gets
        its entities; a slot never returns to `None`, so nothing is removed.
        """
        new: list[NinaSensor | NinaSensorChannel] = [
            NinaSensor(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and (
                description.kind is None
                or getattr(coordinator.data.snapshot, description.kind) is not None
            )
        ]
        added.update(
            sensor.entity_description.key for sensor in new
        )
        device = coordinator.data.snapshot.switch_device
        gauges = [
            channel
            for channel in (device.channels if device is not None else ())
            if not channel.writable and channel_key(channel) not in added
        ]
        added.update(channel_key(channel) for channel in gauges)
        new += [NinaSensorChannel(coordinator, entry, c) for c in gauges]
        if not new:
            return
        async_add_entities(new)

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

    established = _established_channels(er.async_get(hass), entry)
    channels = set(established)
    async_add_entities(
        NinaWeatherSensor(coordinator, entry, description, established[description.key])
        for description in WEATHER_CHANNELS
        if description.key in established
    )

    @callback
    def _add_newly_seen() -> None:
        """First sight at the channel granularity: a channel appears the first
        time it reads non-`NaN`, and is never removed."""
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

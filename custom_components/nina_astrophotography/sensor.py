"""Sensors: the session family, and the weather channels.

**One session family, fed by both paths (§5.2.4).** 1.4.5 shipped two — a
polled set read off `/image-history` and a pushed set fed by `IMAGE-SAVE` — and
they disagreed. The pushed semantics win: after a dawn flat run the polled
`Last Image HFR` read `0` and `Last Image Mean ADU` read `33139.77`, which is
exactly the last FLAT's mean, because a calibration frame's HFR sentinel of
zero looks like a measurement. Every aggregate here but `session_image_count`
is over LIGHT frames only, and all of it comes from one stateless fold, so
push, poll and `/event-history` replay produce the same numbers.

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

from .api.models import Frame, TargetBreakdown
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

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

# The table `async_setup_entry` creates statically, gated on the entity's
# equipment having been observed. C6 extends it with the equipment sensors;
# the weather channels are not here because they have their own lifecycle.
DESCRIPTIONS: tuple[NinaSensorDescription, ...] = SESSION


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
        new = [
            NinaSensor(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and (
                description.kind is None
                or getattr(coordinator.data.snapshot, description.kind) is not None
            )
        ]
        if not new:
            return
        added.update(sensor.entity_description.key for sensor in new)
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

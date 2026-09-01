"""Sensors for N.I.N.A. Astrophotography integration — corrected for v2.2.15 API."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEGREE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NinaDataCoordinator

_LOGGER = logging.getLogger(__name__)


@dataclass
class NinaSensorDescription(SensorEntityDescription):
    value_fn: Any = None


def _safe(data: dict, *keys: str, default=None):
    """Safely traverse nested dict."""
    d = data
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


def _safe_float(data: dict, *keys: str, default=None):
    """Traverse dict and return float, treating 'NaN' strings as None."""
    v = _safe(data, *keys, default=default)
    if v is None:
        return None
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 2)
    except (TypeError, ValueError):
        return None


def _latest_stat(data: dict, stat_key: str) -> Any:
    history = _safe(data, "image_history", "Response", default=[])
    if history and isinstance(history, list):
        # Oldest first, so the newest frame is at the end.
        return history[-1].get(stat_key)
    return None


SENSOR_DESCRIPTIONS: list[NinaSensorDescription] = [

    # ── Camera ────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="camera_temperature",
        name="Camera Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        # API returns "Temperature" key; can be "NaN" string when sensor not available
        value_fn=lambda d: _safe_float(d, "camera", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="camera_target_temperature",
        name="Camera Target Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-lines",
        entity_category=EntityCategory.DIAGNOSTIC,
        # API key is "TargetTemp" NOT "TemperatureSetPoint"
        value_fn=lambda d: _safe_float(d, "camera", "Response", "TargetTemp"),
    ),
    NinaSensorDescription(
        key="camera_cooler_power",
        name="Camera Cooler Power",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:snowflake",
        # API key "CoolerPower" can be "NaN" string
        value_fn=lambda d: _safe_float(d, "camera", "Response", "CoolerPower"),
    ),
    NinaSensorDescription(
        key="camera_gain",
        name="Camera Gain",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:camera-iris",
        # -1 means not available/not connected
        value_fn=lambda d: (
            v if (v := _safe(d, "camera", "Response", "Gain")) not in (None, -1) else None
        ),
    ),
    NinaSensorDescription(
        key="camera_offset",
        name="Camera Offset",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune",
        value_fn=lambda d: (
            v if (v := _safe(d, "camera", "Response", "Offset")) not in (None, -1) else None
        ),
    ),
    NinaSensorDescription(
        key="camera_status",
        name="Camera Status",
        icon="mdi:camera",
        value_fn=lambda d: _safe(d, "camera", "Response", "CameraState"),
    ),
    NinaSensorDescription(
        key="camera_name",
        name="Camera Name",
        icon="mdi:camera",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _safe(d, "camera", "Response", "Name"),
    ),
    NinaSensorDescription(
        key="camera_current_filter",
        name="Current Filter",
        icon="mdi:filter",
        # Filter comes from filterwheel, not camera
        value_fn=lambda d: _safe(d, "filterwheel", "Response", "SelectedFilter", "Name"),
    ),

    # ── Mount ─────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="mount_ra",
        name="Mount RA",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:telescope",
        value_fn=lambda d: _safe_float(d, "mount", "Response", "RightAscension"),
    ),
    NinaSensorDescription(
        key="mount_dec",
        name="Mount Dec",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:telescope",
        value_fn=lambda d: _safe_float(d, "mount", "Response", "Declination"),
    ),
    NinaSensorDescription(
        key="mount_altitude",
        name="Mount Altitude",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-circle",
        value_fn=lambda d: _safe_float(d, "mount", "Response", "Altitude"),
    ),
    NinaSensorDescription(
        key="mount_azimuth",
        name="Mount Azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass",
        value_fn=lambda d: _safe_float(d, "mount", "Response", "Azimuth"),
    ),
    NinaSensorDescription(
        key="mount_sidereal_time",
        name="Mount Sidereal Time",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _safe_float(d, "mount", "Response", "SiderealTime"),
    ),
    NinaSensorDescription(
        key="mount_time_to_meridian_flip",
        name="Time to Meridian Flip",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:swap-horizontal",
        value_fn=lambda d: _safe_float(d, "mount", "Response", "TimeToMeridianFlip"),
    ),
    NinaSensorDescription(
        key="mount_status",
        name="Mount Name",
        icon="mdi:crosshairs-gps",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _safe(d, "mount", "Response", "Name"),
    ),

    # ── Focuser ───────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="focuser_position",
        name="Focuser Position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:focus-field",
        value_fn=lambda d: _safe(d, "focuser", "Response", "Position"),
    ),
    NinaSensorDescription(
        key="focuser_temperature",
        name="Focuser Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: _safe_float(d, "focuser", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="focuser_step_size",
        name="Focuser Step Size",
        native_unit_of_measurement="μm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ruler",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _safe_float(d, "focuser", "Response", "StepSize"),
    ),

    # ── Guider ────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="guider_rms_total",
        name="Guider RMS Total",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-scatter-plot",
        value_fn=lambda d: _safe_float(d, "guider", "Response", "RMSError", "Total", "Arcseconds"),
    ),
    NinaSensorDescription(
        key="guider_rms_ra",
        name="Guider RMS RA",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-left-right",
        value_fn=lambda d: _safe_float(d, "guider", "Response", "RMSError", "RA", "Arcseconds"),
    ),
    NinaSensorDescription(
        key="guider_rms_dec",
        name="Guider RMS Dec",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-down",
        value_fn=lambda d: _safe_float(d, "guider", "Response", "RMSError", "Dec", "Arcseconds"),
    ),
    NinaSensorDescription(
        key="guider_status",
        name="Guider Status",
        icon="mdi:crosshairs",
        value_fn=lambda d: _safe(d, "guider", "Response", "State"),
    ),

    # ── Sequence ──────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="sequence_status",
        name="Sequence Status",
        icon="mdi:playlist-play",
        value_fn=lambda d: _safe(d, "sequence", "Response", "Status"),
    ),
    NinaSensorDescription(
        key="sequence_target_name",
        name="Sequence Target",
        icon="mdi:star-circle",
        value_fn=lambda d: _safe(d, "sequence", "Response", "TargetName"),
    ),
    NinaSensorDescription(
        key="sequence_progress",
        name="Sequence Progress",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=lambda d: _safe(d, "sequence", "Response", "ProgressExposures"),
    ),

    # ── Last image statistics ─────────────────────────────────────────────
    NinaSensorDescription(
        key="image_last_hfr",
        name="Last Image HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points",
        value_fn=lambda d: _latest_stat(d, "HFR"),
    ),
    NinaSensorDescription(
        key="image_last_star_count",
        name="Last Image Star Count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-shooting",
        value_fn=lambda d: _latest_stat(d, "DetectedStars"),
    ),
    NinaSensorDescription(
        key="image_last_mean_adu",
        name="Last Image Mean ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-histogram",
        value_fn=lambda d: _latest_stat(d, "Mean"),
    ),
    NinaSensorDescription(
        key="image_count",
        name="Session Image Count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:image-multiple",
        value_fn=lambda d: len(_safe(d, "image_history", "Response", default=[])),
    ),

    # ── Weather station ───────────────────────────────────────────────────
    # ASCOM ObservingConditions standard keys — all may be NaN if unavailable
    NinaSensorDescription(
        key="weather_temperature",
        name="Weather Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="weather_humidity",
        name="Weather Humidity",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "Humidity"),
    ),
    NinaSensorDescription(
        key="weather_dew_point",
        name="Dew Point",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-water",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "DewPoint"),
    ),
    NinaSensorDescription(
        key="weather_wind_speed",
        name="Wind Speed",
        native_unit_of_measurement="m/s",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-windy",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "WindSpeed"),
    ),
    NinaSensorDescription(
        key="weather_wind_direction",
        name="Wind Direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass-rose",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "WindDirection"),
    ),
    NinaSensorDescription(
        key="weather_wind_gust",
        name="Wind Gust",
        native_unit_of_measurement="m/s",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-hurricane",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "WindGust"),
    ),
    NinaSensorDescription(
        key="weather_pressure",
        name="Barometric Pressure",
        native_unit_of_measurement="hPa",
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "Pressure"),
    ),
    NinaSensorDescription(
        key="weather_cloud_cover",
        name="Cloud Cover",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-cloudy",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "CloudCover"),
    ),
    NinaSensorDescription(
        key="weather_rain_rate",
        name="Rain Rate",
        native_unit_of_measurement="mm/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-rainy",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "RainRate"),
    ),
    NinaSensorDescription(
        key="weather_sky_quality",
        name="Sky Quality",
        native_unit_of_measurement="mag/arcsec²",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-circle-outline",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "SkyQuality"),
    ),
    NinaSensorDescription(
        key="weather_sky_brightness",
        name="Sky Brightness",
        native_unit_of_measurement="lux",
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brightness-5",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "SkyBrightness"),
    ),
    NinaSensorDescription(
        key="weather_sky_temperature",
        name="Sky Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-night",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "SkyTemperature"),
    ),
    NinaSensorDescription(
        key="weather_seeing",
        name="Atmospheric Seeing",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:eye-circle-outline",
        value_fn=lambda d: _safe_float(d, "weather", "Response", "StarFWHM"),
    ),
    NinaSensorDescription(
        key="weather_name",
        name="Weather Station Name",
        icon="mdi:weather-partly-cloudy",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _safe(d, "weather", "Response", "Name"),
    ),

    # ── Safety monitor ────────────────────────────────────────────────────
    NinaSensorDescription(
        key="safetymonitor_name",
        name="Safety Monitor Name",
        icon="mdi:shield-check",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: _safe(d, "safetymonitor", "Response", "Name"),
    ),
]


class NinaSensor(CoordinatorEntity[NinaDataCoordinator], SensorEntity):
    entity_description: NinaSensorDescription

    def __init__(self, coordinator, description, entry_id):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }

    @property
    def native_value(self):
        if self.entity_description.value_fn and self.coordinator.data:
            try:
                return self.entity_description.value_fn(self.coordinator.data)
            except Exception:
                return None
        return None


async def async_setup_entry(hass, entry, async_add_entities):
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    frame_store = entry_data["frame_store"]

    # Standard polled sensors
    entities = [
        NinaSensor(coordinator, description, entry.entry_id)
        for description in SENSOR_DESCRIPTIONS
    ]

    # Per-frame push-driven statistics sensors
    from .frame_stats_sensor import (
        FRAME_SENSOR_DESCRIPTIONS,
        NinaFrameStatisticsSensor,
    )
    entities += [
        NinaFrameStatisticsSensor(frame_store, description, entry.entry_id)
        for description in FRAME_SENSOR_DESCRIPTIONS
    ]

    async_add_entities(entities)

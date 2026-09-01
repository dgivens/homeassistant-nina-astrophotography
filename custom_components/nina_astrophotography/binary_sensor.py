"""Binary sensors for the N.I.N.A. Astrophotography integration."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CAMERA_BUSY_STATES, DOMAIN, SHUTTER_OPEN
from .coordinator import NinaDataCoordinator
from .device import device_info_for_key
from .helpers import safe, safe_bool, sequence_is_running

_LOGGER = logging.getLogger(__name__)


@dataclass
class NinaBinarySensorDescription(BinarySensorEntityDescription):
    value_fn: Any = None


BINARY_SENSOR_DESCRIPTIONS: list[NinaBinarySensorDescription] = [

    # ── Camera ────────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="camera_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:camera",
        value_fn=lambda d: safe_bool(d, "camera", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="camera_cooling_enabled",
        name="Cooling",
        icon="mdi:snowflake",
        value_fn=lambda d: safe_bool(d, "camera", "Response", "CoolerOn"),
    ),
    NinaBinarySensorDescription(
        key="camera_at_target_temp",
        name="At Target Temperature",
        icon="mdi:thermometer-check",
        value_fn=lambda d: safe_bool(d, "camera", "Response", "AtTargetTemp"),
    ),
    NinaBinarySensorDescription(
        key="camera_exposing",
        name="Exposing",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:camera-burst",
        # IsExposing covers the exposure itself; CameraState also flags readout
        # and download, which are equally "busy" for automation purposes.
        value_fn=lambda d: (
            safe_bool(d, "camera", "Response", "IsExposing")
            or safe(d, "camera", "Response", "CameraState") in CAMERA_BUSY_STATES
        ),
    ),
    NinaBinarySensorDescription(
        key="camera_dew_heater_on",
        name="Dew Heater",
        icon="mdi:heat-wave",
        value_fn=lambda d: safe_bool(d, "camera", "Response", "DewHeaterOn"),
    ),
    NinaBinarySensorDescription(
        key="camera_subsample_enabled",
        name="Sub-sample Enabled",
        icon="mdi:crop",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "camera", "Response", "IsSubSampleEnabled"),
    ),
    NinaBinarySensorDescription(
        key="camera_live_view",
        name="Live View",
        icon="mdi:video-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "camera", "Response", "LiveViewEnabled"),
    ),

    # ── Mount ─────────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="mount_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:telescope",
        value_fn=lambda d: safe_bool(d, "mount", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="mount_parked",
        name="Parked",
        icon="mdi:parking",
        value_fn=lambda d: safe_bool(d, "mount", "Response", "AtPark"),
    ),
    NinaBinarySensorDescription(
        key="mount_tracking",
        name="Tracking",
        icon="mdi:orbit",
        value_fn=lambda d: safe_bool(d, "mount", "Response", "TrackingEnabled"),
    ),
    NinaBinarySensorDescription(
        key="mount_slewing",
        name="Slewing",
        device_class=BinarySensorDeviceClass.MOVING,
        icon="mdi:rotate-3d-variant",
        value_fn=lambda d: safe_bool(d, "mount", "Response", "Slewing"),
    ),
    NinaBinarySensorDescription(
        key="mount_at_home",
        name="At Home",
        icon="mdi:home",
        value_fn=lambda d: safe_bool(d, "mount", "Response", "AtHome"),
    ),
    NinaBinarySensorDescription(
        key="mount_pulse_guiding",
        name="Pulse Guiding",
        icon="mdi:pulse",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "mount", "Response", "IsPulseGuiding"),
    ),

    # ── Focuser ───────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="focuser_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:focus-field",
        value_fn=lambda d: safe_bool(d, "focuser", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="focuser_is_moving",
        name="Moving",
        device_class=BinarySensorDeviceClass.MOVING,
        icon="mdi:arrow-expand-horizontal",
        value_fn=lambda d: safe_bool(d, "focuser", "Response", "IsMoving"),
    ),
    NinaBinarySensorDescription(
        key="focuser_is_settling",
        name="Settling",
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "focuser", "Response", "IsSettling"),
    ),
    NinaBinarySensorDescription(
        key="focuser_temp_comp",
        name="Temperature Compensation",
        icon="mdi:thermometer-auto",
        value_fn=lambda d: safe_bool(d, "focuser", "Response", "TempComp"),
    ),

    # ── Filter Wheel ──────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="filterwheel_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:filter",
        value_fn=lambda d: safe_bool(d, "filterwheel", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="filterwheel_is_moving",
        name="Moving",
        device_class=BinarySensorDeviceClass.MOVING,
        icon="mdi:filter-cog",
        value_fn=lambda d: safe_bool(d, "filterwheel", "Response", "IsMoving"),
    ),

    # ── Guider ────────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="guider_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:crosshairs",
        value_fn=lambda d: safe_bool(d, "guider", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="guider_is_guiding",
        name="Active",
        icon="mdi:crosshairs-gps",
        value_fn=lambda d: safe(d, "guider", "Response", "State") == "Guiding",
    ),
    NinaBinarySensorDescription(
        key="guider_is_calibrating",
        name="Calibrating",
        icon="mdi:target-variant",
        value_fn=lambda d: safe(d, "guider", "Response", "State") == "Calibrating",
    ),
    NinaBinarySensorDescription(
        key="guider_lost_lock",
        name="Lost Lock",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:target-account",
        value_fn=lambda d: safe(d, "guider", "Response", "State") == "LostLock",
    ),

    # ── Rotator ───────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="rotator_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:rotate-3d-variant",
        value_fn=lambda d: safe_bool(d, "rotator", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="rotator_is_moving",
        name="Moving",
        device_class=BinarySensorDeviceClass.MOVING,
        icon="mdi:rotate-right",
        value_fn=lambda d: safe_bool(d, "rotator", "Response", "IsMoving"),
    ),
    NinaBinarySensorDescription(
        key="rotator_synced",
        name="Synced",
        icon="mdi:sync",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "rotator", "Response", "Synced"),
    ),
    NinaBinarySensorDescription(
        key="rotator_reversed",
        name="Reversed",
        icon="mdi:swap-horizontal",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "rotator", "Response", "Reverse"),
    ),

    # ── Dome ──────────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="dome_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:home-circle",
        value_fn=lambda d: safe_bool(d, "dome", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="dome_shutter_open",
        name="Shutter Open",
        device_class=BinarySensorDeviceClass.OPENING,
        icon="mdi:home-circle-outline",
        # ShutterStatus is a string enum: ShutterNone / ShutterOpen /
        # ShutterClosed / ShutterOpening / ShutterClosing / ShutterError.
        value_fn=lambda d: safe(d, "dome", "Response", "ShutterStatus") == SHUTTER_OPEN,
    ),
    NinaBinarySensorDescription(
        key="dome_slewing",
        name="Slewing",
        device_class=BinarySensorDeviceClass.MOVING,
        icon="mdi:rotate-orbit",
        value_fn=lambda d: safe_bool(d, "dome", "Response", "Slewing"),
    ),
    NinaBinarySensorDescription(
        key="dome_parked",
        name="Parked",
        icon="mdi:home-lock",
        value_fn=lambda d: safe_bool(d, "dome", "Response", "AtPark"),
    ),
    NinaBinarySensorDescription(
        key="dome_at_home",
        name="At Home",
        icon="mdi:home-import-outline",
        value_fn=lambda d: safe_bool(d, "dome", "Response", "AtHome"),
    ),
    NinaBinarySensorDescription(
        key="dome_following",
        name="Following Mount",
        icon="mdi:link-variant",
        value_fn=lambda d: (
            safe_bool(d, "dome", "Response", "IsFollowing")
            or safe_bool(d, "dome", "Response", "DriverFollowing")
        ),
    ),
    NinaBinarySensorDescription(
        key="dome_synchronized",
        name="Synchronized",
        icon="mdi:sync-circle",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_bool(d, "dome", "Response", "IsSynchronized"),
    ),

    # ── Flat Device ───────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="flatdevice_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:lightbulb",
        value_fn=lambda d: safe_bool(d, "flatdevice", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="flatdevice_light_on",
        name="Light On",
        device_class=BinarySensorDeviceClass.LIGHT,
        icon="mdi:lightbulb-on",
        value_fn=lambda d: safe_bool(d, "flatdevice", "Response", "LightOn"),
    ),
    NinaBinarySensorDescription(
        key="flatdevice_cover_open",
        name="Cover Open",
        device_class=BinarySensorDeviceClass.OPENING,
        icon="mdi:window-shutter-open",
        value_fn=lambda d: safe(d, "flatdevice", "Response", "CoverState") == "Open",
    ),

    # ── Switch device ─────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="switch_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:toggle-switch-outline",
        value_fn=lambda d: safe_bool(d, "switch", "Response", "Connected"),
    ),

    # ── Sequence ──────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="sequence_running",
        name="Sequence Running",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:play-circle",
        value_fn=sequence_is_running,
    ),

    # ── Flat Wizard ───────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="flats_running",
        name="Flat Wizard Running",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:auto-fix",
        value_fn=lambda d: str(safe(d, "flats", "Response", "State") or "").lower() == "running",
    ),

    # ── Livestack ─────────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="livestack_running",
        name="Livestack Running",
        device_class=BinarySensorDeviceClass.RUNNING,
        icon="mdi:layers-triple",
        value_fn=lambda d: str(safe(d, "livestack", "Response") or "").lower() == "running",
    ),

    # ── Weather station ───────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="weather_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:weather-partly-cloudy",
        value_fn=lambda d: safe_bool(d, "weather", "Response", "Connected"),
    ),

    # ── Safety monitor ────────────────────────────────────────────────────
    NinaBinarySensorDescription(
        key="safetymonitor_connected",
        name="Connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        icon="mdi:shield-check",
        value_fn=lambda d: safe_bool(d, "safetymonitor", "Response", "Connected"),
    ),
    NinaBinarySensorDescription(
        key="safetymonitor_is_safe",
        name="Safe",
        device_class=BinarySensorDeviceClass.SAFETY,
        icon="mdi:shield-check-outline",
        # HA's SAFETY class treats "on" as unsafe, so the API's IsSafe is
        # inverted to make the alert fire when conditions turn bad.
        value_fn=lambda d: not safe_bool(d, "safetymonitor", "Response", "IsSafe"),
    ),
]


class NinaBinarySensor(CoordinatorEntity[NinaDataCoordinator], BinarySensorEntity):

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True
    entity_description: NinaBinarySensorDescription

    def __init__(self, coordinator, description, entry_id):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info_for_key(entry_id, description.key)

    @property
    def is_on(self):
        if self.entity_description.value_fn and self.coordinator.data:
            try:
                return self.entity_description.value_fn(self.coordinator.data)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Value lookup failed for %s", self.entity_description.key,
                    exc_info=True,
                )
                return None
        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        NinaBinarySensor(coordinator, description, entry.entry_id)
        for description in BINARY_SENSOR_DESCRIPTIONS
    )

"""Number entities for N.I.N.A. — settable device positions and limits.

Camera gain and offset are deliberately absent: the Advanced API exposes them
read-only (CameraInfo), with no set endpoint. They are surfaced as sensors
instead, and are set per-exposure through the capture service or the sequence.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEGREE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NinaApiClient
from .const import DOMAIN
from .coordinator import NinaDataCoordinator
from .device import device_info_for_key
from .helpers import safe, safe_float, safe_int

_LOGGER = logging.getLogger(__name__)


@dataclass
class NinaNumberDescription(NumberEntityDescription):
    """Number description with a data path, a setter and an availability rule."""

    value_fn: Any = None       # (data) -> float | None
    set_fn: Any = None         # async (client, value) -> None
    available_fn: Any = None   # (data) -> bool
    # Optional (data) -> float overrides for driver-reported ranges
    min_fn: Any = None
    max_fn: Any = None


def _connected(subsystem: str):
    return lambda d: bool(safe(d, subsystem, "Response", "Connected"))


NUMBER_DESCRIPTIONS: list[NinaNumberDescription] = [
    # ── Camera cooling setpoint ──────────────────────────────────────────────
    NinaNumberDescription(
        key="camera_cooling_setpoint",
        name="Cooling Setpoint",
        icon="mdi:thermometer-lines",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=-50,
        native_max_value=30,
        native_step=0.5,
        mode=NumberMode.BOX,
        value_fn=lambda d: safe_float(d, "camera", "Response", "TargetTemp"),
        # minutes=0 ramps immediately to the new setpoint.
        set_fn=lambda client, v: client.cool_camera(temperature=v, minutes=0),
        available_fn=lambda d: bool(
            safe(d, "camera", "Response", "Connected")
        ) and bool(safe(d, "camera", "Response", "CanSetTemperature")),
    ),
    # ── Camera USB limit ─────────────────────────────────────────────────────
    NinaNumberDescription(
        key="camera_usb_limit_control",
        name="USB Limit",
        icon="mdi:usb",
        native_min_value=0,
        native_max_value=100,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: safe_int(d, "camera", "Response", "USBLimit"),
        set_fn=lambda client, v: client.set_usb_limit(int(v)),
        available_fn=lambda d: bool(safe(d, "camera", "Response", "CanSetUSBLimit")),
        min_fn=lambda d: safe_float(d, "camera", "Response", "USBLimitMin"),
        max_fn=lambda d: safe_float(d, "camera", "Response", "USBLimitMax"),
    ),
    # ── Focuser absolute position ────────────────────────────────────────────
    NinaNumberDescription(
        key="focuser_position_control",
        name="Target Position",
        icon="mdi:focus-field",
        native_min_value=0,
        native_max_value=200_000,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda d: safe_int(d, "focuser", "Response", "Position"),
        set_fn=lambda client, v: client.move_focuser(int(v)),
        available_fn=_connected("focuser"),
    ),
    # ── Rotator sky position ─────────────────────────────────────────────────
    NinaNumberDescription(
        key="rotator_position_control",
        name="Position",
        icon="mdi:rotate-360",
        native_unit_of_measurement=DEGREE,
        native_min_value=0,
        native_max_value=360,
        native_step=0.1,
        mode=NumberMode.BOX,
        value_fn=lambda d: safe_float(d, "rotator", "Response", "Position"),
        set_fn=lambda client, v: client.move_rotator(float(v)),
        available_fn=_connected("rotator"),
    ),
    # ── Rotator mechanical position ──────────────────────────────────────────
    NinaNumberDescription(
        key="rotator_mechanical_position_control",
        name="Mechanical Position",
        icon="mdi:cog-clockwise",
        native_unit_of_measurement=DEGREE,
        native_min_value=0,
        native_max_value=360,
        native_step=0.1,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda d: safe_float(d, "rotator", "Response", "MechanicalPosition"),
        set_fn=lambda client, v: client.move_rotator_mechanical(float(v)),
        available_fn=_connected("rotator"),
    ),
    # ── Dome azimuth ─────────────────────────────────────────────────────────
    NinaNumberDescription(
        key="dome_azimuth_control",
        name="Target Azimuth",
        icon="mdi:compass-outline",
        native_unit_of_measurement=DEGREE,
        native_min_value=0,
        native_max_value=360,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda d: safe_float(d, "dome", "Response", "Azimuth"),
        set_fn=lambda client, v: client.slew_dome(float(v)),
        available_fn=lambda d: bool(
            safe(d, "dome", "Response", "Connected")
        ) and bool(safe(d, "dome", "Response", "CanSetAzimuth")),
    ),
]


class NinaNumber(CoordinatorEntity[NinaDataCoordinator], NumberEntity):
    """A number entity backed by the N.I.N.A. coordinator."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    entity_description: NinaNumberDescription

    def __init__(
        self,
        coordinator: NinaDataCoordinator,
        description: NinaNumberDescription,
        client: NinaApiClient,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._client = client
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info_for_key(entry_id, description.key)

    def _bound(self, fn, fallback: float) -> float:
        """Prefer a driver-reported bound over the descriptor default."""
        if fn and self.coordinator.data:
            try:
                value = fn(self.coordinator.data)
                if value is not None:
                    return float(value)
            except (TypeError, ValueError):
                pass
        return fallback

    @property
    def native_min_value(self) -> float:
        return self._bound(
            self.entity_description.min_fn,
            self.entity_description.native_min_value,
        )

    @property
    def native_max_value(self) -> float:
        return self._bound(
            self.entity_description.max_fn,
            self.entity_description.native_max_value,
        )

    @property
    def native_value(self) -> float | None:
        if self.entity_description.value_fn and self.coordinator.data:
            try:
                v = self.entity_description.value_fn(self.coordinator.data)
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None
        return None

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        if self.entity_description.available_fn:
            try:
                return bool(self.entity_description.available_fn(self.coordinator.data))
            except Exception:  # noqa: BLE001
                return False
        return True

    async def async_set_native_value(self, value: float) -> None:
        if self.entity_description.set_fn:
            try:
                await self.entity_description.set_fn(self._client, value)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error(
                    "Failed to set %s to %s: %s",
                    self.entity_description.key,
                    value,
                    exc,
                )
                return
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: NinaDataCoordinator = entry_data["coordinator"]
    client: NinaApiClient = entry_data["client"]

    entities: list[NumberEntity] = [
        NinaNumber(coordinator, description, client, entry.entry_id)
        for description in NUMBER_DESCRIPTIONS
    ]

    # Settable channels reported by the switch device, one number each
    from .switch_device import async_writable_switch_numbers
    entities += async_writable_switch_numbers(coordinator, client, entry.entry_id)

    async_add_entities(entities)

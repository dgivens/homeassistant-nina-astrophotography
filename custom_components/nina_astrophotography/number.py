"""Number entities for N.I.N.A. Astrophotography – camera settings control."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NinaApiClient, NinaApiError, NinaConnectionError
from .const import DOMAIN
from .coordinator import NinaDataCoordinator



@dataclass
class NinaNumberDescription(NumberEntityDescription):
    """Extends NumberEntityDescription with data-path and set callable."""

    # Reads the current value from coordinator data
    value_fn: Any = None
    # Async callable: (client, value) → None
    set_fn: Any = None


def _safe(data: dict, *keys: str, default=None):
    d = data
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


NUMBER_DESCRIPTIONS: list[NinaNumberDescription] = [
    # ── Camera Gain ──────────────────────────────────────────────────────────
    NinaNumberDescription(
        key="camera_gain_control",
        name="Camera Gain",
        icon="mdi:camera-iris",
        native_min_value=0,
        native_max_value=5000,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda d: _safe(d, "camera", "Response", "Gain"),
        set_fn=lambda client, v: client._get(
            "/equipment/camera/set-gain", params={"gain": int(v)}
        ),
    ),
    # ── Camera Offset ─────────────────────────────────────────────────────────
    NinaNumberDescription(
        key="camera_offset_control",
        name="Camera Offset",
        icon="mdi:tune-vertical",
        native_min_value=0,
        native_max_value=5000,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda d: _safe(d, "camera", "Response", "Offset"),
        set_fn=lambda client, v: client._get(
            "/equipment/camera/set-offset", params={"offset": int(v)}
        ),
    ),
    # ── Camera Binning ────────────────────────────────────────────────────────
    NinaNumberDescription(
        key="camera_binning_control",
        name="Camera Binning",
        icon="mdi:grid",
        native_min_value=1,
        native_max_value=4,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda d: _safe(d, "camera", "Response", "BinX"),
        set_fn=lambda client, v: client._get(
            "/equipment/camera/set-binning",
            params={"x": int(v), "y": int(v)},
        ),
    ),
    # ── Camera Cooling Setpoint ───────────────────────────────────────────────
    NinaNumberDescription(
        key="camera_cooling_setpoint",
        name="Camera Cooling Setpoint",
        icon="mdi:thermometer-lines",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        native_min_value=-30,
        native_max_value=20,
        native_step=0.5,
        mode=NumberMode.BOX,
        value_fn=lambda d: _safe(d, "camera", "Response", "TargetTemp"),
        # Calling cool with 0 minutes starts cooling at the new setpoint instantly
        set_fn=lambda client, v: client.cool_camera(temperature=v, minutes=0),
    ),
    # ── Focuser Absolute Position ─────────────────────────────────────────────
    NinaNumberDescription(
        key="focuser_position_control",
        name="Focuser Target Position",
        icon="mdi:focus-field",
        native_min_value=0,
        native_max_value=200_000,
        native_step=1,
        mode=NumberMode.BOX,
        value_fn=lambda d: _safe(d, "focuser", "Response", "Position"),
        set_fn=lambda client, v: client.move_focuser(int(v)),
    ),
    # ── Filter Wheel Slot ─────────────────────────────────────────────────────
    NinaNumberDescription(
        key="filterwheel_slot_control",
        name="Filter Wheel Slot",
        icon="mdi:filter",
        native_min_value=0,
        native_max_value=20,
        native_step=1,
        mode=NumberMode.SLIDER,
        value_fn=lambda d: _safe(
            d, "filterwheel", "Response", "SelectedFilter", "Id"
        ),
        set_fn=lambda client, v: client.change_filter(int(v)),
    ),
    # ── Rotator Position ──────────────────────────────────────────────────────
    NinaNumberDescription(
        key="rotator_position_control",
        name="Rotator Position",
        icon="mdi:rotate-360",
        native_min_value=0,
        native_max_value=360,
        native_step=0.1,
        mode=NumberMode.BOX,
        value_fn=lambda d: _safe(d, "rotator", "Response", "Position"),
        set_fn=lambda client, v: client.move_rotator(float(v)),
    ),
]


class NinaNumber(CoordinatorEntity[NinaDataCoordinator], NumberEntity):
    """A number entity backed by the N.I.N.A. coordinator."""

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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }

    @property
    def native_value(self) -> float | None:
        if self.entity_description.value_fn and self.coordinator.data:
            try:
                v = self.entity_description.value_fn(self.coordinator.data)
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None
        return None

    async def async_set_native_value(self, value: float) -> None:
        """Push the new value to N.I.N.A. and refresh."""
        if self.entity_description.set_fn:
            try:
                await self.entity_description.set_fn(self._client, value)
            except (NinaApiError, NinaConnectionError) as exc:
                raise HomeAssistantError(
                    f"Could not set {self.entity_description.name} to {value}: {exc}"
                ) from exc
        # Refresh so the UI reflects the confirmed new value
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: NinaDataCoordinator = entry_data["coordinator"]
    client: NinaApiClient = entry_data["client"]
    async_add_entities(
        NinaNumber(coordinator, description, client, entry.entry_id)
        for description in NUMBER_DESCRIPTIONS
    )

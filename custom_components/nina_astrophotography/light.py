"""Light entity for N.I.N.A. flat panel / flip-flat device."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .legacy_api import NinaApiClient
from .const import DOMAIN
from .coordinator import NinaDataCoordinator

_LOGGER = logging.getLogger(__name__)


def _safe(data: dict, *keys: str, default=None):
    d = data
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


class NinaFlatLight(CoordinatorEntity[NinaDataCoordinator], LightEntity):
    """Flat panel/flip-flat light as a HA dimmable light entity.

    N.I.N.A. brightness is 0–255 which maps 1:1 to HA brightness (also 0–255).
    """

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_icon = "mdi:lightbulb-fluorescent-tube"
    _attr_name = "Flat Panel Light"

    def __init__(
        self,
        coordinator: NinaDataCoordinator,
        client: NinaApiClient,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_flat_panel_light"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(_safe(self.coordinator.data, "flatdevice", "Response", "Connected"))
            if self.coordinator.data
            else False
        )

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return bool(_safe(self.coordinator.data, "flatdevice", "Response", "LightOn"))

    @property
    def brightness(self) -> int | None:
        if not self.coordinator.data:
            return None
        v = _safe(self.coordinator.data, "flatdevice", "Response", "Brightness")
        return int(v) if v is not None else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self.is_on:
            await self._client.toggle_flat_light(True)
        if ATTR_BRIGHTNESS in kwargs:
            bri = int(kwargs[ATTR_BRIGHTNESS])
            await self._client.set_flat_brightness(bri)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.toggle_flat_light(False)
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: NinaDataCoordinator = entry_data["coordinator"]
    client: NinaApiClient = entry_data["client"]
    async_add_entities([NinaFlatLight(coordinator, client, entry.entry_id)])

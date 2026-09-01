"""Light entity for the N.I.N.A. flat panel / flip-flat device."""
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

from .api import NinaApiClient
from .const import DOMAIN
from .coordinator import NinaDataCoordinator
from .device import device_info_for
from .helpers import safe, safe_int

_LOGGER = logging.getLogger(__name__)

HA_MAX_BRIGHTNESS = 255


class NinaFlatLight(CoordinatorEntity[NinaDataCoordinator], LightEntity):
    """Flat panel / flip-flat light as a dimmable Home Assistant light.

    The panel's brightness range is driver-specific (FlatDeviceInfo reports
    MinBrightness/MaxBrightness), so values are scaled to and from HA's fixed
    0-255 range rather than assumed to match it.
    """

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_icon = "mdi:lightbulb-fluorescent-tube"
    _attr_name = "Light"

    def __init__(
        self,
        coordinator: NinaDataCoordinator,
        client: NinaApiClient,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_flat_panel_light"
        self._attr_device_info = device_info_for(entry_id, "flatdevice")

    # ── Brightness range ────────────────────────────────────────────────────

    def _range(self) -> tuple[int, int]:
        low = safe_int(self.coordinator.data, "flatdevice", "Response", "MinBrightness")
        high = safe_int(self.coordinator.data, "flatdevice", "Response", "MaxBrightness")
        if low is None:
            low = 0
        if high is None or high <= low:
            high = HA_MAX_BRIGHTNESS
        return low, high

    def _to_ha(self, device_value: int) -> int:
        low, high = self._range()
        span = high - low
        if span <= 0:
            return 0
        scaled = (device_value - low) / span * HA_MAX_BRIGHTNESS
        return max(0, min(HA_MAX_BRIGHTNESS, round(scaled)))

    def _to_device(self, ha_value: int) -> int:
        low, high = self._range()
        scaled = low + (ha_value / HA_MAX_BRIGHTNESS) * (high - low)
        return max(low, min(high, round(scaled)))

    # ── State ───────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        return bool(safe(self.coordinator.data, "flatdevice", "Response", "Connected"))

    @property
    def is_on(self) -> bool | None:
        if not self.coordinator.data:
            return None
        return bool(safe(self.coordinator.data, "flatdevice", "Response", "LightOn"))

    @property
    def brightness(self) -> int | None:
        value = safe_int(self.coordinator.data, "flatdevice", "Response", "Brightness")
        return None if value is None else self._to_ha(value)

    @property
    def extra_state_attributes(self) -> dict:
        low, high = self._range()
        return {
            "device_brightness": safe(
                self.coordinator.data, "flatdevice", "Response", "Brightness"
            ),
            "device_brightness_min": low,
            "device_brightness_max": high,
        }

    # ── Commands ────────────────────────────────────────────────────────────

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Set brightness first so the panel does not flash at its old level.
        if ATTR_BRIGHTNESS in kwargs:
            await self._client.set_flat_brightness(
                self._to_device(int(kwargs[ATTR_BRIGHTNESS]))
            )
        if not self.is_on:
            await self._client.set_flat_light(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._client.set_flat_light(False)
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

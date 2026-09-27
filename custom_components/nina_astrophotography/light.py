"""Flat panel light.

Brightness is scaled between the driver's own `MinBrightness` and
`MaxBrightness` (4096 on some panels, 255 on others) and Home Assistant's 0–255.

`turn_on` always sends a brightness, before the light: a bare
`set-light?on=true` jumps to `MaxBrightness`, a hazard in a shared
observatory. Whether every driver honours a brightness set while the light is
off is unverified.
"""

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.models import FlatDeviceModel
from .coordinator import NinaConfigEntry, NinaCoordinator
from .device import observed
from .entity import NinaEntity

PARALLEL_UPDATES = 1

_HA_MAX = 255


class NinaFlatLight(NinaEntity, LightEntity):
    """The panel's light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_translation_key = "flat_panel_light"

    # A bare turn_on restores the level last requested this run; before any
    # request it comes on dim, never full.
    _DEFAULT_ON_BRIGHTNESS = 1

    def __init__(
        self, coordinator: NinaCoordinator, entry: NinaConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator, entry, key, kind="flat_device")
        self._remembered: int | None = None

    @property
    def _panel(self) -> FlatDeviceModel | None:
        return self.coordinator.data.snapshot.flat_device

    @property
    def _span(self) -> float:
        """The driver's brightness range; 0 for a disconnected panel (Min 0 / Max 0)."""
        panel = self._panel
        if panel is None:
            return 0
        return (panel.max_brightness or 0) - (panel.min_brightness or 0)

    @property
    def _last_on_brightness(self) -> int:
        """The level a bare turn_on restores. Dim by default, never full."""
        if self._remembered is not None:
            return self._remembered
        current = self.brightness if self.is_on else None
        return current or self._DEFAULT_ON_BRIGHTNESS

    @property
    def available(self) -> bool:
        # A cover-only panel, or one reporting no usable range, is unavailable
        # rather than absent, so the entity survives restarts.
        panel = self._panel
        return bool(
            super().available
            and panel is not None
            and self._span > 0
            and panel.supports_on_off is not False
        )

    @property
    def is_on(self) -> bool | None:
        panel = self._panel
        return None if panel is None else panel.light_on

    @property
    def brightness(self) -> int | None:
        """The driver's value, scaled into HA's 0-255."""
        panel = self._panel
        if panel is None or panel.brightness is None or self._span <= 0:
            return None
        fraction = (panel.brightness - (panel.min_brightness or 0)) / self._span
        return round(fraction * _HA_MAX)

    def _to_driver(self, ha_brightness: int) -> int:
        """Scale HA's 1-255 into driver units, refusing anything outside it.

        N.I.N.A. would clamp it silently; HA's light schema clamps first, so
        this is a guard.
        """
        if not 1 <= ha_brightness <= _HA_MAX:
            raise ServiceValidationError(
                f"Brightness must be between 1 and {_HA_MAX}, got {ha_brightness}"
            )
        panel = self._panel
        low = 0 if panel is None else (panel.min_brightness or 0)
        return round(low + (ha_brightness / _HA_MAX) * self._span)

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Never fall back to full: an idle panel's brightness scales to 0.
        requested = int(kwargs.get(ATTR_BRIGHTNESS, self._last_on_brightness))
        driver_value = self._to_driver(requested)
        try:
            # Brightness first: a bare set-light jumps to MaxBrightness.
            await self.coordinator.client.set_flat_brightness(driver_value)
            if not self.is_on:
                await self.coordinator.client.set_flat_light(True)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the flat panel: {exc}") from exc
        self._remembered = requested
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            # Brightness 0 is not off.
            await self.coordinator.client.set_flat_light(False)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the flat panel: {exc}") from exc
        await self.coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    added = False

    @callback
    def _add_observed() -> None:
        """Create the light once the panel has been observed.

        Not gated on `SupportsOnOff`, which a disconnected panel reports false;
        `available` handles that.
        """
        nonlocal added
        if added or not observed(coordinator.data, "flat_device"):
            return
        added = True
        async_add_entities([NinaFlatLight(coordinator, entry, "flat_panel_light")])

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

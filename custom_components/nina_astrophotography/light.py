"""Flat panel light.

Brightness is per-device, not 0-255: this rig's panel reports MaxBrightness
4096, others report 256 or 255 — which is how the 0-255 assumption survived.
Scale between the driver's own MinBrightness and MaxBrightness in both
directions.

turn_on always sends a brightness. A bare set-light?on=true jumps to
MaxBrightness, and a light that comes on at full output is a hazard in a shared
observatory. Sending the brightness before the light is the design's anti-flash
intent; whether this driver honours a brightness set while the light is off is
unverified until the idle-rig probe runs.

Do not verify by readback: the API's commands are asynchronous and answer
Success: true before the state changes. FLAT-LIGHT-TOGGLED carries an empty
payload and FLAT-BRIGHTNESS-CHANGED fires repeatedly through a ramp with
inconsistent Previous values — both are change hints, nothing more.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.models import FlatDeviceModel
from .coordinator import NinaConfigEntry, NinaCoordinator
from .entity import NinaEntity

# One in-flight command per platform. Entity calls only; services are unaffected.
PARALLEL_UPDATES = 1

_HA_MAX = 255


class NinaFlatLight(NinaEntity, LightEntity):
    """The panel's light, gated on the panel having been observed (§5.2.2)."""

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
        return current if current else self._DEFAULT_ON_BRIGHTNESS

    @property
    def available(self) -> bool:
        # The panel's own two conditions, on top of the base's levels 1 and 2.
        # A cover-only panel and one whose driver reports no usable range are
        # unavailable, never absent: the entity must not appear and disappear
        # across restarts. Past `super().available` the panel is present, so
        # the short-circuit is what makes the attribute reads safe.
        return bool(
            super().available
            and self._span > 0
            and self._panel.supports_on_off is not False
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
        """Scale HA's 1-255 into driver units.

        Out-of-range input is silently clamped by N.I.N.A. and answers
        Success: true, so refuse it here. Home Assistant's light schema clamps
        first, which makes this a guard rather than a path.
        """
        if not 1 <= ha_brightness <= _HA_MAX:
            raise ServiceValidationError(
                f"Brightness must be between 1 and {_HA_MAX}, got {ha_brightness}"
            )
        low = self._panel.min_brightness or 0
        return round(low + (ha_brightness / _HA_MAX) * self._span)

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Never fall back to _HA_MAX. The panel's ordinary idle state is
        # Brightness 0 / LightOn false, which scales to 0 — falsy — so
        # `self.brightness or _HA_MAX` would send 255 -> 4096 and the panel
        # would come on at full output on any dashboard tap or scene.
        requested = int(kwargs.get(ATTR_BRIGHTNESS, self._last_on_brightness))
        driver_value = self._to_driver(requested)
        try:
            # Brightness first, then the light: a bare set-light jumps to
            # MaxBrightness, so this ordering is what prevents the flash.
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
    # Gate on the panel having been OBSERVED, not on SupportsOnOff being true
    # right now: a disconnected panel reports Min 0 / Max 0 and SupportsOnOff
    # false, which is the ordinary startup state. Gating on it would make the
    # light vanish on every restart that beat the panel's connection.
    # `available` carries the disconnected state instead. §5.2.2.
    if coordinator.data.snapshot.flat_device is not None:
        async_add_entities([NinaFlatLight(coordinator, entry, "flat_panel_light")])

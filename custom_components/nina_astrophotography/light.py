"""Flat panel light.

Brightness is scaled between the driver's own `MinBrightness` and
`MaxBrightness` (4096 on some panels, 255 on others) and Home Assistant's 0–255.

`turn_on` always sends a brightness, before the light: a bare
`set-light?on=true` can jump to `MaxBrightness`, a hazard in a shared
observatory. On an ASCOM panel the brightness alone lights it; N.I.N.A.'s
native drivers keep brightness and light apart, so `set-light` switches the
panel on.
"""

import asyncio
import math
from typing import Any

# The package root is the one path that holds across 2026.9 and 2026.10.
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,  # pyright: ignore[reportPrivateImportUsage]
    LightEntity,
)
from homeassistant.components.light.const import ColorMode
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.models import FlatDeviceModel
from .api.v2 import NinaClientV2
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator
from .device import observed
from .entity import NinaEntity, async_add_observed, refusals_raised

PARALLEL_UPDATES = 1

_HA_MAX = 255

# N.I.N.A. reads the panel once per device polling interval, 2 s by default
# and settable by the operator, so a brightness set shows seconds after the
# command answers.
_SETTLE_INTERVAL = 1.0
_SETTLE_TIMEOUT = 30.0


async def async_light_at(client: NinaClientV2, level: int) -> None:
    """Light the panel at `level`, in driver units, and never above it.

    N.I.N.A. runs `set-brightness` and `set-light` without waiting for either,
    so both can be in flight at once. An ASCOM panel's light-on that runs
    before the brightness is stored comes on at `MaxBrightness`, the first
    time after a connect. So the brightness goes alone, and `set-light` follows
    only once the panel reports that level and still reads off: an ASCOM panel
    is lit by the brightness itself, and a native one comes on at it.

    Being lit is not enough on its own: until N.I.N.A. next reads the panel, it
    reports the state from before the command, including a switch-off just
    sent. A panel that never reports the level is refused rather than sent a
    `set-light` that could race the brightness.
    """
    await client.set_flat_brightness(level)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _SETTLE_TIMEOUT
    while True:
        try:
            panel = (await client.get_equipment()).flat_device
        except NinaError:
            panel = None
        if (
            panel is not None
            and panel.brightness is not None
            and round(panel.brightness) == level
        ):
            if not panel.light_on:
                await client.set_flat_light(True)
            return
        if loop.time() >= deadline:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="flat_panel_brightness_not_reported",
                translation_placeholders={
                    "level": str(level),
                    "seconds": f"{_SETTLE_TIMEOUT:g}",
                },
            )
        await asyncio.sleep(_SETTLE_INTERVAL)


def dimmest_level(driver_range: tuple[float, float]) -> int:
    """Home Assistant's level 1 in driver units, and always above the minimum.

    An ASCOM panel set to its minimum, 0, is dark, and N.I.N.A.'s next
    `set-light` then lights it at `MaxBrightness`; a range under 128 would
    round level 1 down to it.
    """
    low, high = driver_range
    return max(round(low + (high - low) / _HA_MAX), math.floor(low) + 1)


class NinaFlatLight(NinaEntity, LightEntity):
    """The panel's light."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_translation_key = "flat_panel_light"

    # A bare turn_on's level when there is none to restore: dim, never full.
    _DEFAULT_ON_BRIGHTNESS = 1

    def __init__(self, coordinator: NinaCoordinator, entry: NinaConfigEntry) -> None:
        super().__init__(coordinator, entry, "flat_panel_light", kind="flat_device")
        self._remembered: int | None = None

    @property
    def _panel(self) -> FlatDeviceModel | None:
        return self.coordinator.data.snapshot.flat_device

    @property
    def _range(self) -> tuple[float, float] | None:
        """The driver's brightness range; `None` when it reports none."""
        panel = self._panel
        return None if panel is None else panel.brightness_range

    @property
    def _last_on_brightness(self) -> int:
        """The level a bare turn_on sends: the last requested this run, else
        the current one, else dim.
        """
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
            and self._range is not None
            and panel.supports_on_off is not False
        )

    @property
    def is_on(self) -> bool | None:
        panel = self._panel
        return None if panel is None else panel.light_on

    @property
    def brightness(self) -> int | None:
        """The driver's value, scaled into HA's 0-255."""
        panel, driver_range = self._panel, self._range
        if panel is None or panel.brightness is None or driver_range is None:
            return None
        low, high = driver_range
        return round((panel.brightness - low) / (high - low) * _HA_MAX)

    def _to_driver(self, ha_brightness: int) -> int:
        """Scale HA's 1-255 into driver units, refusing anything outside it.

        N.I.N.A. would clamp it silently; HA's light schema clamps first, so
        this is a guard. Every level stays above the driver's minimum, for
        the reason `dimmest_level` gives.
        """
        if not 1 <= ha_brightness <= _HA_MAX:
            raise ServiceValidationError(
                f"Brightness must be between 1 and {_HA_MAX}, got {ha_brightness}"
            )
        low, high = self._range or (0.0, 0.0)
        scaled = round(low + (ha_brightness / _HA_MAX) * (high - low))
        return max(scaled, dimmest_level((low, high)))

    async def async_turn_on(self, **kwargs: Any) -> None:
        # Never fall back to full: an idle panel's brightness scales to 0.
        requested = int(kwargs.get(ATTR_BRIGHTNESS, self._last_on_brightness))
        driver_value = self._to_driver(requested)
        with refusals_raised():
            await async_light_at(self.coordinator.client, driver_value)
        self._remembered = requested
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        # Brightness 0 darkens only an ASCOM panel; set-light turns off any.
        await self._async_send(self.coordinator.client.set_flat_light(False))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    # Not gated on `SupportsOnOff`, which a disconnected panel reports false;
    # `available` handles that.
    async_add_observed(
        entry,
        async_add_entities,
        lambda data: (
            [("flat_panel_light", lambda: NinaFlatLight(coordinator, entry))]
            if observed(data, "flat_device")
            else []
        ),
    )

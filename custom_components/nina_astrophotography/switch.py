"""Switch entities for N.I.N.A. Astrophotography – camera cooler and mount tracking."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
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


@dataclass
class NinaSwitchDescription(SwitchEntityDescription):
    """Extends SwitchEntityDescription with state and action callables."""

    is_on_fn: Any = None        # (data) → bool | None
    turn_on_fn: Any = None      # async (client) → None
    turn_off_fn: Any = None     # async (client) → None
    available_fn: Any = None    # (data) → bool


SWITCH_DESCRIPTIONS: list[NinaSwitchDescription] = [
    # ── Camera Cooler ─────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="camera_cooler_switch",
        name="Camera Cooler",
        icon="mdi:snowflake",
        is_on_fn=lambda d: bool(_safe(d, "camera", "Response", "CoolerOn")),
        # Cool to -10°C over 15 min when switched on; warm over 15 min when off
        turn_on_fn=lambda c: c.cool_camera(temperature=-10, minutes=15),
        turn_off_fn=lambda c: c.warm_camera(minutes=15),
        available_fn=lambda d: bool(_safe(d, "camera", "Response", "Connected")),
    ),
    # ── Mount Tracking ────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="mount_tracking_switch",
        name="Mount Tracking",
        icon="mdi:orbit",
        is_on_fn=lambda d: bool(_safe(d, "mount", "Response", "TrackingEnabled")),
        turn_on_fn=lambda c: c.set_tracking(True),
        turn_off_fn=lambda c: c.set_tracking(False),
        available_fn=lambda d: bool(_safe(d, "mount", "Response", "Connected"))
                              and not bool(_safe(d, "mount", "Response", "AtPark")),
    ),
    # ── Guider ────────────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="guider_switch",
        name="Autoguiding",
        icon="mdi:crosshairs-gps",
        is_on_fn=lambda d: _safe(d, "guider", "Response", "State") == "Guiding",
        turn_on_fn=lambda c: c.start_guiding(),
        turn_off_fn=lambda c: c.stop_guiding(),
        available_fn=lambda d: bool(_safe(d, "guider", "Response", "Connected")),
    ),
]


class NinaSwitch(CoordinatorEntity[NinaDataCoordinator], SwitchEntity):
    """A switch entity backed by the N.I.N.A. coordinator."""

    entity_description: NinaSwitchDescription

    def __init__(
        self,
        coordinator: NinaDataCoordinator,
        description: NinaSwitchDescription,
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
    def is_on(self) -> bool | None:
        if self.entity_description.is_on_fn and self.coordinator.data:
            try:
                return self.entity_description.is_on_fn(self.coordinator.data)
            except Exception:
                return None
        return None

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        if self.entity_description.available_fn:
            try:
                return bool(self.entity_description.available_fn(self.coordinator.data))
            except Exception:
                return False
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self.entity_description.turn_on_fn:
            await self.entity_description.turn_on_fn(self._client)
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if self.entity_description.turn_off_fn:
            await self.entity_description.turn_off_fn(self._client)
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
        NinaSwitch(coordinator, desc, client, entry.entry_id)
        for desc in SWITCH_DESCRIPTIONS
    )

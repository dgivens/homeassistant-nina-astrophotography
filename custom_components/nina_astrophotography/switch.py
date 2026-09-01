"""Switch entities for N.I.N.A. — cooler, tracking, guiding, flats and livestack."""
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

from .api import NinaApiClient
from .const import DOMAIN
from .coordinator import NinaDataCoordinator
from .device import device_info_for_key
from .helpers import safe

_LOGGER = logging.getLogger(__name__)


@dataclass
class NinaSwitchDescription(SwitchEntityDescription):
    """Extends SwitchEntityDescription with state and action callables."""

    is_on_fn: Any = None        # (data) -> bool | None
    turn_on_fn: Any = None      # async (client) -> None
    turn_off_fn: Any = None     # async (client) -> None
    available_fn: Any = None    # (data) -> bool


SWITCH_DESCRIPTIONS: list[NinaSwitchDescription] = [
    # ── Camera Cooler ─────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="camera_cooler_switch",
        name="Cooler",
        icon="mdi:snowflake",
        is_on_fn=lambda d: bool(safe(d, "camera", "Response", "CoolerOn")),
        # Cool to the camera's existing setpoint using the profile's default
        # ramp (-1); adjust the target with the cooling setpoint number entity.
        turn_on_fn=lambda c, d: c.cool_camera(
            temperature=safe(d, "camera", "Response", "TargetTemp") or -10,
            minutes=-1,
        ),
        turn_off_fn=lambda c, d: c.warm_camera(minutes=-1),
        available_fn=lambda d: bool(
            safe(d, "camera", "Response", "Connected")
        ) and bool(safe(d, "camera", "Response", "CanSetTemperature")),
    ),
    # ── Camera Dew Heater ─────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="camera_dew_heater_switch",
        name="Dew Heater",
        icon="mdi:heat-wave",
        is_on_fn=lambda d: bool(safe(d, "camera", "Response", "DewHeaterOn")),
        turn_on_fn=lambda c, d: c.set_dew_heater(True),
        turn_off_fn=lambda c, d: c.set_dew_heater(False),
        available_fn=lambda d: bool(safe(d, "camera", "Response", "HasDewHeater")),
    ),
    # ── Mount Tracking ────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="mount_tracking_switch",
        name="Tracking",
        icon="mdi:orbit",
        is_on_fn=lambda d: bool(safe(d, "mount", "Response", "TrackingEnabled")),
        turn_on_fn=lambda c, d: c.set_tracking(True),
        turn_off_fn=lambda c, d: c.set_tracking(False),
        available_fn=lambda d: bool(safe(d, "mount", "Response", "Connected"))
        and not bool(safe(d, "mount", "Response", "AtPark")),
    ),
    # ── Guider ────────────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="guider_switch",
        name="Autoguiding",
        icon="mdi:crosshairs-gps",
        is_on_fn=lambda d: safe(d, "guider", "Response", "State") == "Guiding",
        turn_on_fn=lambda c, d: c.start_guiding(),
        turn_off_fn=lambda c, d: c.stop_guiding(),
        available_fn=lambda d: bool(safe(d, "guider", "Response", "Connected")),
    ),
    # ── Flat Light ────────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="flat_light_switch",
        name="Light",
        icon="mdi:lightbulb",
        is_on_fn=lambda d: bool(safe(d, "flatdevice", "Response", "LightOn")),
        turn_on_fn=lambda c, d: c.set_flat_light(True),
        turn_off_fn=lambda c, d: c.set_flat_light(False),
        available_fn=lambda d: bool(safe(d, "flatdevice", "Response", "Connected"))
        and bool(safe(d, "flatdevice", "Response", "SupportsOnOff")),
    ),
    # ── Flat Cover ────────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="flat_cover_switch",
        name="Cover Open",
        icon="mdi:window-shutter-open",
        is_on_fn=lambda d: safe(d, "flatdevice", "Response", "CoverState") == "Open",
        turn_on_fn=lambda c, d: c.set_flat_cover(closed=False),
        turn_off_fn=lambda c, d: c.set_flat_cover(closed=True),
        available_fn=lambda d: bool(safe(d, "flatdevice", "Response", "Connected"))
        and bool(safe(d, "flatdevice", "Response", "SupportsOpenClose")),
    ),
    # ── Dome Follow ───────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="dome_follow_switch",
        name="Follow Mount",
        icon="mdi:link-variant",
        is_on_fn=lambda d: bool(safe(d, "dome", "Response", "IsFollowing"))
        or bool(safe(d, "dome", "Response", "DriverFollowing")),
        turn_on_fn=lambda c, d: c.set_dome_follow(True),
        turn_off_fn=lambda c, d: c.set_dome_follow(False),
        available_fn=lambda d: bool(safe(d, "dome", "Response", "Connected")),
    ),
    # ── Rotator Reverse ───────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="rotator_reverse_switch",
        name="Reverse Direction",
        icon="mdi:swap-horizontal",
        entity_category=EntityCategory.CONFIG,
        is_on_fn=lambda d: bool(safe(d, "rotator", "Response", "Reverse")),
        turn_on_fn=lambda c, d: c.set_rotator_reverse(True),
        turn_off_fn=lambda c, d: c.set_rotator_reverse(False),
        available_fn=lambda d: bool(safe(d, "rotator", "Response", "CanReverse")),
    ),
    # ── Livestack ─────────────────────────────────────────────────────────────
    NinaSwitchDescription(
        key="livestack_switch",
        name="Livestack",
        icon="mdi:layers-triple",
        is_on_fn=lambda d: str(safe(d, "livestack", "Response") or "").lower() == "running",
        turn_on_fn=lambda c, d: c.start_livestack(),
        turn_off_fn=lambda c, d: c.stop_livestack(),
        # /livestack/status always answers, even without the Livestack plugin;
        # an empty response means the endpoint is unavailable.
        available_fn=lambda d: safe(d, "livestack", "Response") is not None,
    ),
]


class NinaSwitch(CoordinatorEntity[NinaDataCoordinator], SwitchEntity):
    """A switch entity backed by the N.I.N.A. coordinator."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

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
        self._attr_device_info = device_info_for_key(entry_id, description.key)

    @property
    def is_on(self) -> bool | None:
        if self.entity_description.is_on_fn and self.coordinator.data:
            try:
                return self.entity_description.is_on_fn(self.coordinator.data)
            except Exception:  # noqa: BLE001
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

    async def _run(self, fn) -> None:
        if not fn:
            return
        try:
            await fn(self._client, self.coordinator.data or {})
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Switch %s failed: %s", self.entity_description.key, exc)
            return
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._run(self.entity_description.turn_on_fn)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._run(self.entity_description.turn_off_fn)


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

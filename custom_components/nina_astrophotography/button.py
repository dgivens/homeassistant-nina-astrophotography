"""Button entities for N.I.N.A. — one-shot action triggers.

There is no dither endpoint in the Advanced API; dithering is driven by the
sequence's dither settings, so no dither button is offered here.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NinaApiClient
from .const import DOMAIN
from .device import device_info_for_key

_LOGGER = logging.getLogger(__name__)


@dataclass
class NinaButtonDescription(ButtonEntityDescription):
    """Extends ButtonEntityDescription with a press action callable."""

    press_fn: Any = None  # async (client) -> None


BUTTON_DESCRIPTIONS: list[NinaButtonDescription] = [
    # ── Focuser ──────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_auto_focus",
        name="Run Auto Focus",
        icon="mdi:image-filter-center-focus",
        press_fn=lambda c: c.auto_focus(),
    ),
    NinaButtonDescription(
        key="btn_auto_focus_cancel",
        name="Cancel Auto Focus",
        icon="mdi:focus-field-horizontal",
        press_fn=lambda c: c.auto_focus(cancel=True),
    ),
    NinaButtonDescription(
        key="btn_focuser_stop",
        name="Stop Focuser",
        icon="mdi:stop-circle-outline",
        press_fn=lambda c: c.stop_focuser(),
    ),

    # ── Mount ────────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_mount_find_home",
        name="Find Home",
        icon="mdi:home-import-outline",
        press_fn=lambda c: c.find_home(),
    ),
    NinaButtonDescription(
        key="btn_mount_park",
        name="Park Mount",
        icon="mdi:parking",
        press_fn=lambda c: c.park_mount(),
    ),
    NinaButtonDescription(
        key="btn_mount_unpark",
        name="Unpark Mount",
        icon="mdi:arrow-up-circle-outline",
        press_fn=lambda c: c.unpark_mount(),
    ),
    NinaButtonDescription(
        key="btn_mount_stop_slew",
        name="Stop Slew",
        device_class=ButtonDeviceClass.RESTART,
        icon="mdi:stop-circle",
        press_fn=lambda c: c.stop_slew(),
    ),
    NinaButtonDescription(
        key="btn_mount_flip",
        name="Meridian Flip",
        icon="mdi:swap-horizontal-bold",
        press_fn=lambda c: c.meridian_flip(),
    ),
    NinaButtonDescription(
        key="btn_mount_set_park_position",
        name="Set Mount Park Position",
        icon="mdi:map-marker-check",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.set_mount_park_position(),
    ),

    # ── Guider ───────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_guider_start",
        name="Start Guiding",
        icon="mdi:crosshairs-gps",
        press_fn=lambda c: c.start_guiding(),
    ),
    NinaButtonDescription(
        key="btn_guider_start_calibrate",
        name="Start Guiding with Calibration",
        icon="mdi:target-variant",
        press_fn=lambda c: c.start_guiding(calibrate=True),
    ),
    NinaButtonDescription(
        key="btn_guider_stop",
        name="Stop Guiding",
        icon="mdi:crosshairs",
        press_fn=lambda c: c.stop_guiding(),
    ),
    NinaButtonDescription(
        key="btn_guider_clear_calibration",
        name="Clear Guider Calibration",
        icon="mdi:eraser",
        entity_category=EntityCategory.CONFIG,
        press_fn=lambda c: c.clear_guider_calibration(),
    ),

    # ── Rotator ──────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_rotator_stop",
        name="Stop Rotator",
        icon="mdi:rotate-right",
        press_fn=lambda c: c.stop_rotator(),
    ),

    # ── Sequence ─────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_sequence_start",
        name="Start Sequence",
        icon="mdi:play-circle-outline",
        press_fn=lambda c: c.start_sequence(),
    ),
    NinaButtonDescription(
        key="btn_sequence_stop",
        name="Stop Sequence",
        icon="mdi:stop-circle-outline",
        press_fn=lambda c: c.stop_sequence(),
    ),
    NinaButtonDescription(
        key="btn_sequence_skip",
        name="Skip Sequence Item",
        icon="mdi:skip-next-circle-outline",
        press_fn=lambda c: c.skip_sequence_item(),
    ),
    NinaButtonDescription(
        key="btn_sequence_reset",
        name="Reset Sequence",
        device_class=ButtonDeviceClass.RESTART,
        icon="mdi:restart",
        press_fn=lambda c: c.reset_sequence(),
    ),

    # ── Dome ─────────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_dome_open",
        name="Open Dome",
        icon="mdi:home-circle-outline",
        press_fn=lambda c: c.open_dome(),
    ),
    NinaButtonDescription(
        key="btn_dome_close",
        name="Close Dome",
        icon="mdi:home-circle",
        press_fn=lambda c: c.close_dome(),
    ),
    NinaButtonDescription(
        key="btn_dome_park",
        name="Park Dome",
        icon="mdi:home-lock",
        press_fn=lambda c: c.park_dome(),
    ),
    NinaButtonDescription(
        key="btn_dome_home",
        name="Home Dome",
        icon="mdi:home-import-outline",
        press_fn=lambda c: c.home_dome(),
    ),
    NinaButtonDescription(
        key="btn_dome_stop",
        name="Stop Dome",
        icon="mdi:stop-circle-outline",
        press_fn=lambda c: c.stop_dome(),
    ),
    NinaButtonDescription(
        key="btn_dome_sync",
        name="Sync Dome to Mount",
        icon="mdi:sync",
        press_fn=lambda c: c.sync_dome(),
    ),

    # ── Camera ───────────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_camera_abort",
        name="Abort Capture",
        icon="mdi:camera-off",
        press_fn=lambda c: c.abort_capture(),
    ),
    NinaButtonDescription(
        key="btn_camera_cool_cancel",
        name="Cancel Cooling",
        icon="mdi:snowflake-off",
        press_fn=lambda c: c.cool_camera(temperature=0, minutes=-1, cancel=True),
    ),
    NinaButtonDescription(
        key="btn_camera_warm_cancel",
        name="Cancel Warming",
        icon="mdi:fire-off",
        press_fn=lambda c: c.warm_camera(minutes=-1, cancel=True),
    ),

    # ── Flat Wizard ──────────────────────────────────────────────────────────
    NinaButtonDescription(
        key="btn_flats_stop",
        name="Stop Flat Wizard",
        icon="mdi:stop-circle-outline",
        press_fn=lambda c: c.stop_flats(),
    ),
]


class NinaButton(ButtonEntity):
    """A button entity that fires a one-shot N.I.N.A. API action."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    entity_description: NinaButtonDescription

    def __init__(
        self,
        description: NinaButtonDescription,
        client: NinaApiClient,
        entry_id: str,
    ) -> None:
        self.entity_description = description
        self._client = client
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info_for_key(entry_id, description.key)

    async def async_press(self) -> None:
        if self.entity_description.press_fn:
            try:
                await self.entity_description.press_fn(self._client)
            except Exception as exc:  # noqa: BLE001
                _LOGGER.error(
                    "Button %s failed: %s", self.entity_description.key, exc
                )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: NinaApiClient = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities(
        NinaButton(desc, client, entry.entry_id)
        for desc in BUTTON_DESCRIPTIONS
    )

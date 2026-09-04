"""Button entities for N.I.N.A. Astrophotography – one-shot action triggers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api import NinaApiClient, NinaApiError, NinaConnectionError
from .const import DOMAIN
from .coordinator import NinaDataCoordinator



@dataclass
class NinaButtonDescription(ButtonEntityDescription):
    """Extends ButtonEntityDescription with press action callable."""

    press_fn: Any = None  # async (client) → None


BUTTON_DESCRIPTIONS: list[NinaButtonDescription] = [
    NinaButtonDescription(
        key="btn_auto_focus",
        name="Run Auto Focus",
        icon="mdi:image-filter-center-focus",
        press_fn=lambda c: c.auto_focus(),
    ),
    NinaButtonDescription(
        key="btn_mount_find_home",
        name="Mount Find Home",
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
        key="btn_camera_abort",
        name="Abort Capture",
        icon="mdi:camera-off",
        press_fn=lambda c: c.abort_capture(),
    ),
    NinaButtonDescription(
        key="btn_guider_start",
        name="Start Guiding",
        icon="mdi:crosshairs-gps",
        press_fn=lambda c: c.start_guiding(),
    ),
    NinaButtonDescription(
        key="btn_guider_stop",
        name="Stop Guiding",
        icon="mdi:crosshairs",
        press_fn=lambda c: c.stop_guiding(),
    ),
]


class NinaButton(ButtonEntity):
    """A button entity that fires a one-shot N.I.N.A. API action."""

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
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }

    async def async_press(self) -> None:
        """Handle button press — call the N.I.N.A. API action."""
        if self.entity_description.press_fn:
            try:
                await self.entity_description.press_fn(self._client)
            except (NinaApiError, NinaConnectionError) as exc:
                raise HomeAssistantError(
                    f"{self.entity_description.name} failed: {exc}"
                ) from exc


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

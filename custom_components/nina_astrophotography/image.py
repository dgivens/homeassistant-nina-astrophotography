"""HA Image entity for N.I.N.A. latest captured frame.

Exposes the last captured frame as a native Home Assistant image entity.
This means it can be used in the built-in Picture Entity Card as well as
the custom nina-image-panel-card.

The image is fetched from the Advanced API's streaming endpoint:
  GET /v2/api/image?index=0&stream=true&useAutoStretch=true

The entity updates whenever the IMAGE-SAVE WebSocket event fires, so the
HA image state reflects the last saved frame within a second of capture.
"""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import NinaApiClient, NinaApiError, NinaConnectionError
from .const import DOMAIN
from .coordinator import NinaDataCoordinator

_LOGGER = logging.getLogger(__name__)


class NinaLatestImageEntity(ImageEntity):
    """HA Image entity backed by the N.I.N.A. streaming image endpoint.

    The image bytes are fetched on demand when HA or a frontend requests them.
    The entity's image_last_updated timestamp is bumped on every IMAGE-SAVE
    WebSocket event so frontends know to refresh.
    """

    _attr_name = "Latest Captured Frame"
    _attr_icon = "mdi:image-star"
    _attr_content_type = "image/jpeg"
    _attr_should_poll = False

    def __init__(
        self,
        hass: HomeAssistant,
        client: NinaApiClient,
        ws_client,
        entry_id: str,
    ) -> None:
        super().__init__(hass)
        self._client = client
        self._ws_client = ws_client
        self._unsubscribe = None
        self._attr_unique_id = f"{entry_id}_latest_image"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }
        self._image_bytes: bytes | None = None
        # HA renders image_last_updated as the entity state, so it must be
        # timezone-aware or the frontend reads it as local time.
        self._last_updated: datetime = dt_util.utcnow()

    @property
    def image_last_updated(self) -> datetime:
        return self._last_updated

    async def async_image(self) -> bytes | None:
        """Fetch and return the latest image bytes."""
        try:
            data = await self._client.get_image_bytes(index=0, quality=85, stretch=True)
            self._image_bytes = data
            return data
        except (NinaApiError, NinaConnectionError) as exc:
            _LOGGER.debug("Could not fetch N.I.N.A. image: %s", exc)
            return self._image_bytes  # return cached bytes on failure

    async def async_added_to_hass(self) -> None:
        """Subscribe to IMAGE-SAVE events.

        Here rather than in async_setup_entry so hass is set before an event
        can arrive, and so the unsubscribe is paired with removal.
        """
        await super().async_added_to_hass()
        self._unsubscribe = self._ws_client.add_listener(
            "IMAGE-SAVE", lambda _response: self._mark_updated()
        )

    async def async_will_remove_from_hass(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _mark_updated(self) -> None:
        """A new frame was saved; bump the timestamp so frontends refetch."""
        self._last_updated = dt_util.utcnow()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: NinaApiClient = entry_data["client"]
    ws_client = entry_data["ws_client"]

    async_add_entities(
        [NinaLatestImageEntity(hass, client, ws_client, entry.entry_id)]
    )

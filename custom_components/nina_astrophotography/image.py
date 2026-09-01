"""Image entities for N.I.N.A. — the latest captured frame and a UI screenshot.

Frames come from the streaming image endpoint:
  GET /v2/api/image/{index}?stream=true&autoPrepare=true
with index -1 meaning the most recent frame. The entity's timestamp is bumped
on every IMAGE-SAVE WebSocket event so frontends refresh right after a capture.
"""
from __future__ import annotations

import logging

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .api import NinaApiClient, NinaApiError, NinaConnectionError
from .const import DOMAIN
from .device import HUB, device_info_for

_LOGGER = logging.getLogger(__name__)

LATEST_IMAGE_INDEX = -1


class _NinaImageBase(ImageEntity):
    """Shared plumbing for the N.I.N.A. image entities."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    _attr_content_type = "image/jpeg"
    _attr_should_poll = False

    def __init__(self, hass: HomeAssistant, client: NinaApiClient, entry_id: str,
                 unique_suffix: str) -> None:
        super().__init__(hass)
        self._client = client
        self._attr_unique_id = f"{entry_id}_{unique_suffix}"
        self._attr_device_info = device_info_for(entry_id, HUB)
        self._cached: bytes | None = None
        self._attr_image_last_updated = dt_util.utcnow()

    async def _fetch(self) -> bytes:
        raise NotImplementedError

    async def async_image(self) -> bytes | None:
        try:
            self._cached = await self._fetch()
        except (NinaApiError, NinaConnectionError) as exc:
            _LOGGER.debug("Could not fetch N.I.N.A. image: %s", exc)
        return self._cached

    def mark_updated(self) -> None:
        """Bump the timestamp so frontends know to re-fetch."""
        self._attr_image_last_updated = dt_util.utcnow()
        self.async_write_ha_state()


class NinaLatestImageEntity(_NinaImageBase):
    """The most recently captured frame."""

    _attr_name = "Latest Captured Frame"
    _attr_icon = "mdi:image-star"

    def __init__(self, hass, client, entry_id):
        super().__init__(hass, client, entry_id, "latest_image")

    async def _fetch(self) -> bytes:
        return await self._client.get_image_bytes(
            index=LATEST_IMAGE_INDEX, quality=85, auto_prepare=True
        )


class NinaScreenshotEntity(_NinaImageBase):
    """A screenshot of the N.I.N.A. application window."""

    _attr_name = "Screenshot"
    _attr_icon = "mdi:monitor-screenshot"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, hass, client, entry_id):
        super().__init__(hass, client, entry_id, "app_screenshot")

    async def _fetch(self) -> bytes:
        return await self._client.get_screenshot_bytes(quality=75)

    async def async_image(self) -> bytes | None:
        # A screenshot is only ever as fresh as the moment it is requested.
        self._attr_image_last_updated = dt_util.utcnow()
        return await super().async_image()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    client: NinaApiClient = entry_data["client"]
    ws_client = entry_data["ws_client"]

    latest = NinaLatestImageEntity(hass, client, entry.entry_id)
    async_add_entities([latest, NinaScreenshotEntity(hass, client, entry.entry_id)])

    # A newly saved frame invalidates the cached image.
    ws_client.add_listener("IMAGE-SAVE", lambda response: latest.mark_updated())

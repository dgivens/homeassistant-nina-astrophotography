"""Proxy frames from the image history, so a card fetches from Home
Assistant's own origin.

N.I.N.A. serves plain HTTP, and a browser refuses an HTTPS dashboard's fetch
of it as mixed content.
"""

from datetime import datetime

from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .api.errors import NinaCommandError, NinaError, NinaNoImageError
from .api.v2.client import IMAGE_QUALITY, NinaClientV2
from .const import DOMAIN


def _client_for_entity(hass: HomeAssistant, entity_id: str) -> NinaClientV2 | None:
    """The rig's client behind one of its entities, or `None` if the entity
    or its loaded entry cannot be found.
    """
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None or entity_entry.platform != DOMAIN:
        return None
    if entity_entry.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data.coordinator.client


def _bad_image_request() -> web.Response:
    return web.Response(
        status=400,
        text=(
            "index must be >= 0, quality between 1 and 100, width >= 1, "
            "date an ISO 8601 time with an offset"
        ),
    )


class NinaImageProxyView(HomeAssistantView):
    """`GET /api/nina_astrophotography/image/{entity_id}/{index}`.

    `index` 0 is the newest frame, as in `recent_frames`, and `date` that
    entry's own `date`: with it the proxy serves that frame or none, however
    many the rig saved since the card's list. `width` scales the frame down to
    that many pixels across, and `thumbnail=true` asks for the rig's own
    thumbnail before a render.
    """

    url = "/api/nina_astrophotography/image/{entity_id}/{index}"
    name = "api:nina_astrophotography:image"

    async def get(
        self, request: web.Request, entity_id: str, index: str
    ) -> web.Response:
        try:
            frame_index = int(index)
            quality = int(request.query.get("quality", IMAGE_QUALITY))
            width = int(request.query["width"]) if "width" in request.query else None
            date = (
                datetime.fromisoformat(request.query["date"])
                if "date" in request.query
                else None
            )
        except ValueError:
            return _bad_image_request()
        if (
            frame_index < 0
            or not 1 <= quality <= 100
            or (width is not None and width < 1)
            or (date is not None and date.tzinfo is None)
        ):
            return _bad_image_request()

        hass: HomeAssistant = request.app[KEY_HASS]
        client = _client_for_entity(hass, entity_id)
        if client is None:
            return web.Response(status=404)

        # The card omits the parameter to ask for the linear frame.
        auto_prepare = request.query.get("autoPrepare") == "true"
        try:
            image_bytes = await client.get_recent_image_bytes(
                frame_index,
                quality=quality,
                auto_prepare=auto_prepare,
                width=width,
                thumbnail=request.query.get("thumbnail") == "true",
                date=date,
            )
        except NinaNoImageError, NinaCommandError:
            # An empty history, or an index no longer held.
            return web.Response(status=404)
        except NinaError:
            return web.Response(status=502)

        return web.Response(
            body=image_bytes,
            content_type="image/jpeg",
            # Fetched through a signed URL, a short-lived bearer credential.
            headers={"Cache-Control": "no-store"},
        )


def async_register_views(hass: HomeAssistant) -> None:
    """Register the proxy once, regardless of how many entries load."""
    hass.http.register_view(NinaImageProxyView())

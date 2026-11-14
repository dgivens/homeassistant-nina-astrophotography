"""Proxy frames from the image history and live stacks, so a card fetches
from Home Assistant's own origin.

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
from .api.v2.client import IMAGE_QUALITY
from .const import DOMAIN
from .coordinator import NinaCoordinator


def _coordinator_for_entity(
    hass: HomeAssistant, entity_id: str
) -> NinaCoordinator | None:
    """The rig's coordinator behind one of its entities, or `None` if the
    entity or its loaded entry cannot be found.
    """
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None or entity_entry.platform != DOMAIN:
        return None
    if entity_entry.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data.coordinator


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

    `index` is a `recent_frames` entry's `age`, 0 the newest frame of any
    type, and `date` that entry's own `date`: with it a render is of that frame
    or none, however many the rig saved since the card's list. `width` scales the frame down to
    that many pixels across. `thumbnail=true` asks for the rig's own thumbnail
    before a render, which `get_thumbnail_bytes` says is not always that
    frame's: a preview only, never what a frame's readings are shown over.
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
        coordinator = _coordinator_for_entity(hass, entity_id)
        if coordinator is None:
            return web.Response(status=404)

        # The card omits the parameter to ask for the linear frame.
        auto_prepare = request.query.get("autoPrepare") == "true"
        try:
            image_bytes = await coordinator.client.get_recent_image_bytes(
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
        return _jpeg(image_bytes)


class NinaLivestackProxyView(HomeAssistantView):
    """`GET /api/nina_astrophotography/livestack/{entity_id}?target=…&filter=…`.

    One target and filter's stack, as `image.livestack`'s `stacks` lists them.
    Both are in the query, since either may hold a `/`. `width` scales the
    stack down to that many pixels across.

    Only a pair the rig itself listed is fetched: the two strings become path
    segments on the rig, and an arbitrary one can reach a route that is not an
    image.
    """

    url = "/api/nina_astrophotography/livestack/{entity_id}"
    name = "api:nina_astrophotography:livestack"

    async def get(self, request: web.Request, entity_id: str) -> web.Response:
        target = request.query.get("target", "")
        filter_name = request.query.get("filter", "")
        try:
            quality = int(request.query.get("quality", IMAGE_QUALITY))
            width = int(request.query["width"]) if "width" in request.query else None
        except ValueError:
            return _bad_livestack_request()
        if (
            not target
            or not filter_name
            or not 1 <= quality <= 100
            or (width is not None and width < 1)
        ):
            return _bad_livestack_request()

        hass: HomeAssistant = request.app[KEY_HASS]
        coordinator = _coordinator_for_entity(hass, entity_id)
        if coordinator is None or coordinator.data is None:
            return web.Response(status=404)
        if not any(
            stack.target == target and stack.filter_name == filter_name
            for stack in coordinator.data.stacks
        ):
            return web.Response(status=404)

        try:
            image_bytes = await coordinator.client.get_livestack_image_bytes(
                target, filter_name, quality=quality, width=width
            )
        except NinaNoImageError, NinaCommandError:
            # No such stack, or one a N.I.N.A. restart dropped.
            return web.Response(status=404)
        except NinaError:
            return web.Response(status=502)
        return _jpeg(image_bytes)


def _bad_livestack_request() -> web.Response:
    return web.Response(
        status=400,
        text="target and filter are required, quality between 1 and 100, width >= 1",
    )


def _jpeg(image_bytes: bytes) -> web.Response:
    return web.Response(
        body=image_bytes,
        content_type="image/jpeg",
        # Fetched through a signed URL, a short-lived bearer credential.
        headers={"Cache-Control": "no-store"},
    )


def async_register_views(hass: HomeAssistant) -> None:
    """Register the proxies once, regardless of how many entries load."""
    hass.http.register_view(NinaImageProxyView())
    hass.http.register_view(NinaLivestackProxyView())

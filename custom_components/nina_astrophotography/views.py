"""Proxy an image byte-for-byte, so a dashboard card only ever talks to
Home Assistant's own origin.

N.I.N.A.'s Advanced API is plain HTTP-only; Home Assistant is commonly
served over HTTPS, and a browser refuses an HTTPS page's own `fetch()` of
an HTTP resource as mixed content. Routing the bytes through here — same
origin, same TLS, same auth — is what a dashboard card actually needs;
`image.py`'s `ImageEntity` already does the equivalent for the single
"latest frame", this generalizes it to an arbitrary history index.

Deliberately NOT under `api/`: `api/` is the version-independent, HA-free
seam (nothing there imports `homeassistant`), and a `HomeAssistantView`
inherently does. Keep it here even if that seems worth tidying later.
"""
from __future__ import annotations

from aiohttp import web
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .api.errors import NinaCommandError, NinaError, NinaNoImageError
from .api.v2.client import NinaClientV2
from .const import DOMAIN


def _client_for_entity(hass: HomeAssistant, entity_id: str) -> NinaClientV2 | None:
    """The rig's client behind one of its entities, or `None`.

    `None` covers every way this can fail to resolve — no such entity, an
    entity from a different integration, a config entry id it never got, one
    that no longer exists, or one that exists but is not loaded — as one
    outcome: a request naming any of these all answer the same 404, never a
    traceback.
    """
    entity_entry = er.async_get(hass).async_get(entity_id)
    if entity_entry is None or entity_entry.platform != DOMAIN:
        return None
    if entity_entry.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entity_entry.config_entry_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry.runtime_data.client


class NinaImageProxyView(HomeAssistantView):
    """`GET /api/nina_astrophotography/image/{entity_id}/{index}`.

    `index` counts back from the newest frame — 0 is newest, matching
    `session.recent_frames`, the ordering the card and the sensor attribute
    both use. N.I.N.A.'s own `/image/{index}` counts the OTHER way: 0 is the
    OLDEST frame of the process's whole history, confirmed by inspecting
    real frames from a live rig (the spec only says "the index of the image
    to get", either direction). Translating needs the live count — cached
    client-side history can lag a frame behind what N.I.N.A. holds right
    now, and an off-by-one here silently serves the wrong image.
    """

    url = "/api/nina_astrophotography/image/{entity_id}/{index}"
    name = "api:nina_astrophotography:image"

    async def get(
        self, request: web.Request, entity_id: str, index: str
    ) -> web.Response:
        try:
            frame_index = int(index)
            quality = int(request.query.get("quality", 85))
            if frame_index < 0 or not 1 <= quality <= 100:
                raise ValueError
        except ValueError:
            return web.Response(
                status=400, text="index must be >= 0, quality between 1 and 100"
            )

        hass: HomeAssistant = request.app[KEY_HASS]
        client = _client_for_entity(hass, entity_id)
        if client is None:
            return web.Response(status=404)

        # Absent, not "false": the card omits the param entirely to ask for
        # the linear frame, mirroring `NinaClientV2.get_image_bytes`'s own
        # "only sent when true" contract for this parameter.
        auto_prepare = request.query.get("autoPrepare") == "true"
        try:
            count = await client.get_image_history_count()
            if frame_index >= count:
                return web.Response(status=404)
            image_bytes = await client.get_image_bytes(
                count - 1 - frame_index, quality=quality, auto_prepare=auto_prepare
            )
        except (NinaNoImageError, NinaCommandError):
            # Nothing to render, or the handler declined — an empty history,
            # or an index the rig no longer holds. Ordinary, not a defect.
            return web.Response(status=404)
        except NinaError:
            return web.Response(status=502)

        return web.Response(
            body=image_bytes,
            content_type="image/jpeg",
            # The signed URL this is fetched through is itself a bearer
            # credential for its short TTL; nothing should cache it further.
            headers={"Cache-Control": "no-store"},
        )


def async_register_views(hass: HomeAssistant) -> None:
    """Register the proxy once, regardless of how many entries load."""
    hass.http.register_view(NinaImageProxyView())

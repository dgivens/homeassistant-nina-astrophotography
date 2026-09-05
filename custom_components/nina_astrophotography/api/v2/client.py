"""ninaAPI v2 HTTP client.

Everything that knows a path, a parameter name or the envelope's shape lives
here. Above api/, nothing does: every public getter returns a model.

The HTTP status is almost always 200: the handler layer never assigns it, so
refused commands, 409s and handler exceptions all arrive as HTTP 200 with the
real code in the body's StatusCode. Only routing and parameter-binding failures
produce a real 4xx, and those return EmbedIO HTML rather than an envelope.

Classification is on the pair (StatusCode, Error), never the code alone:
"Sequence is not initialized" is raised by ten guards with 409 on
/sequence/{json,state,start,stop,reset,set-target,skip} and 400 on
/sequence/{edit,load}. The OpenAPI document calls it "Sequencer not
initialized"; the wire says "Sequence is not initialized". Match the wire.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from ..errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from ..models import (
    EquipmentSnapshot,
    FlatsStatus,
    Frame,
    LivestackStatus,
    NinaEvent,
    ProfileSettings,
    SequenceNode,
    VersionInfo,
)
from .mapper import (
    map_equipment_info,
    map_event,
    map_flats_status,
    map_frame,
    map_livestack_status,
    map_profile,
    map_sequence,
    rig_offset,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Pre-handler statuses meaning the path itself is not served.
_NOT_SERVED = (404, 405, 501)

# "No data yet" — ordinary states, normalized to None/[] rather than raised.
_NO_DATA_MESSAGES = ("index out of range", "is not initialized")


class NinaClientV2:
    """Async client for ninaAPI v2 (2.2.15.x)."""

    def __init__(self, host: str, port: int, session: aiohttp.ClientSession) -> None:
        self.base_url = f"http://{host}:{port}/v2/api"
        self._session = session
        # The rig's UTC offset, read from the mount's clock on each
        # /equipment/info. Naive log-scraped event times are in this offset and
        # it is the only place the API states it; the last known value is kept
        # across a mount disconnect, which drops the clock from the wire.
        self._rig_offset: timedelta | None = None

    # ── transport ────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Return the unwrapped Response, or raise. `None` means no data yet."""
        url = self.base_url + path
        try:
            async with self._session.get(url, params=params, timeout=_TIMEOUT) as resp:
                status = resp.status
                body = await resp.text()
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise NinaConnectionError(f"Timeout reaching N.I.N.A. at {url}") from exc
        except aiohttp.ClientError as exc:
            # ClientError, not ClientConnectorError: a crashed N.I.N.A. raises
            # ServerDisconnectedError and a truncated reply ClientPayloadError.
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

        if status != 200:
            raise self._pre_handler_error(path, status, body)
        if not body.strip():
            # Sequence serialization failure: empty body, no envelope.
            raise NinaUnavailableError(f"{path} returned an empty body")
        return self._unwrap(path, self._decode(path, body))

    @staticmethod
    def _pre_handler_error(path: str, status: int, body: str) -> Exception:
        summary = " ".join(body.split())[:120]
        message = f"GET {path} -> {status}: {summary}" if summary else f"GET {path} -> {status}"
        if status in _NOT_SERVED:
            return NinaEndpointError(message)
        if 400 <= status < 500:
            # EmbedIO routing/binding failure: permanent, unlike an envelope 400.
            return NinaRequestError(message)
        return NinaUnavailableError(message)

    @staticmethod
    def _decode(path: str, body: str) -> Any:
        try:
            return json.loads(body)
        except ValueError as exc:
            raise NinaUnavailableError(f"{path} returned a non-JSON body") from exc

    @staticmethod
    def _unwrap(path: str, payload: Any) -> Any:
        if not isinstance(payload, dict) or "Success" not in payload:
            raise NinaUnavailableError(f"{path} returned no envelope")

        error = str(payload.get("Error") or "")
        status = payload.get("StatusCode")

        if payload.get("Success") is False:
            # Seven handlers assign Success from a driver boolean and answer
            # Success: false, Error: "", StatusCode: 200 on a call that worked.
            if not error and status in (None, 200):
                return payload.get("Response")
            if any(message in error.lower() for message in _NO_DATA_MESSAGES):
                return None
            if isinstance(status, int) and status >= 500:
                raise NinaUnavailableError(f"{path}: {error} (StatusCode {status})")
            raise NinaCommandError(
                f"{path}: {error or 'unknown error'} (StatusCode {status})",
                status_code=status if isinstance(status, int) else None,
                api_error=error,
            )
        return payload.get("Response")

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_versions(self) -> VersionInfo:
        api = await self._get("/version")
        nina = await self._get("/version/nina")
        return VersionInfo(
            api_version=str(api) if api is not None else None,
            nina_version=str(nina) if nina is not None else None,
        )

    async def get_application_start(self) -> str | None:
        value = await self._get("/application-start")
        return str(value) if value is not None else None

    async def get_equipment(self) -> EquipmentSnapshot:
        wire = await self._get("/equipment/info") or {}
        self._rig_offset = rig_offset(wire) or self._rig_offset
        return map_equipment_info(wire)

    async def get_frames(self, *, include_all: bool = False,
                         generation: str | None = None) -> list[Frame]:
        """`include_all`, not `all` — the wire parameter stays `all`; only the
        keyword differs, to leave the builtin unshadowed.

        Bare /image-history answers the latest frame as a single object;
        ?all=true answers the list.
        """
        params = {"all": "true"} if include_all else None
        response = await self._get("/image-history", params)
        if response is None:
            return []
        wire = response if isinstance(response, list) else [response]
        return [map_frame(item, generation) for item in wire]

    async def get_image_history_count(self) -> int:
        return int(await self._get("/image-history", {"count": "true"}) or 0)

    async def get_events(self, generation: str | None = None) -> list[NinaEvent]:
        events: list[NinaEvent] = []
        for item in await self._raw_event_history():
            try:
                events.append(map_event(item, generation, rig_offset=self._rig_offset))
            except ValueError as exc:
                _LOGGER.debug("Skipping unmappable event %s: %s", item, exc)
        return events

    async def _raw_event_history(self) -> list[dict]:
        """The stored events as sent. Package-private: the event socket replays
        from it with its own generation bookkeeping."""
        return await self._get("/event-history") or []

    async def get_sequence(self) -> SequenceNode | None:
        return map_sequence(await self._get("/sequence/json"))

    async def get_flats(self) -> FlatsStatus:
        return map_flats_status(await self._get("/flats/status") or {})

    async def get_livestack(self) -> LivestackStatus:
        return map_livestack_status(await self._get("/livestack/status") or {})

    async def get_profile(self) -> ProfileSettings:
        return map_profile(await self._get("/profile/show", {"active": "true"}) or {})

    async def get_image_bytes(self, index: int, *, quality: int = 85,
                              auto_prepare: bool = True) -> bytes:
        """Fetch a rendered frame.

        autoPrepare, not useAutoStretch: an unknown parameter binds nothing and
        is not rejected, so the request succeeds and returns the linear frame.
        """
        path = f"/image/{index}"
        params: dict[str, Any] = {"stream": "true", "quality": quality}
        if auto_prepare:
            params["autoPrepare"] = "true"
        url = self.base_url + path
        try:
            async with self._session.get(url, params=params,
                                         timeout=_IMAGE_TIMEOUT) as resp:
                if resp.status != 200:
                    raise self._pre_handler_error(path, resp.status, "")
                # With stream=true a real image is served as image/*; a refusal
                # arrives as 200 carrying the JSON envelope.
                if (resp.content_type or "").startswith("image/"):
                    return await resp.read()
                self._unwrap(path, await resp.json(content_type=None))
                raise NinaUnavailableError(f"{path} returned no image")
        except (asyncio.TimeoutError, TimeoutError) as exc:
            raise NinaConnectionError(f"Timeout fetching {url}") from exc
        except aiohttp.ClientError as exc:
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

    # ── commands ─────────────────────────────────────────────────────────────
    #
    # Parameter names are verified by live probe and pinned by test. The spec
    # declares set-light's parameter as literally `True`; `set-light?True=true`
    # answers Success: true and leaves the panel alone. Never generate these.
    #
    # No command on this API can be confirmed from its own response: parameters
    # default silently, values are clamped silently, and the state changes
    # seconds later. Read state back from the poll.

    async def set_flat_light(self, on: bool) -> None:
        await self._get("/equipment/flatdevice/set-light",
                        {"on": "true" if on else "false"})

    async def set_flat_brightness(self, brightness: int) -> None:
        await self._get("/equipment/flatdevice/set-brightness",
                        {"brightness": brightness})

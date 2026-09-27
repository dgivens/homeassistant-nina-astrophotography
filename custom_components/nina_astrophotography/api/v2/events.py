"""The N.I.N.A. event socket, inside the seam.

Subscribers receive `NinaEvent` models. No dict crosses `api/`.

Two shapes of `IMAGE-SAVE` exist: the live socket carries `ImageStatistics` and
no `Time`, while `/event-history` carries `Time` and no statistics — every
stored copy is exactly `{Event, Time}`. Replay therefore fixes only the
timestamp; it can never reconstruct a frame's measurements.

"""

import asyncio
from collections.abc import Callable
import contextlib
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

import aiohttp

from ..models import NinaEvent
from .mapper import map_event

_LOGGER = logging.getLogger(__name__)

WS_URL = "ws://{host}:{port}/v2/socket"

_RECONNECT_DELAY = 5
_MAX_RECONNECT_DELAY = 60


class NinaEventStream:
    """The push half of the data flow: one socket, many model subscribers.

    `generation` supplies the tag stamped onto every dispatched event: the
    coordinator's, from `/application-start`.
    """

    def __init__(
        self,
        host: str,
        port: int,
        session: aiohttp.ClientSession,
        *,
        generation: Callable[[], str | None] = lambda: None,
        rig_offset: Callable[[], timedelta | None] | None = None,
        on_connection: Callable[[bool], None] | None = None,
    ) -> None:
        self._url = WS_URL.format(host=host, port=port)
        self._session = session
        self._generation = generation
        self._rig_offset = rig_offset
        self._on_connection = on_connection
        self._subscribers: list[Callable[[NinaEvent], None]] = []
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self.connected = False

    # ── subscription ─────────────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[NinaEvent], None]) -> Callable[[], None]:
        """Subscribe to every event. No topic parameter — there are no channels."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def _dispatch(self, payload: Any) -> None:
        """Map one event payload and hand the model to every subscriber."""
        if not isinstance(payload, dict) or not payload.get("Event"):
            # A "Send WebSocket Event" instruction puts a bare string in
            # Response, and {DEVICE}-INFO-UPDATED is dead code upstream.
            return
        if "Time" not in payload and "ImageStatistics" not in payload:
            # The socket carries no clock of its own, and every NinaEvent.time
            # must be offset-aware for the fold to sort. Arrival time is within
            # a network hop of the truth, and replay from /event-history
            # corrects it with the rig's own timestamp.
            payload = {**payload, "Time": datetime.now(UTC).isoformat()}
        offset = self._rig_offset() if self._rig_offset is not None else None
        try:
            event = map_event(payload, self._generation(), rig_offset=offset)
        except (KeyError, TypeError, ValueError) as exc:
            _LOGGER.debug("Skipping unmappable event %s: %s", payload, exc)
            return
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:
                _LOGGER.exception("A N.I.N.A. event subscriber raised")

    # ── connection ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background receive loop."""
        self._running = True
        self._task = asyncio.create_task(self._run(), name="nina_event_stream")

    async def stop(self) -> None:
        """Stop the receive loop. Safe on a stream that never started: unload
        runs its callbacks even when setup failed before `start`.
        """
        self._running = False
        self._set_connected(False)
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def _set_connected(self, connected: bool) -> None:
        """Latch the flag and announce transitions only."""
        if self.connected == connected:
            return
        self.connected = connected
        if self._on_connection is None:
            return
        try:
            self._on_connection(connected)
        except Exception:
            _LOGGER.exception("A N.I.N.A. connection listener raised")

    async def _run(self) -> None:
        delay = _RECONNECT_DELAY
        while self._running:
            try:
                _LOGGER.debug("N.I.N.A. event socket: connecting to %s", self._url)
                async with self._session.ws_connect(
                    self._url,
                    heartbeat=30,
                    # An attrs class declared with `attr.ib(type=...)`, which
                    # pyright does not read as keyword parameters.
                    timeout=aiohttp.ClientWSTimeout(ws_receive=60),  # pyright: ignore[reportCallIssue]
                ) as ws:
                    self._ws = ws
                    delay = _RECONNECT_DELAY  # reset backoff on a live connection
                    _LOGGER.info("N.I.N.A. event socket: connected to %s", self._url)
                    self._set_connected(True)
                    await self._listen(ws)
            except aiohttp.ClientConnectorError:
                _LOGGER.warning(
                    "N.I.N.A. event socket: connection refused – retrying in %ds", delay
                )
            except Exception as exc:
                # With the traceback: this catch is what keeps the socket
                # reconnecting, so without it an unanticipated failure loops
                # silently every 5 s with nothing to diagnose it by.
                _LOGGER.warning(
                    "N.I.N.A. event socket: unexpected error: %s", exc, exc_info=True
                )
            finally:
                self._ws = None

            self._set_connected(False)
            if not self._running:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)

    async def _listen(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                self._receive(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                _LOGGER.debug("N.I.N.A. event socket: closed/error – reconnecting")
                break

    def _receive(self, raw: str) -> None:
        """Unwrap one socket frame — the same envelope the HTTP paths use."""
        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.debug("N.I.N.A. event socket: non-JSON message: %s", raw[:200])
            return
        if not isinstance(envelope, dict) or not envelope.get("Success"):
            return
        self._dispatch(envelope.get("Response"))

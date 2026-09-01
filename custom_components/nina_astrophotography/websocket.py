"""WebSocket client for N.I.N.A. Advanced API v2 real-time push events."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable

import aiohttp

from .const import DEFAULT_API_VERSION, WS_BASE

_LOGGER = logging.getLogger(__name__)

# Event names from the AsyncAPI spec at .../v2/doc/websocket. The dispatcher
# forwards every event it receives, so these sets are documentation of the
# known surface rather than a filter.

# Events that carry no payload beyond the event name
SIMPLE_EVENTS = {
    "API-CAPTURE-FINISHED",
    "AUTOFOCUS-FINISHED",
    "AUTOFOCUS-STARTING",
    "CAMERA-CONNECTED",
    "CAMERA-DISCONNECTED",
    "CAMERA-DOWNLOAD-TIMEOUT",
    "DOME-CONNECTED",
    "DOME-DISCONNECTED",
    "DOME-SHUTTER-CLOSED",
    "DOME-SHUTTER-OPENED",
    "DOME-HOMED",
    "DOME-PARKED",
    "DOME-STOPPED",
    "DOME-SLEWED",
    "DOME-SYNCED",
    "FILTERWHEEL-CONNECTED",
    "FILTERWHEEL-DISCONNECTED",
    "FLAT-CONNECTED",
    "FLAT-DISCONNECTED",
    "FLAT-LIGHT-TOGGLED",
    "FLAT-COVER-OPENED",
    "FLAT-COVER-CLOSED",
    "FOCUSER-CONNECTED",
    "FOCUSER-DISCONNECTED",
    "FOCUSER-USER-FOCUSED",
    "GUIDER-CONNECTED",
    "GUIDER-DISCONNECTED",
    "GUIDER-START",
    "GUIDER-STOP",
    "GUIDER-DITHER",
    "IMAGE-PREPARED",
    "MOUNT-CONNECTED",
    "MOUNT-DISCONNECTED",
    "MOUNT-BEFORE-FLIP",
    "MOUNT-AFTER-FLIP",
    "MOUNT-HOMED",
    "MOUNT-PARKED",
    "MOUNT-UNPARKED",
    "MOUNT-CENTER",
    "PROFILE-ADDED",
    "PROFILE-CHANGED",
    "PROFILE-REMOVED",
    "ROTATOR-CONNECTED",
    "ROTATOR-DISCONNECTED",
    "ROTATOR-SYNCED",
    "SAFETY-CONNECTED",
    "SAFETY-DISCONNECTED",
    "SEQUENCE-STARTING",
    "SEQUENCE-FINISHED",
    "SWITCH-CONNECTED",
    "SWITCH-DISCONNECTED",
    "WEATHER-CONNECTED",
    "WEATHER-DISCONNECTED",
    "ERROR-AF",
    "ERROR-PLATESOLVE",
}

# Events that carry rich payloads
PAYLOAD_EVENTS = {
    "IMAGE-SAVE",                # Response.ImageStatistics
    "AUTOFOCUS-POINT-ADDED",     # Response.ImageStatistics {Position, HFR}
    "FILTERWHEEL-CHANGED",       # Response.Previous / Response.New
    "FLAT-BRIGHTNESS-CHANGED",   # Response.Previous / Response.New
    "SAFETY-CHANGED",            # Response.IsSafe
    "STACK-UPDATED",             # Livestack plugin >= 1.0.0.9
    "STACK-STATUS",              # Livestack plugin >= 1.0.1.7
    "SEQUENCE-ENTITY-FAILED",    # Response.Entity / Response.Error
    "ROTATOR-MOVED",             # Response.From / Response.To
    "ROTATOR-MOVED-MECHANICAL",  # Response.From / Response.To
    "TS-WAITSTART",              # Target Scheduler: Response.WaitStartTime
    "TS-NEWTARGETSTART",         # Target Scheduler: target/project/coordinates
    "TS-TARGETSTART",            # Target Scheduler: target/project/coordinates
}

# How long (seconds) to wait before reconnecting after a disconnect
_RECONNECT_DELAY = 5
_MAX_RECONNECT_DELAY = 60


class NinaWebSocketClient:
    """Maintains a persistent WebSocket connection to N.I.N.A.

    Consumers register callbacks keyed on event names (or "*" for all).
    The client reconnects automatically with exponential backoff.
    """

    def __init__(
        self,
        host: str,
        port: int,
        session: aiohttp.ClientSession,
        hass_event_bus_fire: Callable[[str, dict], None],
        api_version: str = DEFAULT_API_VERSION,
    ) -> None:
        self._url = WS_BASE.format(host=host, port=port, version=api_version)
        self._session = session
        self._fire = hass_event_bus_fire
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._running = False
        self._task: asyncio.Task | None = None
        # event_name → list of callbacks
        self._listeners: dict[str, list[Callable[[dict], None]]] = {}

    # ─── Public API ──────────────────────────────────────────────────────────

    def add_listener(self, event: str, callback: Callable[[dict], None]) -> Callable:
        """Register *callback* for *event* (use '*' for all events).
        Returns an unsubscribe callable."""
        self._listeners.setdefault(event, []).append(callback)

        def _remove() -> None:
            self._listeners.get(event, []).remove(callback)

        return _remove

    async def start(self) -> None:
        """Start the background WebSocket task."""
        self._running = True
        self._task = asyncio.create_task(self._run(), name="nina_websocket")

    async def stop(self) -> None:
        """Gracefully stop the WebSocket task."""
        self._running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ─── Internal loop ───────────────────────────────────────────────────────

    async def _run(self) -> None:
        delay = _RECONNECT_DELAY
        while self._running:
            try:
                _LOGGER.debug("N.I.N.A. WebSocket: connecting to %s", self._url)
                async with self._session.ws_connect(
                    self._url,
                    heartbeat=30,
                    timeout=aiohttp.ClientWSTimeout(ws_receive=60),
                ) as ws:
                    self._ws = ws
                    delay = _RECONNECT_DELAY  # reset backoff on successful connect
                    _LOGGER.info("N.I.N.A. WebSocket: connected to %s", self._url)
                    self._fire_ha_event("nina_websocket_connected", {})
                    await self._listen(ws)
            except aiohttp.ClientConnectorError:
                _LOGGER.warning(
                    "N.I.N.A. WebSocket: connection refused – retrying in %ds", delay
                )
            except asyncio.CancelledError:
                return
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning("N.I.N.A. WebSocket: unexpected error: %s", exc)

            if not self._running:
                return

            self._fire_ha_event("nina_websocket_disconnected", {})
            await asyncio.sleep(delay)
            delay = min(delay * 2, _MAX_RECONNECT_DELAY)

    async def _listen(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._dispatch(msg.data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                _LOGGER.debug("N.I.N.A. WebSocket: closed/error – reconnecting")
                break

    async def _dispatch(self, raw: str) -> None:
        """Parse a raw JSON message and dispatch to listeners + HA event bus."""
        try:
            data: dict = json.loads(raw)
        except json.JSONDecodeError:
            _LOGGER.debug("N.I.N.A. WebSocket: non-JSON message: %s", raw[:200])
            return

        if not data.get("Success"):
            return

        response: dict = data.get("Response", {})
        event_name: str = response.get("Event", "")
        if not event_name:
            return

        _LOGGER.debug("N.I.N.A. WebSocket event: %s", event_name)

        # Fire on the HA event bus so automations can trigger on any NINA event
        self._fire_ha_event(
            f"nina_{event_name.lower().replace('-', '_')}",
            {"event": event_name, "response": response},
        )

        # Also fire a generic nina_event for catch-all triggers
        self._fire_ha_event(
            "nina_event",
            {"event": event_name, "response": response},
        )

        # Notify registered Python callbacks
        for cb in list(self._listeners.get(event_name, [])):
            try:
                cb(response)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("N.I.N.A. WebSocket listener error")
        for cb in list(self._listeners.get("*", [])):
            try:
                cb(response)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("N.I.N.A. WebSocket wildcard listener error")

    def _fire_ha_event(self, event_type: str, data: dict) -> None:
        try:
            self._fire(event_type, data)
        except Exception:  # noqa: BLE001
            pass

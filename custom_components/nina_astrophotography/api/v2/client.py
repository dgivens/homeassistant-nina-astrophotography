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
    rig_utc_offset,
)

_LOGGER = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Pre-handler statuses meaning the path itself is not served.
_NOT_SERVED = (404, 405, 501)

# "No data yet" — ordinary states, normalized to None/[] rather than raised.
# Matched as substrings of the envelope's Error, but kept specific: a bare
# "is not initialized" would also swallow a device refusal on a command path.
_NO_DATA_MESSAGES = ("index out of range", "sequence is not initialized")


def _boolean(value: bool) -> str:
    """Query booleans go on the wire as lowercase strings: aiohttp refuses a
    bare bool as a parameter value, and `str(True)` binds to nothing."""
    return "true" if value else "false"


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

    @property
    def rig_offset(self) -> timedelta | None:
        """The rig's UTC offset as last read from the mount's clock; `None`
        until the first `/equipment/info` with a connected mount. Frame dates
        carry this offset, so anything placing a local-time boundary — the
        session's noon rollover — must use it rather than Home Assistant's zone.
        """
        return self._rig_offset

    # ── transport ────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Return the unwrapped Response, or raise. `None` means no data yet."""
        url = self.base_url + path
        try:
            async with self._session.get(url, params=params, timeout=_TIMEOUT) as resp:
                status = resp.status
                body = await resp.text()
        except TimeoutError as exc:
            raise NinaConnectionError(f"Timeout reaching N.I.N.A. at {url}") from exc
        except aiohttp.ClientError as exc:
            # ClientError, not ClientConnectorError: a crashed N.I.N.A. raises
            # ServerDisconnectedError and a truncated reply ClientPayloadError.
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

        if status != 200:
            raise self._pre_handler_error(path, status, body)
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
        if not body.strip():
            # Sequence serialization failure: empty body, no envelope.
            raise NinaUnavailableError(f"{path} returned an empty body")
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
            # A 5xx is a handler exception whatever its text says; only then
            # may the message downgrade a refusal to "no data yet".
            if isinstance(status, int) and status >= 500:
                raise NinaUnavailableError(f"{path}: {error} (StatusCode {status})")
            if any(message in error.lower() for message in _NO_DATA_MESSAGES):
                return None
            raise NinaCommandError(
                f"{path}: {error or 'unknown error'} (StatusCode {status})",
                status_code=status if isinstance(status, int) else None,
                api_error=error,
            )
        return payload.get("Response")

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_versions(self) -> VersionInfo:
        """`/version/nina` is diagnostic: a build that does not serve it is
        still usable, so only that route's absence is tolerated."""
        api = await self._get("/version")
        try:
            nina = await self._get("/version/nina")
        except NinaEndpointError:
            nina = None
        return VersionInfo(
            api_version=str(api) if api is not None else None,
            nina_version=str(nina) if nina is not None else None,
        )

    async def get_application_start(self) -> str | None:
        value = await self._get("/application-start")
        return str(value) if value is not None else None

    async def get_equipment(self) -> EquipmentSnapshot:
        response = await self._get("/equipment/info")
        wire = response if isinstance(response, dict) else {}
        offset = rig_utc_offset(wire)
        if offset is not None:  # not `or`: UTC+0 is a real offset
            self._rig_offset = offset
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
        if isinstance(response, dict):
            response = [response]
        if not isinstance(response, list):
            return []
        frames: list[Frame] = []
        for item in response:
            try:
                frames.append(map_frame(item, generation))
            except (KeyError, TypeError, ValueError) as exc:
                # No (Date, Filename) identity means it cannot enter the fold.
                _LOGGER.debug("Skipping unmappable frame %s: %s", item, exc)
        return frames

    async def get_image_history_count(self) -> int:
        return int(await self._get("/image-history", {"count": "true"}) or 0)

    async def get_events(self, generation: str | None = None) -> list[NinaEvent]:
        """The stored events, mapped. A malformed one is skipped, not raised.

        This feeds the setup replay, which runs inside
        `async_config_entry_first_refresh`, so anything escaping here fails the
        entry over one bad stored event — and the same widths guard `get_frames`
        and the socket's own dispatch.
        """
        raw = await self._raw_event_history()
        if not isinstance(raw, list):
            return []
        events: list[NinaEvent] = []
        for item in raw:
            try:
                events.append(map_event(item, generation, rig_offset=self._rig_offset))
            except (AttributeError, KeyError, TypeError, ValueError) as exc:
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
        # No `or {}`: the Response is a bare string, and "" is falsy.
        return map_livestack_status(await self._get("/livestack/status") or "")

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
                # With stream=true a real image is served as image/*; a refusal
                # arrives as 200 carrying the JSON envelope.
                if resp.status == 200 and (resp.content_type or "").startswith("image/"):
                    return await resp.read()
                body = await resp.text()
                if resp.status != 200:
                    raise self._pre_handler_error(path, resp.status, body)
                self._unwrap(path, self._decode(path, body))
                raise NinaUnavailableError(f"{path} returned no image")
        except TimeoutError as exc:
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

    # camera

    async def cool_camera(self, temperature: float, *, minutes: float = -1) -> None:
        """`minutes` is the cooling ramp, not a timeout; -1 asks for the
        profile's own duration."""
        await self._get("/equipment/camera/cool",
                        {"temperature": temperature, "minutes": minutes})

    async def warm_camera(self, *, minutes: float = -1) -> None:
        await self._get("/equipment/camera/warm", {"minutes": minutes})

    async def set_target_temperature(self, temperature: float, *,
                                     minutes: float | None = None) -> None:
        """There is no setpoint endpoint: changing the target is a cool-down to
        the new value. Omitting `minutes` leaves the ramp to the API."""
        params: dict[str, Any] = {"temperature": temperature}
        if minutes is not None:
            params["minutes"] = minutes
        await self._get("/equipment/camera/cool", params)

    async def set_cooler(self, on: bool, temperature: float, *,
                         minutes: float = -1) -> None:
        """The API has no cooler toggle: cooling starts with /cool and stops
        with /warm, so the two branches are different endpoints.

        `temperature` is the setpoint /cool requires — there is no "resume at
        the existing target" form — and is unused when switching off.
        """
        if on:
            await self.cool_camera(temperature, minutes=minutes)
        else:
            await self.warm_camera(minutes=minutes)

    async def set_dew_heater(self, on: bool) -> None:
        """The parameter is `power`, not `on` or `enabled`."""
        await self._get("/equipment/camera/dew-heater", {"power": _boolean(on)})

    async def set_usb_limit(self, limit: int) -> None:
        """An integer bounded by USBLimitMin/USBLimitMax, per camera. The spec
        types it as a string with the example `2x2`, which is set-binning's."""
        await self._get("/equipment/camera/usb-limit", {"limit": limit})

    async def capture_image(self, duration: float, *, gain: int | None = None,
                            save: bool = False) -> None:
        """The parameter is `duration`. 1.4.5 sent `time`, so exposure time was
        silently ignored — the API defaulted it and answered Success: true.

        `binning` and `filter_index` are deliberately absent: they bind nothing,
        and a parameter that looks like it works is worse than no parameter.
        """
        params: dict[str, Any] = {"duration": duration, "save": _boolean(save)}
        if gain is not None:
            params["gain"] = gain
        await self._get("/equipment/camera/capture", params)

    async def abort_capture(self) -> None:
        await self._get("/equipment/camera/abort-exposure")

    # mount

    async def slew_mount(self, ra_degrees: float, dec_degrees: float) -> None:
        """Slew to J2000 coordinates, in DEGREES.

        All three branches construct
        `new Coordinates(Angle.ByDegree(ra), Angle.ByDegree(dec), Epoch.J2000)`
        and N.I.N.A. transforms to the mount's own EquatorialSystem internally.
        Never pre-transform.

        The round trip is asymmetric: MountInfo.Coordinates / RightAscension are
        reported in the MOUNT's epoch (JNOW here) and in HOURS. Feeding a
        reported RA back into slew is wrong twice — a 15x unit error and a
        precession error — and 22.07 is a valid RA read either way, so nothing
        catches it.
        """
        await self._get("/equipment/mount/slew", {"ra": ra_degrees, "dec": dec_degrees})

    async def park_mount(self) -> None:
        await self._get("/equipment/mount/park")

    async def unpark_mount(self) -> None:
        await self._get("/equipment/mount/unpark")

    async def find_home(self) -> None:
        await self._get("/equipment/mount/home")

    async def set_tracking_mode(self, mode: int) -> None:
        """`mode` is the API's enum value — 0 Sidereal, 1 Lunar, 2 Solar,
        3 King, 4 Stopped — and **not** the position in `TrackingModes`, which
        omits modes a mount does not offer."""
        await self._get("/equipment/mount/tracking", {"mode": mode})

    # focuser

    async def move_focuser(self, position: int) -> None:
        await self._get("/equipment/focuser/move", {"position": position})

    async def auto_focus(self) -> None:
        await self._get("/equipment/focuser/auto-focus")

    # filter wheel

    async def change_filter(self, index: int) -> None:
        """The parameter is `filterId`, not `filter` or `index`."""
        await self._get("/equipment/filterwheel/change-filter", {"filterId": index})

    # guider

    async def start_guiding(self, *, force_calibration: bool = False) -> None:
        await self._get("/equipment/guider/start",
                        {"calibrate": _boolean(force_calibration)})

    async def stop_guiding(self) -> None:
        await self._get("/equipment/guider/stop")

    async def clear_guider_calibration(self) -> None:
        await self._get("/equipment/guider/clear-calibration")

    # rotator

    async def move_rotator(self, position: float) -> None:
        """`position` is the SKY angle in degrees; the mechanical angle is a
        different endpoint, /equipment/rotator/move-mechanical."""
        await self._get("/equipment/rotator/move", {"position": position})

    async def move_rotator_mechanical(self, position: float) -> None:
        """`position` is the MECHANICAL angle in degrees, which is what the
        rotator reports as `MechanicalPosition`; /move takes the sky angle.

        Parameter name taken from the spec and not confirmed against hardware.
        """
        await self._get("/equipment/rotator/move-mechanical", {"position": position})

    async def set_rotator_reverse(self, on: bool) -> None:
        """The parameter is `reverseDirection`."""
        await self._get("/equipment/rotator/reverse", {"reverseDirection": _boolean(on)})

    # dome

    async def slew_dome(self, azimuth: float) -> None:
        """Degrees. The spec also declares `waitToFinish`; it is omitted, since
        a command that blocks until the dome arrives would hold the poll.

        Parameter name taken from the spec and not confirmed against hardware —
        there is no dome to confirm it against (§5.3.1).
        """
        await self._get("/equipment/dome/slew", {"azimuth": azimuth})

    async def open_dome(self) -> None:
        await self._get("/equipment/dome/open")

    async def close_dome(self) -> None:
        await self._get("/equipment/dome/close")

    async def park_dome(self) -> None:
        await self._get("/equipment/dome/park")

    async def home_dome(self) -> None:
        await self._get("/equipment/dome/home")

    async def set_dome_follow(self, on: bool) -> None:
        """The parameter is `enabled`."""
        await self._get("/equipment/dome/set-follow", {"enabled": _boolean(on)})

    # flat device

    async def set_flat_light(self, on: bool) -> None:
        await self._get("/equipment/flatdevice/set-light", {"on": _boolean(on)})

    async def set_flat_brightness(self, brightness: int) -> None:
        await self._get("/equipment/flatdevice/set-brightness",
                        {"brightness": brightness})

    async def open_flat_cover(self) -> None:
        """The parameter is `closed` and it is inverted: opening sends false."""
        await self._get("/equipment/flatdevice/set-cover", {"closed": "false"})

    async def close_flat_cover(self) -> None:
        await self._get("/equipment/flatdevice/set-cover", {"closed": "true"})

    # switch

    async def set_switch_value(self, index: int, value: float) -> None:
        await self._get("/equipment/switch/set", {"index": index, "value": value})

    # sequence

    async def start_sequence(self) -> None:
        await self._get("/sequence/start")

    async def stop_sequence(self) -> None:
        await self._get("/sequence/stop")

    async def load_sequence(self, sequence_name: str) -> None:
        """The parameter is `sequenceName`, and it is a NAME, not a path.
        1.4.5 sent `path`, so the sequence never loaded."""
        await self._get("/sequence/load", {"sequenceName": sequence_name})

    # livestack

    async def start_livestack(self) -> None:
        await self._get("/livestack/start")

    async def stop_livestack(self) -> None:
        await self._get("/livestack/stop")

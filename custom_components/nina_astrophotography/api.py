"""N.I.N.A. Advanced API client — corrected for v2.2.15+ endpoint paths."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_BASE, TrackingMode

_LOGGER = logging.getLogger(__name__)


class NinaApiError(Exception):
    """Raised when N.I.N.A. answers, but not with what was asked for."""


class NinaEndpointError(NinaApiError):
    """Raised when this NINA build does not serve the requested path.

    Distinct from a refused command: a refusal means the equipment said no and
    is worth retrying, a wrong path never will be.
    """


class NinaConnectionError(Exception):
    """Raised when a connection to N.I.N.A. cannot be established."""


# Statuses that mean the path itself is not served. Everything else, 5xx
# included, is treated as transient: a handler that threw or a server still
# starting up will answer normally later, and failing the config entry for
# one of those is far worse than retrying a path that never returns.
_PATH_NOT_SERVED = (404, 405, 501)


def _http_error(method: str, path: str, status: int, body: str = "") -> NinaApiError:
    """Build the error for a non-200 reply.

    The body is an EmbedIO HTML error page, so it is collapsed and truncated
    rather than dumped into the log.
    """
    summary = " ".join(body.split())[:120]
    detail = f": {summary}" if summary else ""
    message = f"{method} {path} -> {status}{detail}"
    if status in _PATH_NOT_SERVED:
        return NinaEndpointError(message)
    return NinaApiError(message)


def _raise_for_envelope(path: str, payload) -> None:
    """Raise if the response envelope reports a failure.

    The API answers HTTP 200 for everything, including refused commands, and
    carries the real outcome in the body.

    `Success` alone is not enough to key on: some handlers assign it straight
    from the driver's return value, so it can be false on a call that worked —
    a successful tracking change answers `Success: false` with an empty Error
    and a 200 code. Genuine failures are built by CreateErrorTable, which
    always sets both a message and a 4xx/5xx code.
    """
    if not isinstance(payload, dict) or payload.get("Success") is not False:
        return
    error = payload.get("Error")
    status = payload.get("StatusCode")
    if not error and status in (None, 200):
        return
    detail = f" (StatusCode {status})" if status is not None else ""
    raise NinaApiError(f"{path}: {error or 'unknown error'}{detail}")


class NinaApiClient:
    """Async HTTP client wrapping the N.I.N.A. Advanced API v2."""

    def __init__(self, host, port, api_version, session):
        self._base = API_BASE.format(host=host, port=port, version=api_version)
        self._session = session

    async def _get(self, path, params=None):
        url = self._base + path
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status != 200:
                    raise _http_error("GET", path, resp.status, await resp.text())
                payload = await resp.json(content_type=None)
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError(f"Timeout reaching N.I.N.A. at {url}") from exc
        except aiohttp.ClientError as exc:
            # ClientError, not ClientConnectorError: a crashed NINA raises
            # ServerDisconnectedError, a truncated reply ClientPayloadError.
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

        _raise_for_envelope(path, payload)
        return payload

    async def _post(self, path, data=None, params=None):
        url = self._base + path
        try:
            async with self._session.post(
                url, json=data, params=params, timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                if resp.status in (200, 204):
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception:
                        return {}
                    _raise_for_envelope(path, payload)
                    return payload
                raise _http_error("POST", path, resp.status, await resp.text())
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError(f"Timeout reaching N.I.N.A. at {url}") from exc
        except aiohttp.ClientError as exc:
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

    # Application
    async def get_version(self):
        return await self._get("/version")

    # Camera — v2.2.x uses /equipment/camera/info
    async def get_camera(self):
        return await self._get("/equipment/camera/info")

    async def connect_camera(self):
        return await self._get("/equipment/camera/connect")

    async def disconnect_camera(self):
        return await self._get("/equipment/camera/disconnect")

    async def cool_camera(self, temperature, minutes=10):
        return await self._get("/equipment/camera/cool",
                               params={"temperature": temperature, "minutes": minutes})

    async def warm_camera(self, minutes=10):
        return await self._get("/equipment/camera/warm", params={"minutes": minutes})

    async def capture_image(self, exposure, gain=None, filter_index=None, binning=1, save=False):
        params = {"time": exposure, "binning": binning, "save": str(save).lower()}
        if gain is not None:
            params["gain"] = gain
        if filter_index is not None:
            params["filter_index"] = filter_index
        return await self._get("/equipment/camera/capture", params=params)

    async def abort_capture(self):
        return await self._get("/equipment/camera/abort-exposure")

    # Mount / Telescope
    async def get_mount(self):
        return await self._get("/equipment/mount/info")

    async def connect_mount(self):
        return await self._get("/equipment/mount/connect")

    async def disconnect_mount(self):
        return await self._get("/equipment/mount/disconnect")

    async def slew_mount(self, ra, dec):
        return await self._get("/equipment/mount/slew-to-coordinates-j2000",
                               params={"ra": ra, "dec": dec})

    async def park_mount(self):
        return await self._get("/equipment/mount/park")

    async def unpark_mount(self):
        return await self._get("/equipment/mount/unpark")

    async def set_tracking_mode(self, mode: TrackingMode):
        """Set the tracking rate."""
        return await self._get(
            "/equipment/mount/tracking", params={"mode": int(mode)}
        )

    async def set_tracking(self, enabled):
        """Start sidereal tracking, or stop it."""
        return await self.set_tracking_mode(
            TrackingMode.SIDEREAL if enabled else TrackingMode.STOPPED
        )

    async def find_home(self):
        return await self._get("/equipment/mount/find-home")

    # Focuser
    async def get_focuser(self):
        return await self._get("/equipment/focuser/info")

    async def connect_focuser(self):
        return await self._get("/equipment/focuser/connect")

    async def disconnect_focuser(self):
        return await self._get("/equipment/focuser/disconnect")

    async def move_focuser(self, position):
        return await self._get("/equipment/focuser/move", params={"position": position})

    async def auto_focus(self):
        return await self._get("/equipment/focuser/auto-focus")

    # Filter Wheel
    async def get_filterwheel(self):
        return await self._get("/equipment/filterwheel/info")

    async def connect_filterwheel(self):
        return await self._get("/equipment/filterwheel/connect")

    async def disconnect_filterwheel(self):
        return await self._get("/equipment/filterwheel/disconnect")

    async def change_filter(self, index):
        return await self._get("/equipment/filterwheel/change-filter",
                               params={"filterId": index})

    # Guider
    async def get_guider(self):
        return await self._get("/equipment/guider/info")

    async def connect_guider(self):
        return await self._get("/equipment/guider/connect")

    async def disconnect_guider(self):
        return await self._get("/equipment/guider/disconnect")

    async def start_guiding(self, force_calibration=False):
        return await self._get("/equipment/guider/start",
                               params={"calibrate": str(force_calibration).lower()})

    async def stop_guiding(self):
        return await self._get("/equipment/guider/stop")

    async def dither(self):
        return await self._get("/equipment/guider/dither")

    # Rotator
    async def get_rotator(self):
        return await self._get("/equipment/rotator/info")

    async def connect_rotator(self):
        return await self._get("/equipment/rotator/connect")

    async def disconnect_rotator(self):
        return await self._get("/equipment/rotator/disconnect")

    async def move_rotator(self, position):
        return await self._get("/equipment/rotator/move", params={"position": position})

    # Dome
    async def get_dome(self):
        return await self._get("/equipment/dome/info")

    async def connect_dome(self):
        return await self._get("/equipment/dome/connect")

    async def disconnect_dome(self):
        return await self._get("/equipment/dome/disconnect")

    async def open_dome(self):
        return await self._get("/equipment/dome/open")

    async def close_dome(self):
        return await self._get("/equipment/dome/close")

    async def park_dome(self):
        return await self._get("/equipment/dome/park")

    async def home_dome(self):
        return await self._get("/equipment/dome/home")

    # Flat Device
    async def get_flatdevice(self):
        return await self._get("/equipment/flatdevice/info")

    async def connect_flatdevice(self):
        return await self._get("/equipment/flatdevice/connect")

    async def toggle_flat_light(self, on):
        return await self._get("/equipment/flatdevice/toggle-light",
                               params={"on": str(on).lower()})

    async def set_flat_brightness(self, brightness):
        return await self._get("/equipment/flatdevice/set-brightness",
                               params={"brightness": brightness})

    # Sequence
    async def get_sequence(self):
        return await self._get("/sequence")

    async def start_sequence(self):
        return await self._get("/sequence/start")

    async def stop_sequence(self):
        return await self._get("/sequence/stop")

    async def load_sequence(self, path):
        return await self._get("/sequence/load", params={"path": path})

    # Images
    async def get_image_history(self):
        """Every frame of the current session, oldest first."""
        return await self._get("/image-history", params={"all": "true"})

    async def get_latest_image(self):
        return await self._get("/image/latest")



    # Weather station
    async def get_weather(self):
        return await self._get("/equipment/weather/info")

    async def connect_weather(self):
        return await self._get("/equipment/weather/connect")

    async def disconnect_weather(self):
        return await self._get("/equipment/weather/disconnect")

    # Safety monitor
    async def get_safetymonitor(self):
        return await self._get("/equipment/safetymonitor/info")

    async def connect_safetymonitor(self):
        return await self._get("/equipment/safetymonitor/connect")

    async def disconnect_safetymonitor(self):
        return await self._get("/equipment/safetymonitor/disconnect")

    # Image streaming — returns raw JPEG bytes (use stream=True)
    async def get_image_stream_url(self, index: int = 0, quality: int = 85, stretch: bool = True) -> str:
        """Return URL for fetching a JPEG image directly.
        
        The Advanced API streams the image when stream=true.
        Use in the Lovelace card img src attribute.
        """
        params = f"stream=true&quality={quality}"
        if stretch:
            params += "&useAutoStretch=true"
        return f"{self._base}/image/{index}?{params}"

    async def get_image_bytes(self, index: int = 0, quality: int = 85, stretch: bool = True) -> bytes:
        """Fetch a JPEG image and return raw bytes. Used for HA image entities."""
        path = f"/image/{index}"
        url = self._base + path
        params = {"stream": "true", "quality": quality}
        if stretch:
            params["useAutoStretch"] = "true"
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                if resp.status != 200:
                    raise _http_error("GET", path, resp.status)
                # A refusal arrives as 200 carrying the JSON envelope. With
                # stream=true a real image is served as image/jpeg or
                # image/png, so the content type is what separates them.
                if (resp.content_type or "").startswith("image/"):
                    return await resp.read()
                _raise_for_envelope(path, await resp.json(content_type=None))
                raise NinaApiError(
                    f"GET {path} returned {resp.content_type}, not an image"
                )
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError("Timeout fetching image") from exc
        except aiohttp.ClientError as exc:
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

    # Poll all equipment concurrently
    async def poll_all(self):
        """Fetch all equipment info concurrently. Returns {subsystem: data}."""
        tasks = {
            "camera": self.get_camera(),
            "mount": self.get_mount(),
            "focuser": self.get_focuser(),
            "filterwheel": self.get_filterwheel(),
            "guider": self.get_guider(),
            "rotator": self.get_rotator(),
            "dome": self.get_dome(),
            "flatdevice": self.get_flatdevice(),
            "sequence": self.get_sequence(),
            "image_history": self.get_image_history(),
            "weather": self.get_weather(),
            "safetymonitor": self.get_safetymonitor(),
        }
        results = {}
        failures = {}
        responses = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for key, response in zip(tasks.keys(), responses):
            if isinstance(response, Exception):
                _LOGGER.debug("Poll error for %s: %s", key, response)
                failures[key] = response
                results[key] = {}
            else:
                results[key] = response

        # A rig with no dome must not fail the whole poll. But if nothing
        # answered, NINA is gone and the coordinator has to know, or every
        # entity carries on publishing defaults.
        if len(failures) == len(tasks):
            connection_errors = [
                exc for exc in failures.values()
                if isinstance(exc, NinaConnectionError)
            ]
            if connection_errors:
                raise NinaConnectionError(
                    f"No N.I.N.A. subsystem responded: {connection_errors[0]}"
                )
            if all(isinstance(e, NinaEndpointError) for e in failures.values()):
                raise NinaEndpointError(
                    "N.I.N.A. served none of the expected endpoints, so this "
                    "client is talking to an API it does not understand: "
                    f"{next(iter(failures.values()))}"
                )
            raise NinaApiError(
                "Every N.I.N.A. subsystem returned an error: "
                f"{next(iter(failures.values()))}"
            )

        return results

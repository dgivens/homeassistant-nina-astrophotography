"""N.I.N.A. Advanced API client.

Endpoint paths and query parameters follow the Advanced API v2 OpenAPI spec
(v2.2.15) published at
https://christian-photo.github.io/github-page/projects/ninaAPI/v2/doc/api

Every endpoint in this API is a GET, including the ones that mutate state.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_BASE, TRACKING_MODE_TO_INDEX

_LOGGER = logging.getLogger(__name__)


class NinaApiError(Exception):
    """Raised when the N.I.N.A. API returns an error."""


class NinaConnectionError(Exception):
    """Raised when a connection to N.I.N.A. cannot be established."""


def _b(value: bool) -> str:
    """Render a Python bool the way the Advanced API expects it in a query."""
    return "true" if value else "false"


class NinaApiClient:
    """Async HTTP client wrapping the N.I.N.A. Advanced API v2."""

    def __init__(self, host, port, api_version, session):
        self._base = API_BASE.format(host=host, port=port, version=api_version)
        self._session = session

    @property
    def base_url(self) -> str:
        """Base URL of the API, e.g. http://host:1888/v2/api."""
        return self._base

    async def _get(self, path, params=None):
        url = self._base + path
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                text = await resp.text()
                raise NinaApiError(f"GET {path} -> {resp.status}: {text}")
        except aiohttp.ClientConnectorError as exc:
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}") from exc
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError(f"Timeout reaching N.I.N.A. at {url}") from exc

    async def _get_bytes(self, path, params=None, timeout=30) -> bytes:
        """Fetch a binary payload (streamed image endpoints)."""
        url = self._base + path
        try:
            async with self._session.get(
                url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
                raise NinaApiError(f"GET {path} -> {resp.status}")
        except aiohttp.ClientConnectorError as exc:
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}") from exc
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError(f"Timeout fetching {path}") from exc

    # ── Application ──────────────────────────────────────────────────────────

    async def get_version(self):
        """Advanced API plugin version."""
        return await self._get("/version")

    async def get_nina_version(self, friendly: bool = True):
        """N.I.N.A. application version."""
        return await self._get("/version/nina", params={"friendly": _b(friendly)})

    async def get_application_start(self):
        """Timestamp N.I.N.A. was started."""
        return await self._get("/application-start")

    async def get_plugins(self):
        return await self._get("/application/plugins")

    async def get_tab(self):
        return await self._get("/application/get-tab")

    async def switch_tab(self, tab: str):
        return await self._get("/application/switch-tab", params={"tab": tab})

    async def get_screenshot_bytes(self, quality: int = 85, resize: bool = False,
                                   size: str | None = None) -> bytes:
        params: dict[str, Any] = {"stream": _b(True), "quality": quality}
        if resize:
            params["resize"] = _b(True)
            if size:
                params["size"] = size
        return await self._get_bytes("/application/screenshot", params=params)

    async def get_event_history(self):
        return await self._get("/event-history")

    # ── Camera ───────────────────────────────────────────────────────────────

    async def get_camera(self):
        return await self._get("/equipment/camera/info")

    async def connect_camera(self):
        return await self._get("/equipment/camera/connect")

    async def disconnect_camera(self):
        return await self._get("/equipment/camera/disconnect")

    async def cool_camera(self, temperature, minutes=-1, cancel=False):
        """Cool the sensor. ``minutes`` of -1 uses the profile's default duration."""
        return await self._get(
            "/equipment/camera/cool",
            params={
                "temperature": temperature,
                "minutes": minutes,
                "cancel": _b(cancel),
            },
        )

    async def warm_camera(self, minutes=-1, cancel=False):
        return await self._get(
            "/equipment/camera/warm", params={"minutes": minutes, "cancel": _b(cancel)}
        )

    async def capture_image(
        self,
        duration: float | None = None,
        gain: int | None = None,
        save: bool = False,
        solve: bool = False,
        wait_for_result: bool = False,
        image_type: str | None = None,
        target_name: str | None = None,
        omit_image: bool = True,
    ):
        """Start (or run) a capture.

        The API has no ``binning`` or ``filter`` parameter on this endpoint —
        set binning via :meth:`set_binning` and the filter via
        :meth:`change_filter` before capturing.
        """
        params: dict[str, Any] = {
            "save": _b(save),
            "solve": _b(solve),
            "omitImage": _b(omit_image),
        }
        if duration is not None:
            params["duration"] = duration
        if gain is not None:
            params["gain"] = gain
        if wait_for_result:
            params["waitForResult"] = _b(True)
        if image_type is not None:
            params["imageType"] = image_type
        if target_name is not None:
            params["targetName"] = target_name
        return await self._get("/equipment/camera/capture", params=params)

    async def get_capture_statistics(self):
        """Image statistics for the last captured image."""
        return await self._get("/equipment/camera/capture/statistics")

    async def abort_capture(self):
        return await self._get("/equipment/camera/abort-exposure")

    async def set_binning(self, binning: str):
        """Set binning, e.g. ``"2x2"``. Must be a mode the camera reports."""
        return await self._get(
            "/equipment/camera/set-binning", params={"binning": binning}
        )

    async def set_dew_heater(self, on: bool):
        return await self._get("/equipment/camera/dew-heater", params={"power": _b(on)})

    async def set_usb_limit(self, limit: int):
        return await self._get("/equipment/camera/usb-limit", params={"limit": limit})

    async def set_readout_mode(self, mode: int):
        return await self._get("/equipment/camera/set-readout", params={"mode": mode})

    # ── Mount ────────────────────────────────────────────────────────────────

    async def get_mount(self):
        return await self._get("/equipment/mount/info")

    async def connect_mount(self):
        return await self._get("/equipment/mount/connect")

    async def disconnect_mount(self):
        return await self._get("/equipment/mount/disconnect")

    async def slew_mount(
        self,
        ra_degrees: float,
        dec_degrees: float,
        wait_for_result: bool = False,
        center: bool = False,
        rotate: bool = False,
        rotation_angle: float | None = None,
    ):
        """Slew to RA/Dec. Both angles are in **degrees**, not hours."""
        params: dict[str, Any] = {
            "ra": ra_degrees,
            "dec": dec_degrees,
            "waitForResult": _b(wait_for_result),
            "center": _b(center),
            "rotate": _b(rotate),
        }
        if rotation_angle is not None:
            params["rotationAngle"] = rotation_angle
        return await self._get("/equipment/mount/slew", params=params)

    async def stop_slew(self):
        return await self._get("/equipment/mount/slew/stop")

    async def sync_mount(self, ra_degrees: float, dec_degrees: float):
        return await self._get(
            "/equipment/mount/sync", params={"ra": ra_degrees, "dec": dec_degrees}
        )

    async def park_mount(self):
        return await self._get("/equipment/mount/park")

    async def unpark_mount(self):
        return await self._get("/equipment/mount/unpark")

    async def set_mount_park_position(self):
        return await self._get("/equipment/mount/set-park-position")

    async def set_tracking_mode(self, mode: int):
        """Set tracking mode: 0 Sidereal, 1 Lunar, 2 Solar, 3 King, 4 Stopped."""
        return await self._get("/equipment/mount/tracking", params={"mode": mode})

    async def set_tracking(self, enabled: bool):
        """Convenience wrapper: sidereal tracking on, or tracking stopped."""
        return await self.set_tracking_mode(
            TRACKING_MODE_TO_INDEX["Sidereal"] if enabled
            else TRACKING_MODE_TO_INDEX["Stopped"]
        )

    async def find_home(self):
        return await self._get("/equipment/mount/home")

    async def meridian_flip(self):
        """Flip only if a flip is actually needed; never forces one."""
        return await self._get("/equipment/mount/flip")

    # ── Focuser ──────────────────────────────────────────────────────────────

    async def get_focuser(self):
        return await self._get("/equipment/focuser/info")

    async def connect_focuser(self):
        return await self._get("/equipment/focuser/connect")

    async def disconnect_focuser(self):
        return await self._get("/equipment/focuser/disconnect")

    async def move_focuser(self, position: int):
        return await self._get("/equipment/focuser/move", params={"position": position})

    async def stop_focuser(self):
        return await self._get("/equipment/focuser/stop-move")

    async def auto_focus(self, cancel: bool = False):
        return await self._get(
            "/equipment/focuser/auto-focus", params={"cancel": _b(cancel)}
        )

    async def get_last_autofocus(self):
        """Result of the most recent autofocus run."""
        return await self._get("/equipment/focuser/last-af")

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def get_filterwheel(self):
        return await self._get("/equipment/filterwheel/info")

    async def connect_filterwheel(self):
        return await self._get("/equipment/filterwheel/connect")

    async def disconnect_filterwheel(self):
        return await self._get("/equipment/filterwheel/disconnect")

    async def change_filter(self, filter_id: int):
        """Change to the filter with the given ``Id`` (not a list position)."""
        return await self._get(
            "/equipment/filterwheel/change-filter", params={"filterId": filter_id}
        )

    # ── Guider ───────────────────────────────────────────────────────────────

    async def get_guider(self):
        return await self._get("/equipment/guider/info")

    async def connect_guider(self):
        return await self._get("/equipment/guider/connect")

    async def disconnect_guider(self):
        return await self._get("/equipment/guider/disconnect")

    async def start_guiding(self, calibrate: bool = False):
        return await self._get(
            "/equipment/guider/start", params={"calibrate": _b(calibrate)}
        )

    async def stop_guiding(self):
        return await self._get("/equipment/guider/stop")

    async def clear_guider_calibration(self):
        return await self._get("/equipment/guider/clear-calibration")

    async def get_guider_graph(self):
        """Recent guide steps, as configured on the N.I.N.A. guide graph."""
        return await self._get("/equipment/guider/graph")

    # ── Rotator ──────────────────────────────────────────────────────────────

    async def get_rotator(self):
        return await self._get("/equipment/rotator/info")

    async def connect_rotator(self):
        return await self._get("/equipment/rotator/connect")

    async def disconnect_rotator(self):
        return await self._get("/equipment/rotator/disconnect")

    async def move_rotator(self, position: float):
        return await self._get("/equipment/rotator/move", params={"position": position})

    async def move_rotator_mechanical(self, position: float):
        return await self._get(
            "/equipment/rotator/move-mechanical", params={"position": position}
        )

    async def set_rotator_reverse(self, reverse: bool):
        return await self._get(
            "/equipment/rotator/reverse", params={"reverseDirection": _b(reverse)}
        )

    async def stop_rotator(self):
        return await self._get("/equipment/rotator/stop-move")

    # ── Dome ─────────────────────────────────────────────────────────────────

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

    async def stop_dome(self):
        return await self._get("/equipment/dome/stop")

    async def park_dome(self):
        return await self._get("/equipment/dome/park")

    async def home_dome(self):
        return await self._get("/equipment/dome/home")

    async def sync_dome(self):
        return await self._get("/equipment/dome/sync")

    async def slew_dome(self, azimuth: float):
        return await self._get("/equipment/dome/slew", params={"azimuth": azimuth})

    async def set_dome_follow(self, enabled: bool):
        return await self._get(
            "/equipment/dome/set-follow", params={"enabled": _b(enabled)}
        )

    # ── Flat Device ──────────────────────────────────────────────────────────

    async def get_flatdevice(self):
        return await self._get("/equipment/flatdevice/info")

    async def connect_flatdevice(self):
        return await self._get("/equipment/flatdevice/connect")

    async def disconnect_flatdevice(self):
        return await self._get("/equipment/flatdevice/disconnect")

    async def set_flat_light(self, on: bool):
        return await self._get("/equipment/flatdevice/set-light", params={"on": _b(on)})

    async def set_flat_cover(self, closed: bool):
        return await self._get(
            "/equipment/flatdevice/set-cover", params={"closed": _b(closed)}
        )

    async def set_flat_brightness(self, brightness: int):
        return await self._get(
            "/equipment/flatdevice/set-brightness", params={"brightness": brightness}
        )

    # ── Switch device ────────────────────────────────────────────────────────

    async def get_switch(self):
        return await self._get("/equipment/switch/info")

    async def connect_switch(self):
        return await self._get("/equipment/switch/connect")

    async def disconnect_switch(self):
        return await self._get("/equipment/switch/disconnect")

    async def set_switch_value(self, index: int, value: float):
        return await self._get(
            "/equipment/switch/set", params={"index": index, "value": value}
        )

    # ── Weather / Safety ─────────────────────────────────────────────────────

    async def get_weather(self):
        return await self._get("/equipment/weather/info")

    async def connect_weather(self):
        return await self._get("/equipment/weather/connect")

    async def disconnect_weather(self):
        return await self._get("/equipment/weather/disconnect")

    async def get_safetymonitor(self):
        return await self._get("/equipment/safetymonitor/info")

    async def connect_safetymonitor(self):
        return await self._get("/equipment/safetymonitor/connect")

    async def disconnect_safetymonitor(self):
        return await self._get("/equipment/safetymonitor/disconnect")

    # ── Sequence ─────────────────────────────────────────────────────────────

    async def get_sequence(self):
        """Full sequence tree. ``Response`` is a list of root containers."""
        return await self._get("/sequence/state")

    async def start_sequence(self, skip_validation: bool = False):
        return await self._get(
            "/sequence/start", params={"skipValidation": _b(skip_validation)}
        )

    async def stop_sequence(self):
        return await self._get("/sequence/stop")

    async def skip_sequence_item(self, skip_type: str = "CurrentItems"):
        """Skip ahead. ``skip_type``: CurrentItems, ToEnd or ToImaging."""
        return await self._get("/sequence/skip", params={"type": skip_type})

    async def reset_sequence(self):
        return await self._get("/sequence/reset")

    async def list_available_sequences(self):
        return await self._get("/sequence/list-available")

    async def load_sequence(self, sequence_name: str):
        """Load a sequence by name from N.I.N.A.'s configured sequence folder."""
        return await self._get(
            "/sequence/load", params={"sequenceName": sequence_name}
        )

    # ── Profile ──────────────────────────────────────────────────────────────

    async def get_profile(self, active: bool = True):
        return await self._get("/profile/show", params={"active": _b(active)})

    async def switch_profile(self, profile_id: str):
        return await self._get("/profile/switch", params={"profileid": profile_id})

    # ── Flat Wizard ──────────────────────────────────────────────────────────

    async def get_flats_status(self):
        return await self._get("/flats/status")

    async def stop_flats(self):
        return await self._get("/flats/stop")

    async def start_skyflat(self, **params):
        return await self._get("/flats/skyflat", params=params or None)

    async def start_auto_brightness_flat(self, **params):
        return await self._get("/flats/auto-brightness", params=params or None)

    async def start_auto_exposure_flat(self, **params):
        return await self._get("/flats/auto-exposure", params=params or None)

    async def start_trained_flat(self, **params):
        return await self._get("/flats/trained-flat", params=params or None)

    async def start_trained_dark_flat(self, **params):
        return await self._get("/flats/trained-dark-flat", params=params or None)

    # ── Livestack (requires the Livestack N.I.N.A. plugin) ───────────────────

    async def get_livestack_status(self):
        return await self._get("/livestack/status")

    async def start_livestack(self):
        return await self._get("/livestack/start")

    async def stop_livestack(self):
        return await self._get("/livestack/stop")

    # ── Images ───────────────────────────────────────────────────────────────

    async def get_image_history(self, all_images: bool = True,
                                image_type: str | None = None):
        """Image history for the session.

        With ``all_images`` the ``Response`` is a list of per-frame statistics,
        ordered oldest first.
        """
        params: dict[str, Any] = {"all": _b(all_images)}
        if image_type is not None:
            params["imageType"] = image_type
        return await self._get("/image-history", params=params)

    async def get_image_count(self, image_type: str | None = None):
        """Number of images captured this session (``Response`` is an int)."""
        params: dict[str, Any] = {"count": _b(True)}
        if image_type is not None:
            params["imageType"] = image_type
        return await self._get("/image-history", params=params)

    def image_stream_url(self, index: int = -1, quality: int = 85,
                         auto_prepare: bool = True) -> str:
        """URL that streams a JPEG of image ``index``; -1 is the latest frame."""
        params = f"stream=true&quality={quality}"
        if auto_prepare:
            params += "&autoPrepare=true"
        return f"{self._base}/image/{index}?{params}"

    async def get_image_bytes(self, index: int = -1, quality: int = 85,
                              auto_prepare: bool = True) -> bytes:
        """Fetch a JPEG of image ``index``; -1 is the latest frame."""
        params: dict[str, Any] = {"stream": _b(True), "quality": quality}
        if auto_prepare:
            params["autoPrepare"] = _b(True)
        return await self._get_bytes(f"/image/{index}", params=params)

    async def get_thumbnail_bytes(self, index: int = -1) -> bytes:
        return await self._get_bytes(f"/image/thumbnail/{index}")

    # ── Bulk poll ────────────────────────────────────────────────────────────

    async def poll_all(self):
        """Fetch all polled state concurrently. Returns {subsystem: data}.

        Individual failures are swallowed so one missing device (or a missing
        optional N.I.N.A. plugin) never fails the whole update.
        """
        tasks = {
            "camera": self.get_camera(),
            "mount": self.get_mount(),
            "focuser": self.get_focuser(),
            "filterwheel": self.get_filterwheel(),
            "guider": self.get_guider(),
            "rotator": self.get_rotator(),
            "dome": self.get_dome(),
            "flatdevice": self.get_flatdevice(),
            "switch": self.get_switch(),
            "weather": self.get_weather(),
            "safetymonitor": self.get_safetymonitor(),
            "sequence": self.get_sequence(),
            # The active profile carries TelescopeSettings.FocalLength, which
            # changes when a focal reducer is swapped in, so it is polled
            # rather than read once at setup.
            "profile": self.get_profile(active=True),
            "profiles": self.get_profile(active=False),
            "image_history": self.get_image_history(all_images=True),
            "last_af": self.get_last_autofocus(),
            "flats": self.get_flats_status(),
            "livestack": self.get_livestack_status(),
            "nina_version": self.get_nina_version(),
            "app_start": self.get_application_start(),
        }
        results = {}
        responses = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for key, response in zip(tasks.keys(), responses):
            if isinstance(response, Exception):
                _LOGGER.debug("Poll error for %s: %s", key, response)
                results[key] = {}
            else:
                results[key] = response
        return results

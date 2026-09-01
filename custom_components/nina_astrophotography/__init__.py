"""N.I.N.A. Astrophotography integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NinaApiClient, NinaConnectionError
from .const import (
    APPLICATION_TABS,
    CONF_API_VERSION,
    CONF_HOST,
    CONF_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DEFAULT_API_VERSION,
    DEFAULT_NAME,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DOMAIN,
    IMAGE_TYPES,
    SEQUENCE_SKIP_TYPES,
    SERVICE_CAMERA_ABORT_CAPTURE,
    SERVICE_CAMERA_CAPTURE,
    SERVICE_CAMERA_COOL,
    SERVICE_CAMERA_DEW_HEATER,
    SERVICE_CAMERA_SET_BINNING,
    SERVICE_CAMERA_WARM,
    SERVICE_DOME_CLOSE,
    SERVICE_DOME_OPEN,
    SERVICE_DOME_PARK,
    SERVICE_DOME_SET_FOLLOW,
    SERVICE_DOME_SLEW,
    SERVICE_FILTERWHEEL_CHANGE,
    SERVICE_FLATS_AUTO_BRIGHTNESS,
    SERVICE_FLATS_AUTO_EXPOSURE,
    SERVICE_FLATS_SKYFLAT,
    SERVICE_FLATS_STOP,
    SERVICE_FLATS_TRAINED,
    SERVICE_FOCUSER_AUTO_FOCUS,
    SERVICE_FOCUSER_MOVE,
    SERVICE_GUIDER_CLEAR_CALIBRATION,
    SERVICE_GUIDER_START,
    SERVICE_GUIDER_STOP,
    SERVICE_MOUNT_FLIP,
    SERVICE_MOUNT_PARK,
    SERVICE_MOUNT_SLEW,
    SERVICE_MOUNT_STOP_SLEW,
    SERVICE_MOUNT_SYNC,
    SERVICE_MOUNT_TRACKING,
    SERVICE_MOUNT_UNPARK,
    SERVICE_ROTATOR_MOVE,
    SERVICE_SEQUENCE_LOAD,
    SERVICE_SEQUENCE_RESET,
    SERVICE_SEQUENCE_SKIP,
    SERVICE_SEQUENCE_START,
    SERVICE_SEQUENCE_STOP,
    SERVICE_SWITCH_SET,
    SERVICE_SWITCH_TAB,
    TRACKING_MODES,
)
from .coordinator import NinaDataCoordinator
from .device import (
    async_register_hub,
    async_sync_devices,
    forget_instance,
    set_instance_name,
)
from .frame_statistics import NinaFrameStatisticsStore
from .websocket import NinaWebSocketClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.LIGHT,
    Platform.BUTTON,
    Platform.IMAGE,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up N.I.N.A. from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    api_version = entry.data.get(CONF_API_VERSION, DEFAULT_API_VERSION)
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )

    session = async_get_clientsession(hass)
    client = NinaApiClient(host=host, port=port, api_version=api_version, session=session)

    # Verify reachability at startup
    try:
        await client.get_version()
    except NinaConnectionError as exc:
        raise ConfigEntryNotReady(f"Cannot connect to N.I.N.A. at {host}:{port}") from exc

    # Device names carry this label and entity ids derive from device names,
    # so it must be set before any platform is forwarded.
    set_instance_name(entry.entry_id, entry.data.get(CONF_NAME) or DEFAULT_NAME)
    async_register_hub(hass, entry, host, port)

    coordinator = NinaDataCoordinator(hass, client, poll_interval)
    await coordinator.async_config_entry_first_refresh()

    # ── WebSocket: real-time push events ──────────────────────────────────────
    ws_client = NinaWebSocketClient(
        host=host,
        port=port,
        session=session,
        hass_event_bus_fire=hass.bus.fire,
        api_version=api_version,
    )
    await ws_client.start()

    # ── Per-frame statistics store ───────────────────────────────────────────
    frame_store = NinaFrameStatisticsStore()

    async def _on_image_save(response: dict) -> None:
        frame_store.push_frame(response)
        await coordinator.async_request_refresh()

    ws_client.add_listener(
        "IMAGE-SAVE",
        lambda r: hass.async_create_task(_on_image_save(r)),
    )

    # Reset per-session stats when a new sequence starts
    ws_client.add_listener("SEQUENCE-STARTING", lambda r: frame_store.reset())

    # Events that change polled state should refresh it without waiting for the
    # next poll tick.
    def _refresh(_response: dict) -> None:
        hass.async_create_task(coordinator.async_request_refresh())

    for event in (
        "FILTERWHEEL-CHANGED",
        "SAFETY-CHANGED",
        "FLAT-BRIGHTNESS-CHANGED",
        "FLAT-LIGHT-TOGGLED",
        "FLAT-COVER-OPENED",
        "FLAT-COVER-CLOSED",
        "AUTOFOCUS-FINISHED",
        "SEQUENCE-STARTING",
        "SEQUENCE-FINISHED",
        "MOUNT-PARKED",
        "MOUNT-UNPARKED",
        "MOUNT-HOMED",
        "MOUNT-AFTER-FLIP",
        "DOME-SHUTTER-OPENED",
        "DOME-SHUTTER-CLOSED",
        "DOME-PARKED",
        "DOME-HOMED",
        "GUIDER-START",
        "GUIDER-STOP",
        "ROTATOR-MOVED",
        "ROTATOR-MOVED-MECHANICAL",
        "STACK-STATUS",
    ):
        ws_client.add_listener(event, _refresh)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "client": client,
        "ws_client": ws_client,
        "frame_store": frame_store,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Equipment is often disconnected at startup, so its driver name and
    # version only show up on a later poll. Sync now and on every update.
    async_sync_devices(hass, entry.entry_id, coordinator.data or {})

    @callback
    def _sync_devices() -> None:
        async_sync_devices(hass, entry.entry_id, coordinator.data or {})

    entry.async_on_unload(coordinator.async_add_listener(_sync_devices))

    _register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    ws: NinaWebSocketClient | None = entry_data.get("ws_client")
    if ws:
        await ws.stop()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        forget_instance(entry.entry_id)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update — reload to apply new poll interval."""
    await hass.config_entries.async_reload(entry.entry_id)


# ─── Service registration ─────────────────────────────────────────────────────


def _client_for_call(hass: HomeAssistant, call: ServiceCall) -> NinaApiClient:
    """Resolve which N.I.N.A. instance a service call is aimed at.

    With one instance configured the call needs no target. With several, the
    call must name a target device — guessing would silently drive the wrong
    observatory.
    """
    entries = hass.data.get(DOMAIN, {})
    if not entries:
        raise HomeAssistantError("No N.I.N.A. integration is configured")

    device_ids = call.data.get(ATTR_DEVICE_ID) or []
    if isinstance(device_ids, str):
        device_ids = [device_ids]
    if device_ids:
        registry = dr.async_get(hass)
        for device_id in device_ids:
            device = registry.async_get(device_id)
            if device is None:
                continue
            for entry_id in device.config_entries:
                if entry_id in entries:
                    return entries[entry_id]["client"]
        raise HomeAssistantError(
            "The targeted device does not belong to a N.I.N.A. instance"
        )

    if len(entries) == 1:
        return next(iter(entries.values()))["client"]
    raise HomeAssistantError(
        f"{len(entries)} N.I.N.A. instances are configured; "
        "target a device belonging to the one you mean"
    )


async def _refresh_all(hass: HomeAssistant) -> None:
    for entry_data in hass.data.get(DOMAIN, {}).values():
        await entry_data["coordinator"].async_request_refresh()


def _register_services(hass: HomeAssistant) -> None:
    """Register all Home Assistant services for N.I.N.A. control."""

    if hass.services.has_service(DOMAIN, SERVICE_CAMERA_COOL):
        return  # already registered by a previous config entry

    def register(name: str, handler, schema=None) -> None:
        hass.services.async_register(DOMAIN, name, handler, schema=schema)

    # ── Camera ──────────────────────────────────────────────────────────────

    async def handle_camera_cool(call: ServiceCall) -> None:
        await _client_for_call(hass, call).cool_camera(
            temperature=call.data["temperature"],
            minutes=call.data.get("minutes", -1),
            cancel=call.data.get("cancel", False),
        )
        await _refresh_all(hass)

    register(
        SERVICE_CAMERA_COOL,
        handle_camera_cool,
        vol.Schema(
            {
                vol.Required("temperature"): vol.Coerce(float),
                vol.Optional("minutes", default=-1): vol.Coerce(float),
                vol.Optional("cancel", default=False): cv.boolean,
            }
        ),
    )

    async def handle_camera_warm(call: ServiceCall) -> None:
        await _client_for_call(hass, call).warm_camera(
            minutes=call.data.get("minutes", -1),
            cancel=call.data.get("cancel", False),
        )
        await _refresh_all(hass)

    register(
        SERVICE_CAMERA_WARM,
        handle_camera_warm,
        vol.Schema(
            {
                vol.Optional("minutes", default=-1): vol.Coerce(float),
                vol.Optional("cancel", default=False): cv.boolean,
            }
        ),
    )

    async def handle_capture(call: ServiceCall) -> None:
        await _client_for_call(hass, call).capture_image(
            duration=call.data.get("duration"),
            gain=call.data.get("gain"),
            save=call.data.get("save", False),
            solve=call.data.get("solve", False),
            wait_for_result=call.data.get("wait_for_result", False),
            image_type=call.data.get("image_type"),
            target_name=call.data.get("target_name"),
        )

    register(
        SERVICE_CAMERA_CAPTURE,
        handle_capture,
        vol.Schema(
            {
                vol.Optional("duration"): vol.Coerce(float),
                vol.Optional("gain"): vol.Coerce(int),
                vol.Optional("save", default=False): cv.boolean,
                vol.Optional("solve", default=False): cv.boolean,
                vol.Optional("wait_for_result", default=False): cv.boolean,
                vol.Optional("image_type"): vol.In(IMAGE_TYPES),
                vol.Optional("target_name"): cv.string,
            }
        ),
    )

    async def handle_abort_capture(call: ServiceCall) -> None:
        await _client_for_call(hass, call).abort_capture()

    register(SERVICE_CAMERA_ABORT_CAPTURE, handle_abort_capture)

    async def handle_set_binning(call: ServiceCall) -> None:
        await _client_for_call(hass, call).set_binning(call.data["binning"])
        await _refresh_all(hass)

    register(
        SERVICE_CAMERA_SET_BINNING,
        handle_set_binning,
        vol.Schema({vol.Required("binning"): cv.string}),
    )

    async def handle_dew_heater(call: ServiceCall) -> None:
        await _client_for_call(hass, call).set_dew_heater(call.data["enabled"])
        await _refresh_all(hass)

    register(
        SERVICE_CAMERA_DEW_HEATER,
        handle_dew_heater,
        vol.Schema({vol.Required("enabled"): cv.boolean}),
    )

    # ── Mount ────────────────────────────────────────────────────────────────

    async def handle_slew(call: ServiceCall) -> None:
        await _client_for_call(hass, call).slew_mount(
            ra_degrees=call.data["ra"],
            dec_degrees=call.data["dec"],
            wait_for_result=call.data.get("wait_for_result", False),
            center=call.data.get("center", False),
            rotate=call.data.get("rotate", False),
            rotation_angle=call.data.get("rotation_angle"),
        )
        await _refresh_all(hass)

    register(
        SERVICE_MOUNT_SLEW,
        handle_slew,
        vol.Schema(
            {
                # The API takes both angles in degrees.
                vol.Required("ra"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
                vol.Required("dec"): vol.All(
                    vol.Coerce(float), vol.Range(min=-90, max=90)
                ),
                vol.Optional("wait_for_result", default=False): cv.boolean,
                vol.Optional("center", default=False): cv.boolean,
                vol.Optional("rotate", default=False): cv.boolean,
                vol.Optional("rotation_angle"): vol.Coerce(float),
            }
        ),
    )

    async def handle_stop_slew(call: ServiceCall) -> None:
        await _client_for_call(hass, call).stop_slew()
        await _refresh_all(hass)

    register(SERVICE_MOUNT_STOP_SLEW, handle_stop_slew)

    async def handle_sync(call: ServiceCall) -> None:
        await _client_for_call(hass, call).sync_mount(
            ra_degrees=call.data["ra"], dec_degrees=call.data["dec"]
        )
        await _refresh_all(hass)

    register(
        SERVICE_MOUNT_SYNC,
        handle_sync,
        vol.Schema(
            {
                vol.Required("ra"): vol.All(vol.Coerce(float), vol.Range(min=0, max=360)),
                vol.Required("dec"): vol.All(
                    vol.Coerce(float), vol.Range(min=-90, max=90)
                ),
            }
        ),
    )

    async def handle_park(call: ServiceCall) -> None:
        await _client_for_call(hass, call).park_mount()
        await _refresh_all(hass)

    register(SERVICE_MOUNT_PARK, handle_park)

    async def handle_unpark(call: ServiceCall) -> None:
        await _client_for_call(hass, call).unpark_mount()
        await _refresh_all(hass)

    register(SERVICE_MOUNT_UNPARK, handle_unpark)

    async def handle_flip(call: ServiceCall) -> None:
        await _client_for_call(hass, call).meridian_flip()
        await _refresh_all(hass)

    register(SERVICE_MOUNT_FLIP, handle_flip)

    async def handle_tracking(call: ServiceCall) -> None:
        from .const import TRACKING_MODE_TO_INDEX

        mode = call.data["mode"]
        await _client_for_call(hass, call).set_tracking_mode(TRACKING_MODE_TO_INDEX[mode])
        await _refresh_all(hass)

    register(
        SERVICE_MOUNT_TRACKING,
        handle_tracking,
        vol.Schema({vol.Required("mode"): vol.In(TRACKING_MODES)}),
    )

    # ── Focuser ──────────────────────────────────────────────────────────────

    async def handle_focuser_move(call: ServiceCall) -> None:
        await _client_for_call(hass, call).move_focuser(call.data["position"])
        await _refresh_all(hass)

    register(
        SERVICE_FOCUSER_MOVE,
        handle_focuser_move,
        vol.Schema({vol.Required("position"): vol.Coerce(int)}),
    )

    async def handle_autofocus(call: ServiceCall) -> None:
        await _client_for_call(hass, call).auto_focus(cancel=call.data.get("cancel", False))

    register(
        SERVICE_FOCUSER_AUTO_FOCUS,
        handle_autofocus,
        vol.Schema({vol.Optional("cancel", default=False): cv.boolean}),
    )

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def handle_filter_change(call: ServiceCall) -> None:
        await _client_for_call(hass, call).change_filter(call.data["filter_id"])
        await _refresh_all(hass)

    register(
        SERVICE_FILTERWHEEL_CHANGE,
        handle_filter_change,
        vol.Schema({vol.Required("filter_id"): vol.Coerce(int)}),
    )

    # ── Guider ───────────────────────────────────────────────────────────────

    async def handle_guider_start(call: ServiceCall) -> None:
        await _client_for_call(hass, call).start_guiding(
            calibrate=call.data.get("calibrate", False)
        )
        await _refresh_all(hass)

    register(
        SERVICE_GUIDER_START,
        handle_guider_start,
        vol.Schema({vol.Optional("calibrate", default=False): cv.boolean}),
    )

    async def handle_guider_stop(call: ServiceCall) -> None:
        await _client_for_call(hass, call).stop_guiding()
        await _refresh_all(hass)

    register(SERVICE_GUIDER_STOP, handle_guider_stop)

    async def handle_clear_calibration(call: ServiceCall) -> None:
        await _client_for_call(hass, call).clear_guider_calibration()

    register(SERVICE_GUIDER_CLEAR_CALIBRATION, handle_clear_calibration)

    # ── Rotator ──────────────────────────────────────────────────────────────

    async def handle_rotator_move(call: ServiceCall) -> None:
        client = _client_for_call(hass, call)
        if call.data.get("mechanical", False):
            await client.move_rotator_mechanical(call.data["position"])
        else:
            await client.move_rotator(call.data["position"])
        await _refresh_all(hass)

    register(
        SERVICE_ROTATOR_MOVE,
        handle_rotator_move,
        vol.Schema(
            {
                vol.Required("position"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=360)
                ),
                vol.Optional("mechanical", default=False): cv.boolean,
            }
        ),
    )

    # ── Dome ─────────────────────────────────────────────────────────────────

    async def handle_dome_open(call: ServiceCall) -> None:
        await _client_for_call(hass, call).open_dome()
        await _refresh_all(hass)

    register(SERVICE_DOME_OPEN, handle_dome_open)

    async def handle_dome_close(call: ServiceCall) -> None:
        await _client_for_call(hass, call).close_dome()
        await _refresh_all(hass)

    register(SERVICE_DOME_CLOSE, handle_dome_close)

    async def handle_dome_park(call: ServiceCall) -> None:
        await _client_for_call(hass, call).park_dome()
        await _refresh_all(hass)

    register(SERVICE_DOME_PARK, handle_dome_park)

    async def handle_dome_slew(call: ServiceCall) -> None:
        await _client_for_call(hass, call).slew_dome(call.data["azimuth"])
        await _refresh_all(hass)

    register(
        SERVICE_DOME_SLEW,
        handle_dome_slew,
        vol.Schema(
            {
                vol.Required("azimuth"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=360)
                )
            }
        ),
    )

    async def handle_dome_follow(call: ServiceCall) -> None:
        await _client_for_call(hass, call).set_dome_follow(call.data["enabled"])
        await _refresh_all(hass)

    register(
        SERVICE_DOME_SET_FOLLOW,
        handle_dome_follow,
        vol.Schema({vol.Required("enabled"): cv.boolean}),
    )

    # ── Switch device ────────────────────────────────────────────────────────

    async def handle_switch_set(call: ServiceCall) -> None:
        await _client_for_call(hass, call).set_switch_value(
            call.data["index"], call.data["value"]
        )
        await _refresh_all(hass)

    register(
        SERVICE_SWITCH_SET,
        handle_switch_set,
        vol.Schema(
            {
                vol.Required("index"): vol.Coerce(int),
                vol.Required("value"): vol.Coerce(float),
            }
        ),
    )

    # ── Sequence ─────────────────────────────────────────────────────────────

    async def handle_seq_start(call: ServiceCall) -> None:
        await _client_for_call(hass, call).start_sequence(
            skip_validation=call.data.get("skip_validation", False)
        )
        await _refresh_all(hass)

    register(
        SERVICE_SEQUENCE_START,
        handle_seq_start,
        vol.Schema({vol.Optional("skip_validation", default=False): cv.boolean}),
    )

    async def handle_seq_stop(call: ServiceCall) -> None:
        await _client_for_call(hass, call).stop_sequence()
        await _refresh_all(hass)

    register(SERVICE_SEQUENCE_STOP, handle_seq_stop)

    async def handle_seq_skip(call: ServiceCall) -> None:
        await _client_for_call(hass, call).skip_sequence_item(
            call.data.get("type", "CurrentItems")
        )
        await _refresh_all(hass)

    register(
        SERVICE_SEQUENCE_SKIP,
        handle_seq_skip,
        vol.Schema(
            {vol.Optional("type", default="CurrentItems"): vol.In(SEQUENCE_SKIP_TYPES)}
        ),
    )

    async def handle_seq_reset(call: ServiceCall) -> None:
        await _client_for_call(hass, call).reset_sequence()
        await _refresh_all(hass)

    register(SERVICE_SEQUENCE_RESET, handle_seq_reset)

    async def handle_seq_load(call: ServiceCall) -> None:
        await _client_for_call(hass, call).load_sequence(call.data["sequence_name"])
        await _refresh_all(hass)

    register(
        SERVICE_SEQUENCE_LOAD,
        handle_seq_load,
        vol.Schema({vol.Required("sequence_name"): cv.string}),
    )

    # ── Flat Wizard ──────────────────────────────────────────────────────────

    _FLAT_COMMON = {
        vol.Required("count"): vol.Coerce(int),
        vol.Optional("filter_id"): vol.Coerce(int),
        vol.Optional("binning"): cv.string,
        vol.Optional("gain"): vol.Coerce(int),
        vol.Optional("offset"): vol.Coerce(int),
    }

    def _flat_params(call: ServiceCall) -> dict:
        """Map the service's snake_case fields onto the API's query names."""
        mapping = {
            "count": "count",
            "filter_id": "filterId",
            "binning": "binning",
            "gain": "gain",
            "offset": "offset",
            "keep_closed": "keepClosed",
            "exposure_time": "exposureTime",
            "brightness": "brightness",
            "min_exposure": "minExposure",
            "max_exposure": "maxExposure",
            "min_brightness": "minBrightness",
            "max_brightness": "maxBrightness",
            "histogram_mean": "histogramMean",
            "mean_tolerance": "meanTolerance",
            "dither": "dither",
        }
        params = {}
        for key, api_name in mapping.items():
            if key in call.data:
                value = call.data[key]
                params[api_name] = (
                    "true" if value is True else "false" if value is False else value
                )
        return params

    async def handle_trained_flat(call: ServiceCall) -> None:
        await _client_for_call(hass, call).start_trained_flat(**_flat_params(call))

    register(
        SERVICE_FLATS_TRAINED,
        handle_trained_flat,
        vol.Schema({**_FLAT_COMMON, vol.Optional("keep_closed"): cv.boolean}),
    )

    # Auto-exposure holds panel brightness fixed and lets N.I.N.A. pick the
    # exposure time; auto-brightness is its complement.
    async def handle_auto_exposure_flat(call: ServiceCall) -> None:
        await _client_for_call(hass, call).start_auto_exposure_flat(**_flat_params(call))

    register(
        SERVICE_FLATS_AUTO_EXPOSURE,
        handle_auto_exposure_flat,
        vol.Schema(
            {
                **_FLAT_COMMON,
                vol.Required("brightness"): vol.Coerce(float),
                vol.Optional("keep_closed"): cv.boolean,
                vol.Optional("histogram_mean"): vol.Coerce(float),
                vol.Optional("mean_tolerance"): vol.Coerce(float),
                vol.Optional("min_exposure"): vol.Coerce(float),
                vol.Optional("max_exposure"): vol.Coerce(float),
            }
        ),
    )

    async def handle_auto_brightness_flat(call: ServiceCall) -> None:
        await _client_for_call(hass, call).start_auto_brightness_flat(**_flat_params(call))

    register(
        SERVICE_FLATS_AUTO_BRIGHTNESS,
        handle_auto_brightness_flat,
        vol.Schema(
            {
                **_FLAT_COMMON,
                vol.Required("exposure_time"): vol.Coerce(float),
                vol.Optional("keep_closed"): cv.boolean,
                vol.Optional("histogram_mean"): vol.Coerce(float),
                vol.Optional("mean_tolerance"): vol.Coerce(float),
                vol.Optional("min_brightness"): vol.Coerce(int),
                vol.Optional("max_brightness"): vol.Coerce(int),
            }
        ),
    )

    async def handle_skyflat(call: ServiceCall) -> None:
        await _client_for_call(hass, call).start_skyflat(**_flat_params(call))

    register(
        SERVICE_FLATS_SKYFLAT,
        handle_skyflat,
        vol.Schema(
            {
                **_FLAT_COMMON,
                vol.Optional("min_exposure"): vol.Coerce(float),
                vol.Optional("max_exposure"): vol.Coerce(float),
                vol.Optional("histogram_mean"): vol.Coerce(float),
                vol.Optional("mean_tolerance"): vol.Coerce(float),
                vol.Optional("dither"): cv.boolean,
            }
        ),
    )

    async def handle_flats_stop(call: ServiceCall) -> None:
        await _client_for_call(hass, call).stop_flats()
        await _refresh_all(hass)

    register(SERVICE_FLATS_STOP, handle_flats_stop)

    # ── Application ──────────────────────────────────────────────────────────

    async def handle_switch_tab(call: ServiceCall) -> None:
        await _client_for_call(hass, call).switch_tab(call.data["tab"])

    register(
        SERVICE_SWITCH_TAB,
        handle_switch_tab,
        vol.Schema({vol.Required("tab"): vol.In(APPLICATION_TABS)}),
    )

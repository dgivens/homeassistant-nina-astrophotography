"""N.I.N.A. Astrophotography integration for Home Assistant."""
from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaError,
    NinaRequestError,
    NinaUnavailableError,
)
from .api.models import NinaEvent
from .api.v2 import NinaClientV2, NinaEventStream
from .const import (
    CONF_HOST,
    CONF_INSTANCE_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_ROLLOVER_HOUR,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_ROLLOVER_HOUR,
    DOMAIN,
    SERVICE_CAMERA_ABORT_CAPTURE,
    SERVICE_CAMERA_CAPTURE,
    SERVICE_CAMERA_COOL,
    SERVICE_CAMERA_WARM,
    SERVICE_DOME_CLOSE,
    SERVICE_DOME_OPEN,
    SERVICE_DOME_PARK,
    SERVICE_FILTERWHEEL_CHANGE,
    SERVICE_FOCUSER_AUTO_FOCUS,
    SERVICE_FOCUSER_MOVE,
    SERVICE_GUIDER_START,
    SERVICE_GUIDER_STOP,
    SERVICE_MOUNT_PARK,
    SERVICE_MOUNT_SLEW,
    SERVICE_MOUNT_TRACKING,
    SERVICE_MOUNT_UNPARK,
    SERVICE_SEQUENCE_LOAD,
    SERVICE_SEQUENCE_START,
    SERVICE_SEQUENCE_STOP,
    TrackingMode,
)
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaRuntimeData
from .device import async_sync_devices, kind_of

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.EVENT,
    Platform.IMAGE,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# The integration is config-entry only: nothing is configured from YAML.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, once, before any entry is set up."""
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Set up N.I.N.A. from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )
    rollover_hour = entry.options.get(CONF_ROLLOVER_HOUR, DEFAULT_ROLLOVER_HOUR)
    # Entries created before 2.0 carry no instance name; their title is the one
    # thing they have, and it is what the flow now writes into both.
    instance_name = entry.data.get(CONF_INSTANCE_NAME, entry.title)

    session = async_get_clientsession(hass)
    client = NinaClientV2(host, port, session)

    # Verify reachability at startup
    try:
        version = await client.get_versions()
    except (NinaEndpointError, NinaRequestError) as exc:
        # A path this build does not serve will not appear later, so fail the
        # entry rather than retrying forever.
        raise ConfigEntryError(
            f"N.I.N.A. at {host}:{port} does not serve the expected API: {exc}"
        ) from exc
    except (NinaConnectionError, NinaUnavailableError, NinaCommandError) as exc:
        # All transient at startup — NINA may still be booting, or answering
        # unhappily while equipment connects. ConfigEntryNotReady retries; an
        # uncaught exception fails the entry permanently.
        raise ConfigEntryNotReady(
            f"N.I.N.A. at {host}:{port} is not ready: {exc}"
        ) from exc

    coordinator = NinaCoordinator(
        hass,
        client,
        config_entry=entry,
        update_interval=timedelta(seconds=poll_interval),
        version=version,
        rollover_hour=rollover_hour,
    )

    # ── The event socket: real-time push ─────────────────────────────────────
    def _fire_bus_event(event: NinaEvent) -> None:
        """Keep the 1.4.x automation contract: `nina_<event>` plus the catch-all.

        The payload is derived from the model, so a wire dict never reaches an
        automation; phase D rewrites the blueprints against the entities.
        """
        payload = {
            "event": event.name,
            "time": event.time.isoformat(),
            "data": dict(event.data),
            "frame": asdict(event.frame) if event.frame is not None else None,
        }
        hass.bus.async_fire(f"nina_{event.name.lower().replace('-', '_')}", payload)
        hass.bus.async_fire("nina_event", payload)

    connected_before = False

    def _fire_connection_event(connected: bool) -> None:
        nonlocal connected_before
        hass.bus.async_fire(
            "nina_websocket_connected" if connected else "nina_websocket_disconnected",
            {},
        )
        if not connected:
            return
        if connected_before:
            # A RECONNECT, so the socket has been silent for a while: the frame
            # set is reseeded and /event-history replayed for what it missed.
            # The first connection needs neither — setup has just done both.
            coordinator.schedule_reconnect()
        connected_before = True

    events = NinaEventStream(
        host=host,
        port=port,
        session=session,
        rig_offset=lambda: client.rig_offset,
        on_connection=_fire_connection_event,
    )
    # Wired BEFORE the first refresh: that refresh replays /event-history
    # through the stream, and it is what first sets the generation the stream
    # stamps on every event it dispatches.
    coordinator.event_stream = events
    events.subscribe(coordinator.handle_event)
    events.subscribe(_fire_bus_event)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = NinaRuntimeData(
        client=client,
        coordinator=coordinator,
        instance_name=instance_name,
        events=events,
    )
    # Registered before the socket starts: on_unload callbacks also run when a
    # later setup step fails, which is what keeps the reconnect task from
    # outliving a failed entry.
    entry.async_on_unload(events.stop)

    # Before the platforms: an entity's `via_device` needs the hub to exist,
    # and a child device created here rather than by an entity is what lets a
    # piece of equipment carrying no entities still appear.
    async_sync_devices(hass, entry, coordinator.data)
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: async_sync_devices(hass, entry, coordinator.data)
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # AFTER the platforms, so nothing dispatches into a window where the
    # subscribers do not exist yet. `event.nina_error` subscribes in
    # `async_added_to_hass` (Bronze entity-event-setup), and replay
    # deliberately does not re-fire — so an ERROR-* arriving while nine
    # platforms set themselves up would be lost for good, on every reload.
    await events.start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Unload a config entry. The socket stops via `async_on_unload`."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NinaConfigEntry, device: DeviceEntry
) -> bool:
    """Allow deleting equipment the rig no longer reports (Gold stale-devices).

    A device is created on first sight and never removed by a poll — equipment
    is routinely down — so retiring a sold focuser is the user's call. The one
    thing that is not their call is a device the rig still reports, or the hub:
    both would come straight back.
    """
    try:
        kind = kind_of(entry.entry_id, device)
    except LookupError:
        # An identifier scheme we no longer write. Nothing will ever claim it.
        return True
    if kind is None:
        return False
    if not hasattr(entry, "runtime_data"):
        # The hook runs against a disabled or unloaded entry too, and Home
        # Assistant drops `runtime_data` on unload. Nothing is polling, so
        # nothing can recreate the device.
        return True
    return getattr(entry.runtime_data.coordinator.data.snapshot, kind) is None


async def _async_update_listener(hass: HomeAssistant, entry: NinaConfigEntry) -> None:
    """Handle options update — reload to apply new poll interval."""
    await hass.config_entries.async_reload(entry.entry_id)


# ─── Service registration ─────────────────────────────────────────────────────

def _entry_for_device(hass: HomeAssistant, device_id: str) -> NinaConfigEntry:
    """The loaded entry a targeted device belongs to.

    Any of the entry's devices identifies it — the hub or a piece of its
    equipment — because they all carry the same config entry.
    """
    device = dr.async_get(hass).async_get(device_id)
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        if device is not None and entry.entry_id in device.config_entries:
            return entry
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="unknown_target",
        translation_placeholders={"device_id": device_id},
    )


def _client_for_target(hass: HomeAssistant, call: ServiceCall) -> NinaClientV2:
    """Resolve which rig a call means.

    1.4.5 returned the first loaded entry, so a second rig was unreachable from
    the services however it was targeted. An untargeted call still works while
    one instance is configured, which is what most installs are.
    """
    targeted = [_entry_for_device(hass, device_id)
                for device_id in call.data.get(ATTR_DEVICE_ID, ())]
    entries = {entry.entry_id: entry
               for entry in targeted or hass.config_entries.async_loaded_entries(DOMAIN)}
    if len(entries) == 1:
        return next(iter(entries.values())).runtime_data.client
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="no_instance" if not entries else "ambiguous_target",
    )


def _bounded(field: str, minimum: float,
             maximum: float | None = None) -> Callable[[float], float]:
    """Refuse out-of-range input as a validation error, not a `vol.Invalid`.

    Out-of-range input is silently clamped and answered `Success: true`, so
    nothing downstream ever reports it, and `services.yaml`'s selectors are a
    UI hint that binds nothing from a script or the REST API.
    """
    limits = f"between {minimum} and {maximum}" if maximum is not None \
        else f"{minimum} or more"

    def validate(value: float) -> float:
        if value < minimum or (maximum is not None and value > maximum):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="out_of_range",
                translation_placeholders={
                    "field": field, "value": str(value), "limits": limits,
                },
            )
        return value

    return validate


def _schema(fields: dict[vol.Marker, Any] | None = None) -> vol.Schema:
    """One service's schema, with the device target every service accepts."""
    return vol.Schema({
        vol.Optional(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        **(fields or {}),
    })


def _service(handler: Callable[[ServiceCall], Awaitable[None]]):
    """Wrap a handler so a refusal reads as a refusal.

    `NinaError` subclasses `Exception` alone — deliberately, to keep the API
    layer free of Home Assistant — so one escaping a service handler is treated
    by Home Assistant as an integration DEFECT: the automation step fails with
    a traceback and the frontend offers to file a bug. A disconnected mount is
    not a bug in this integration. Every platform already does this at its own
    boundary; the services are the last place that did not.
    """
    @functools.wraps(handler)
    async def wrapped(call: ServiceCall) -> None:
        try:
            await handler(call)
        except NinaError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(exc)},
            ) from exc

    return wrapped


def _register_services(hass: HomeAssistant) -> None:
    """Register every N.I.N.A. action.

    Registered from `async_setup`, so the actions exist whether or not an entry
    is loaded (Bronze `action-setup`): registered per entry, they would vanish
    with the last one and an automation referencing one would fail validation
    rather than failing legibly at call time. Which rig a call means is
    resolved per call instead, by `_client_for_target`.
    """

    # ── Camera ──────────────────────────────────────────────────────────────

    async def handle_camera_cool(call: ServiceCall) -> None:
        await _client_for_target(hass, call).cool_camera(
            call.data["temperature"], minutes=call.data["minutes"]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAMERA_COOL,
        _service(handle_camera_cool),
        schema=_schema({
            vol.Required("temperature"): vol.Coerce(float),
            vol.Optional("minutes", default=10): vol.Coerce(float),
        }),
    )

    async def handle_camera_warm(call: ServiceCall) -> None:
        await _client_for_target(hass, call).warm_camera(minutes=call.data["minutes"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAMERA_WARM,
        _service(handle_camera_warm),
        schema=_schema({vol.Optional("minutes", default=10): vol.Coerce(float)}),
    )

    async def handle_capture(call: ServiceCall) -> None:
        await _client_for_target(hass, call).capture_image(
            call.data["duration"],
            gain=call.data.get("gain"),
            save=call.data["save"],
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAMERA_CAPTURE,
        _service(handle_capture),
        # `binning` and `filter_index` are gone rather than accepted and
        # dropped: `/equipment/camera/capture` binds neither, and a parameter
        # that looks like it works is worse than no parameter.
        schema=_schema({
            vol.Required("duration"): vol.All(vol.Coerce(float),
                                              _bounded("Duration", 0)),
            vol.Optional("gain"): vol.All(vol.Coerce(int), _bounded("Gain", 0)),
            vol.Optional("save", default=False): cv.boolean,
        }),
    )

    async def handle_abort_capture(call: ServiceCall) -> None:
        await _client_for_target(hass, call).abort_capture()

    hass.services.async_register(DOMAIN, SERVICE_CAMERA_ABORT_CAPTURE,
        _service(handle_abort_capture), schema=_schema())

    # ── Mount ────────────────────────────────────────────────────────────────

    async def handle_slew(call: ServiceCall) -> None:
        await _client_for_target(hass, call).slew_mount(
            call.data["ra_degrees"], call.data["dec_degrees"]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_MOUNT_SLEW,
        _service(handle_slew),
        # J2000 degrees, sent through untouched. 1.4.5 took hours and
        # multiplied by 15, which reads plausibly for a coordinate that came
        # back out of `MountInfo` — reported in the MOUNT's epoch and in hours,
        # so feeding one back was wrong twice and nothing caught it.
        schema=_schema({
            vol.Required("ra_degrees"): vol.All(
                vol.Coerce(float), _bounded("Right ascension", 0, 360)),
            vol.Required("dec_degrees"): vol.All(
                vol.Coerce(float), _bounded("Declination", -90, 90)),
        }),
    )

    async def handle_park(call: ServiceCall) -> None:
        await _client_for_target(hass, call).park_mount()

    hass.services.async_register(DOMAIN, SERVICE_MOUNT_PARK,
        _service(handle_park), schema=_schema())

    async def handle_unpark(call: ServiceCall) -> None:
        await _client_for_target(hass, call).unpark_mount()

    hass.services.async_register(DOMAIN, SERVICE_MOUNT_UNPARK,
        _service(handle_unpark), schema=_schema())

    async def handle_tracking(call: ServiceCall) -> None:
        mode = TrackingMode.SIDEREAL if call.data["enabled"] else TrackingMode.STOPPED
        await _client_for_target(hass, call).set_tracking_mode(int(mode))

    hass.services.async_register(
        DOMAIN,
        SERVICE_MOUNT_TRACKING,
        _service(handle_tracking),
        schema=_schema({vol.Required("enabled"): cv.boolean}),
    )

    # ── Focuser ──────────────────────────────────────────────────────────────

    async def handle_focuser_move(call: ServiceCall) -> None:
        await _client_for_target(hass, call).move_focuser(call.data["position"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_FOCUSER_MOVE,
        _service(handle_focuser_move),
        # No upper bound: the focuser's travel is per-device, and the driver
        # reports it (§ ranges are per-device, never hardcoded).
        schema=_schema({
            vol.Required("position"): vol.All(vol.Coerce(int),
                                              _bounded("Position", 0)),
        }),
    )

    async def handle_autofocus(call: ServiceCall) -> None:
        await _client_for_target(hass, call).auto_focus()

    hass.services.async_register(DOMAIN, SERVICE_FOCUSER_AUTO_FOCUS,
        _service(handle_autofocus), schema=_schema())

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def handle_filter_change(call: ServiceCall) -> None:
        await _client_for_target(hass, call).change_filter(call.data["filter_index"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_FILTERWHEEL_CHANGE,
        _service(handle_filter_change),
        schema=_schema({
            vol.Required("filter_index"): vol.All(vol.Coerce(int),
                                                  _bounded("Filter index", 0)),
        }),
    )

    # ── Guider ───────────────────────────────────────────────────────────────

    async def handle_guider_start(call: ServiceCall) -> None:
        await _client_for_target(hass, call).start_guiding(
            force_calibration=call.data["force_calibration"]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GUIDER_START,
        _service(handle_guider_start),
        schema=_schema({
            vol.Optional("force_calibration", default=False): cv.boolean,
        }),
    )

    async def handle_guider_stop(call: ServiceCall) -> None:
        await _client_for_target(hass, call).stop_guiding()

    hass.services.async_register(DOMAIN, SERVICE_GUIDER_STOP,
        _service(handle_guider_stop), schema=_schema())

    # ── Dome ─────────────────────────────────────────────────────────────────

    async def handle_dome_open(call: ServiceCall) -> None:
        await _client_for_target(hass, call).open_dome()

    hass.services.async_register(DOMAIN, SERVICE_DOME_OPEN,
        _service(handle_dome_open), schema=_schema())

    async def handle_dome_close(call: ServiceCall) -> None:
        await _client_for_target(hass, call).close_dome()

    hass.services.async_register(DOMAIN, SERVICE_DOME_CLOSE,
        _service(handle_dome_close), schema=_schema())

    async def handle_dome_park(call: ServiceCall) -> None:
        await _client_for_target(hass, call).park_dome()

    hass.services.async_register(DOMAIN, SERVICE_DOME_PARK,
        _service(handle_dome_park), schema=_schema())

    # ── Sequence ─────────────────────────────────────────────────────────────

    async def handle_seq_start(call: ServiceCall) -> None:
        await _client_for_target(hass, call).start_sequence()

    hass.services.async_register(DOMAIN, SERVICE_SEQUENCE_START,
        _service(handle_seq_start), schema=_schema())

    async def handle_seq_stop(call: ServiceCall) -> None:
        await _client_for_target(hass, call).stop_sequence()

    hass.services.async_register(DOMAIN, SERVICE_SEQUENCE_STOP,
        _service(handle_seq_stop), schema=_schema())

    async def handle_seq_load(call: ServiceCall) -> None:
        await _client_for_target(hass, call).load_sequence(call.data["sequence_name"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEQUENCE_LOAD,
        _service(handle_seq_load),
        # A NAME — the one N.I.N.A. lists under its sequence folder. 1.4.5 sent
        # a Windows path as `path`, which the API binds nothing to.
        schema=_schema({vol.Required("sequence_name"): cv.string}),
    )

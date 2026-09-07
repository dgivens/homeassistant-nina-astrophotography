"""N.I.N.A. Astrophotography integration for Home Assistant."""
from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
    Platform,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    HomeAssistantError,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.service import async_extract_config_entry_ids
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
        automation. It names the instance twice over, because the event types
        are shared and an unfiltered automation on a two-rig install fires for
        both: `entry_id` is what a template filters on, against
        `config_entry_id(<one of that rig's entities>)`, and `instance` is the
        name to put in the message it sends.
        """
        payload = {
            "event": event.name,
            "time": event.time.isoformat(),
            "instance": instance_name,
            "entry_id": entry.entry_id,
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

_TARGET_FIELDS = (ATTR_AREA_ID, ATTR_DEVICE_ID, ATTR_ENTITY_ID, ATTR_FLOOR_ID,
                  ATTR_LABEL_ID)


async def _entry_for_target(hass: HomeAssistant, call: ServiceCall) -> NinaConfigEntry:
    """Resolve which rig a call means.

    Any target form resolves: the hub device, a piece of equipment, one of its
    entities, or the area/floor/label any of those sit in. An untargeted call
    resolves to the single configured instance, which is what most installs
    have.

    Ambiguity is judged on CONFIGURED entries, not loaded ones. Judged on
    loaded entries, an untargeted call would silently retarget to the surviving
    rig whenever the other one's N.I.N.A. was down — which is exactly when
    nobody is watching.
    """
    configured = [entry for entry in hass.config_entries.async_entries(DOMAIN)
                  if not entry.disabled_by]
    # Whether a target was GIVEN, not whether it resolved: a target naming
    # something unknown must be refused, never widened back to "the only rig".
    if any(call.data.get(field) for field in _TARGET_FIELDS):
        targeted = await async_extract_config_entry_ids(call)
        configured = [entry for entry in configured if entry.entry_id in targeted]
        if not configured:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="unknown_target"
            )
    if not configured:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_instance"
        )
    if len(configured) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="ambiguous_target"
        )
    entry = configured[0]
    if entry.state is not ConfigEntryState.LOADED:
        # The device registry outlives a failed setup, so a rig whose N.I.N.A.
        # has not started yet is targetable but not commandable. Say which.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"instance": entry.title},
        )
    return entry


async def _client_for_target(hass: HomeAssistant, call: ServiceCall) -> NinaClientV2:
    """The client of the rig a call is aimed at."""
    return (await _entry_for_target(hass, call)).runtime_data.client


def _bounded(field: str, kind: type[int] | type[float], minimum: float,
             maximum: float | None = None) -> vol.All:
    """Coerce, then refuse out-of-range input as a validation error rather than
    a `vol.Invalid`.

    Out-of-range input is silently clamped and answered `Success: true`, so
    nothing downstream ever reports it, and `services.yaml`'s selectors are a
    UI hint that binds nothing from a script or the REST API.
    """
    if maximum is None:
        limits = f"{minimum} or more"
    else:
        limits = f"between {minimum} and {maximum}"

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

    return vol.All(vol.Coerce(kind), validate)


def _service(handler: Callable[[ServiceCall], Awaitable[None]]):
    """Wrap a handler so a refusal reads as a refusal.

    `NinaError` subclasses `Exception` alone — deliberately, to keep the API
    layer free of Home Assistant — so one escaping a service handler is treated
    by Home Assistant as an integration DEFECT: the automation step fails with
    a traceback and the frontend offers to file a bug. A disconnected mount is
    not a bug in this integration.
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
    resolved per call instead.
    """

    def register(
        service: str,
        handler: Callable[[ServiceCall], Awaitable[None]],
        fields: dict[Any, Any] | None = None,
    ) -> None:
        """Every action is wrapped and accepts a target; none opts out.

        The target fields are the full set Home Assistant's target picker can
        produce. Accepting only `device_id` while `services.yaml` declares a
        `target:` block makes an area-targeted call fail as an integration
        defect rather than reaching the rig.
        """
        hass.services.async_register(
            DOMAIN, service, _service(handler),
            schema=vol.Schema({**cv.TARGET_SERVICE_FIELDS, **(fields or {})}),
        )

    def register_command(
        service: str, command: Callable[[NinaClientV2], Awaitable[None]]
    ) -> None:
        """An action whose whole body is one no-argument client call."""
        async def handle(call: ServiceCall) -> None:
            await command(await _client_for_target(hass, call))

        register(service, handle)

    for service, command in (
        (SERVICE_CAMERA_ABORT_CAPTURE, NinaClientV2.abort_capture),
        (SERVICE_MOUNT_PARK, NinaClientV2.park_mount),
        (SERVICE_MOUNT_UNPARK, NinaClientV2.unpark_mount),
        (SERVICE_FOCUSER_AUTO_FOCUS, NinaClientV2.auto_focus),
        (SERVICE_GUIDER_STOP, NinaClientV2.stop_guiding),
        (SERVICE_DOME_OPEN, NinaClientV2.open_dome),
        (SERVICE_DOME_CLOSE, NinaClientV2.close_dome),
        (SERVICE_DOME_PARK, NinaClientV2.park_dome),
        (SERVICE_SEQUENCE_START, NinaClientV2.start_sequence),
        (SERVICE_SEQUENCE_STOP, NinaClientV2.stop_sequence),
    ):
        register_command(service, command)

    # ── Camera ──────────────────────────────────────────────────────────────

    async def handle_camera_cool(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.cool_camera(call.data["temperature"],
                                 minutes=call.data.get("minutes", -1))

    # `minutes` is unset by default rather than 10: the client sends -1, which
    # asks N.I.N.A. for the ramp the profile specifies for this camera.
    register(SERVICE_CAMERA_COOL, handle_camera_cool, {
        vol.Required("temperature"): vol.Coerce(float),
        vol.Optional("minutes"): _bounded("Ramp time", float, 0),
    })

    async def handle_camera_warm(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.warm_camera(minutes=call.data.get("minutes", -1))

    register(SERVICE_CAMERA_WARM, handle_camera_warm, {
        vol.Optional("minutes"): _bounded("Ramp time", float, 0),
    })

    async def handle_camera_capture(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.capture_image(call.data["duration"],
                                   gain=call.data.get("gain"),
                                   save=call.data["save"])

    # `binning` and `filter_index` are gone rather than accepted and dropped:
    # `/equipment/camera/capture` binds neither, and a parameter that looks
    # like it works is worse than no parameter.
    register(SERVICE_CAMERA_CAPTURE, handle_camera_capture, {
        vol.Required("duration"): _bounded("Duration", float, 0),
        vol.Optional("gain"): _bounded("Gain", int, 0),
        vol.Optional("save", default=False): cv.boolean,
    })

    # ── Mount ────────────────────────────────────────────────────────────────

    async def handle_mount_slew(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.slew_mount(call.data["ra_degrees"], call.data["dec_degrees"])

    # J2000 DEGREES, sent through untouched. `MountInfo` reports RA in the
    # MOUNT's epoch and in HOURS, so feeding a reported value back here is
    # wrong twice — and 22.07 is a valid figure either way, so nothing catches
    # it. Catalogues quote h:m:s; multiply hours by 15.
    register(SERVICE_MOUNT_SLEW, handle_mount_slew, {
        vol.Required("ra_degrees"): _bounded("Right ascension", float, 0, 360),
        vol.Required("dec_degrees"): _bounded("Declination", float, -90, 90),
    })

    async def handle_mount_set_tracking(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        mode = TrackingMode.SIDEREAL if call.data["enabled"] else TrackingMode.STOPPED
        await client.set_tracking_mode(int(mode))

    register(SERVICE_MOUNT_TRACKING, handle_mount_set_tracking, {
        vol.Required("enabled"): cv.boolean,
    })

    # ── Focuser ──────────────────────────────────────────────────────────────

    async def handle_focuser_move(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.move_focuser(call.data["position"])

    # No upper bound: the focuser's travel is per-device, and the driver
    # reports it.
    register(SERVICE_FOCUSER_MOVE, handle_focuser_move, {
        vol.Required("position"): _bounded("Position", int, 0),
    })

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def handle_filterwheel_change_filter(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.change_filter(call.data["filter_index"])

    register(SERVICE_FILTERWHEEL_CHANGE, handle_filterwheel_change_filter, {
        vol.Required("filter_index"): _bounded("Filter index", int, 0),
    })

    # ── Guider ───────────────────────────────────────────────────────────────

    async def handle_guider_start(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.start_guiding(force_calibration=call.data["force_calibration"])

    register(SERVICE_GUIDER_START, handle_guider_start, {
        vol.Optional("force_calibration", default=False): cv.boolean,
    })

    # ── Sequence ─────────────────────────────────────────────────────────────

    async def handle_sequence_load(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.load_sequence(call.data["sequence_name"])

    # A NAME — the one N.I.N.A. lists under its sequence folder. The endpoint
    # binds no path.
    register(SERVICE_SEQUENCE_LOAD, handle_sequence_load, {
        vol.Required("sequence_name"): cv.string,
    })

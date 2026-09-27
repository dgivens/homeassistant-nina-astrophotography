"""N.I.N.A. Astrophotography integration for Home Assistant."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import timedelta
import functools
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
    Platform,
)
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
import voluptuous as vol

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
from .frontend import (
    async_ensure_frontend_resources,
    async_register_frontend_resources,
    async_unregister_frontend_resources,
)
from .views import async_register_views

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

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, the image proxy and the Lovelace cards."""
    _register_services(hass)
    async_register_views(hass)
    await async_register_frontend_resources(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Set up N.I.N.A. from a config entry."""
    # Restores the cards if removing the last entry deleted them; `async_setup`
    # does not run again for a rig re-added without a restart.
    await async_ensure_frontend_resources(hass)

    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )
    rollover_hour = entry.options.get(CONF_ROLLOVER_HOUR, DEFAULT_ROLLOVER_HOUR)
    # Entries created before 2.0 carry no instance name; the title stands in.
    instance_name = entry.data.get(CONF_INSTANCE_NAME, entry.title)

    session = async_get_clientsession(hass)
    client = NinaClientV2(host, port, session)

    try:
        version = await client.get_versions()
    except (NinaEndpointError, NinaRequestError) as exc:
        # A path this build does not serve will not appear later.
        raise ConfigEntryError(
            f"N.I.N.A. at {host}:{port} does not serve the expected API: {exc}"
        ) from exc
    except (NinaConnectionError, NinaUnavailableError, NinaCommandError) as exc:
        # N.I.N.A. may still be booting, or connecting equipment.
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
        """Fire `nina_<event>` and the catch-all `nina_event`.

        Every rig fires the same event types, so the payload names its rig
        twice: `entry_id` for a template to filter on, against
        `config_entry_id(<one of that rig's entities>)`, and `instance` for a
        message to print.
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
            # Reseed the frames and replay /event-history for what the socket
            # missed. Setup has just done both for the first connection.
            coordinator.schedule_reconnect()
        connected_before = True

    events = NinaEventStream(
        host=host,
        port=port,
        session=session,
        rig_offset=lambda: client.rig_offset,
        on_connection=_fire_connection_event,
    )
    # Before the first refresh, which replays /event-history through the stream
    # and sets the generation it stamps on every event.
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
    # Before the socket starts: on_unload callbacks also run when a later setup
    # step fails, so the reconnect task cannot outlive a failed entry.
    entry.async_on_unload(events.stop)

    # Before the platforms: `via_device` needs the hub to exist, and equipment
    # with no entities still gets a device.
    async_sync_devices(hass, entry, coordinator.data)
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: async_sync_devices(hass, entry, coordinator.data)
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # After the platforms: `event.nina_error` subscribes in
    # `async_added_to_hass`, and replay does not re-fire, so an ERROR-* that
    # arrived before it subscribed would be lost.
    await events.start()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Unload a config entry. The socket stops via `async_on_unload`."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> None:
    """Remove the bundled Lovelace resources once no rig needs them.

    This entry is already gone from `async_entries`, so any entry left there
    is another rig still using the cards.
    """
    if hass.config_entries.async_entries(DOMAIN):
        return
    await async_unregister_frontend_resources(hass)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: NinaConfigEntry, device: DeviceEntry
) -> bool:
    """Allow deleting equipment the rig no longer reports.

    A poll never removes a device, because equipment is routinely down, so
    retiring one is the user's call. The hub, and a device the rig still
    reports, would come straight back.
    """
    try:
        kind = kind_of(entry.entry_id, device)
    except LookupError:
        # An identifier scheme nothing writes any more.
        return True
    if kind is None:
        return False
    if not hasattr(entry, "runtime_data"):
        # An unloaded entry: nothing is polling to recreate the device.
        return True
    return getattr(entry.runtime_data.coordinator.data.snapshot, kind) is None


async def _async_update_listener(hass: HomeAssistant, entry: NinaConfigEntry) -> None:
    """Reload to apply changed options."""
    await hass.config_entries.async_reload(entry.entry_id)


# ─── Service registration ─────────────────────────────────────────────────────

_TARGET_FIELDS = (
    ATTR_AREA_ID,
    ATTR_DEVICE_ID,
    ATTR_ENTITY_ID,
    ATTR_FLOOR_ID,
    ATTR_LABEL_ID,
)


async def _entry_for_target(hass: HomeAssistant, call: ServiceCall) -> NinaConfigEntry:
    """Resolve which rig a call means.

    Any target form resolves: the hub, a piece of equipment, an entity, or an
    area, floor or label holding one. An untargeted call means the only
    configured rig.

    Ambiguity is judged on configured entries, not loaded ones, so an
    untargeted call never silently retargets to one rig while the other's
    N.I.N.A. is down.
    """
    configured = [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if not entry.disabled_by
    ]
    # A target that resolves to nothing is refused, never widened to the only rig.
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
        # Its devices outlive a failed setup, so it is targetable but not
        # commandable.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"instance": entry.title},
        )
    return entry


async def _client_for_target(hass: HomeAssistant, call: ServiceCall) -> NinaClientV2:
    """The client of the rig a call is aimed at."""
    return (await _entry_for_target(hass, call)).runtime_data.client


def _bounded(
    field: str, kind: type[int | float], minimum: float, maximum: float | None = None
) -> vol.All:
    """Coerce, then refuse out-of-range input with a `ServiceValidationError`.

    N.I.N.A. silently clamps out-of-range input and answers `Success: true`,
    and `services.yaml`'s selectors bind nothing from a script.
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
                    "field": field,
                    "value": str(value),
                    "limits": limits,
                },
            )
        return value

    return vol.All(vol.Coerce(kind), validate)


def _service(handler: Callable[[ServiceCall], Awaitable[None]]):
    """Re-raise `NinaError` as `HomeAssistantError`.

    `NinaError` subclasses `Exception` alone, to keep the API layer free of
    Home Assistant, and Home Assistant reports any other exception escaping a
    handler as an integration defect.
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
    """Register every action, whether or not an entry is loaded.

    Which rig a call means is resolved per call.
    """

    def register(
        service: str,
        handler: Callable[[ServiceCall], Awaitable[None]],
        fields: dict[Any, Any] | None = None,
    ) -> None:
        """Register a wrapped action accepting every target field.

        `services.yaml` declares a `target:` block, so the picker can send an
        area, floor or label as well as a device.
        """
        hass.services.async_register(
            DOMAIN,
            service,
            _service(handler),
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
        await client.cool_camera(
            call.data["temperature"], minutes=call.data.get("minutes", -1)
        )

    # `minutes` is unset by default rather than 10: the client sends -1, which
    # asks N.I.N.A. for the ramp the profile specifies for this camera.
    register(
        SERVICE_CAMERA_COOL,
        handle_camera_cool,
        {
            vol.Required("temperature"): vol.Coerce(float),
            vol.Optional("minutes"): _bounded("Ramp time", float, 0),
        },
    )

    async def handle_camera_warm(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.warm_camera(minutes=call.data.get("minutes", -1))

    register(
        SERVICE_CAMERA_WARM,
        handle_camera_warm,
        {
            vol.Optional("minutes"): _bounded("Ramp time", float, 0),
        },
    )

    async def handle_camera_capture(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.capture_image(
            call.data["duration"], gain=call.data.get("gain"), save=call.data["save"]
        )

    # No `binning` or `filter_index`: `/equipment/camera/capture` binds neither.
    register(
        SERVICE_CAMERA_CAPTURE,
        handle_camera_capture,
        {
            vol.Required("duration"): _bounded("Duration", float, 0),
            vol.Optional("gain"): _bounded("Gain", int, 0),
            vol.Optional("save", default=False): cv.boolean,
        },
    )

    # ── Mount ────────────────────────────────────────────────────────────────

    async def handle_mount_slew(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.slew_mount(call.data["ra_degrees"], call.data["dec_degrees"])

    # J2000 degrees, sent as-is. `MountInfo` reports RA in hours and in the
    # mount's epoch, so a reported value fed back here is silently wrong twice.
    register(
        SERVICE_MOUNT_SLEW,
        handle_mount_slew,
        {
            vol.Required("ra_degrees"): _bounded("Right ascension", float, 0, 360),
            vol.Required("dec_degrees"): _bounded("Declination", float, -90, 90),
        },
    )

    async def handle_mount_set_tracking(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        mode = TrackingMode.SIDEREAL if call.data["enabled"] else TrackingMode.STOPPED
        await client.set_tracking_mode(int(mode))

    register(
        SERVICE_MOUNT_TRACKING,
        handle_mount_set_tracking,
        {
            vol.Required("enabled"): cv.boolean,
        },
    )

    # ── Focuser ──────────────────────────────────────────────────────────────

    async def handle_focuser_move(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.move_focuser(call.data["position"])

    # No upper bound: travel is per focuser.
    register(
        SERVICE_FOCUSER_MOVE,
        handle_focuser_move,
        {
            vol.Required("position"): _bounded("Position", int, 0),
        },
    )

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def handle_filterwheel_change_filter(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.change_filter(call.data["filter_index"])

    register(
        SERVICE_FILTERWHEEL_CHANGE,
        handle_filterwheel_change_filter,
        {
            vol.Required("filter_index"): _bounded("Filter index", int, 0),
        },
    )

    # ── Guider ───────────────────────────────────────────────────────────────

    async def handle_guider_start(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.start_guiding(force_calibration=call.data["force_calibration"])

    register(
        SERVICE_GUIDER_START,
        handle_guider_start,
        {
            vol.Optional("force_calibration", default=False): cv.boolean,
        },
    )

    # ── Sequence ─────────────────────────────────────────────────────────────

    async def handle_sequence_load(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.load_sequence(call.data["sequence_name"])

    # A name N.I.N.A. lists from its sequence folder; the endpoint binds no path.
    register(
        SERVICE_SEQUENCE_LOAD,
        handle_sequence_load,
        {
            vol.Required("sequence_name"): cv.string,
        },
    )

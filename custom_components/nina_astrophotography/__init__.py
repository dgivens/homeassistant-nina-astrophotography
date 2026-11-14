"""N.I.N.A. Astrophotography integration for Home Assistant."""

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import timedelta
import functools
import logging
import math
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
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.service import async_extract_config_entry_ids
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from . import binary_sensor, button, light, number, sensor, switch
from .api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from .api.models import NinaEvent
from .api.v2 import NinaClientV2, NinaEventStream
from .blueprint_sync import async_install_blueprints, async_track_imported_copies
from .const import (
    CAMERA_SETPOINT_RANGE,
    CONF_HOST,
    CONF_INSTANCE_NAME,
    CONF_OUTAGE_GRACE,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_ROLLOVER_HOUR,
    DEFAULT_OUTAGE_GRACE,
    DEFAULT_ROLLOVER_HOUR,
    DOMAIN,
    POLL_INTERVAL,
    SERVICE_CAMERA_ABORT_CAPTURE,
    SERVICE_CAMERA_CAPTURE,
    SERVICE_CAMERA_COOL,
    SERVICE_CAMERA_WARM,
    SERVICE_DOME_CLOSE,
    SERVICE_DOME_OPEN,
    SERVICE_DOME_PARK,
    SERVICE_FILTERWHEEL_CHANGE,
    SERVICE_FLAT_PANEL_SET_BRIGHTNESS,
    SERVICE_FLAT_PANEL_SET_COVER,
    SERVICE_FLAT_PANEL_SET_LIGHT,
    SERVICE_FOCUSER_AUTO_FOCUS,
    SERVICE_FOCUSER_MOVE,
    SERVICE_GUIDER_START,
    SERVICE_GUIDER_STOP,
    SERVICE_MOUNT_PARK,
    SERVICE_MOUNT_SLEW,
    SERVICE_MOUNT_TRACKING,
    SERVICE_MOUNT_UNPARK,
    SERVICE_ROTATOR_MOVE,
    SERVICE_ROTATOR_MOVE_MECHANICAL,
    SERVICE_SEQUENCE_LOAD,
    SERVICE_SEQUENCE_START,
    SERVICE_SEQUENCE_STOP,
    TrackingMode,
    normalize_host,
)
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData, NinaRuntimeData
from .device import (
    async_sync_devices,
    kind_of,
    raise_outside_rotator_range,
    refused_while_unsafe,
    refused_while_unsynced,
)
from .entity import NinaEntityDescription, refusals_raised, usable
from .frontend import (
    async_ensure_frontend_resources,
    async_register_frontend_resources,
    async_serve_cards,
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

# Every dome entity that ships enabled; `_enable_dome_rows` enables its row.
_DOME_ENABLED: tuple[tuple[Platform, NinaEntityDescription], ...] = tuple(
    (platform, description)
    for platform, descriptions in (
        (Platform.BINARY_SENSOR, binary_sensor.DESCRIPTIONS),
        (Platform.BUTTON, button.DESCRIPTIONS),
        (Platform.NUMBER, number.DESCRIPTIONS),
        (Platform.SENSOR, sensor.DESCRIPTIONS),
        (Platform.SWITCH, switch.DESCRIPTIONS),
    )
    for description in descriptions
    if description.kind == "dome" and description.entity_registry_enabled_default
)

# The rotator rows minor version 4 enables, by unique id suffix.
_ROTATOR_ENABLED = (
    (Platform.BINARY_SENSOR, "rotator_synced"),
    (Platform.NUMBER, "rotator_mechanical_position"),
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the actions, the image proxy and the Lovelace cards, and
    install the blueprints.
    """
    _register_services(hass)
    async_register_views(hass)
    await async_serve_cards(hass)
    await async_register_frontend_resources(hass)
    await async_install_blueprints(hass)
    await async_track_imported_copies(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Set up N.I.N.A. from a config entry."""
    # Restores the cards if removing the last entry deleted them; `async_setup`
    # does not run again for a rig re-added without a restart.
    await async_ensure_frontend_resources(hass)

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    instance_name = entry.data[CONF_INSTANCE_NAME]
    rollover_hour = entry.options.get(CONF_ROLLOVER_HOUR, DEFAULT_ROLLOVER_HOUR)
    outage_grace = entry.options.get(CONF_OUTAGE_GRACE, DEFAULT_OUTAGE_GRACE)

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
        update_interval=POLL_INTERVAL,
        version=version,
        rollover_hour=rollover_hour,
        outage_grace=timedelta(seconds=outage_grace),
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
        coordinator.socket_changed(connected)
        hass.bus.async_fire(
            "nina_websocket_connected" if connected else "nina_websocket_disconnected",
            {"instance": instance_name, "entry_id": entry.entry_id},
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
        generation=lambda: coordinator.generation,
        rig_offset=lambda: client.rig_offset,
        on_connection=_fire_connection_event,
    )
    events.subscribe(coordinator.handle_event)
    events.subscribe(_fire_bus_event)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = NinaRuntimeData(
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
    # Before the platforms too, so an enabled row's entity is created at setup;
    # and on every publish, for a dome N.I.N.A. connects later.
    _enable_dome_rows(hass, entry, coordinator.data)
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: async_sync_devices(hass, entry, coordinator.data)
        )
    )
    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: _enable_dome_rows(hass, entry, coordinator.data)
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # After the platforms: `event.nina_error` subscribes in
    # `async_added_to_hass`, and replay does not re-fire, so an ERROR-* that
    # arrived before it subscribed would be lost.
    await events.start()
    return True


async def async_migrate_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Bring an entry from an earlier minor version up to the current one.

    Minor 2 drops the poll interval, which is fixed, from `data` and
    `options` alike. An entry from before 2.0 has no instance name, and its
    title stands in.

    Minor 3 drops the unique id, which was the address. The duplicate guard
    compares host and port in `data` instead, so the host is normalised the
    way the config flow stores it.

    Minor 4 enables the rotator rows the observatory card reads, which earlier
    versions registered disabled. Only rows the integration disabled, and not
    on an entry whose system options disable new entities, which Home
    Assistant records the same way: a row a user disabled is left alone.
    Home Assistant reloads the entry 30 s after a row is enabled.
    """
    if entry.version == 1 and entry.minor_version < 2:
        data = {k: v for k, v in entry.data.items() if k != CONF_POLL_INTERVAL}
        options = {k: v for k, v in entry.options.items() if k != CONF_POLL_INTERVAL}
        data.setdefault(CONF_INSTANCE_NAME, entry.title)
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, minor_version=2
        )
    if entry.version == 1 and entry.minor_version < 3:
        hass.config_entries.async_update_entry(
            entry,
            data={**entry.data, CONF_HOST: normalize_host(entry.data[CONF_HOST])},
            unique_id=None,
            minor_version=3,
        )
    if entry.version == 1 and entry.minor_version < 4:
        if not entry.pref_disable_new_entities:
            registry = er.async_get(hass)
            for platform, key in _ROTATOR_ENABLED:
                entity_id = registry.async_get_entity_id(
                    platform, DOMAIN, f"{entry.entry_id}_{key}"
                )
                row = registry.async_get(entity_id) if entity_id else None
                if row and row.disabled_by is er.RegistryEntryDisabler.INTEGRATION:
                    registry.async_update_entity(row.entity_id, disabled_by=None)
        hass.config_entries.async_update_entry(entry, minor_version=4)
    return True


def _enable_dome_rows(
    hass: HomeAssistant, entry: NinaConfigEntry, data: NinaData
) -> None:
    """Enable the dome rows 2.0.0 registered disabled, once the dome reports the
    capability each needs: a roll-off roof's park row stays as it is.

    Only rows the integration disabled, and not on an entry whose system
    options disable new entities, which Home Assistant records the same way. A
    row a user disabled is left alone. Home Assistant reloads the entry 30 s
    after a row is enabled, which creates an entity enabled after setup; the
    rows are enabled by then, so it happens once.
    """
    if entry.pref_disable_new_entities:
        return
    registry = er.async_get(hass)
    for platform, description in _DOME_ENABLED:
        unique_id = (
            f"{entry.entry_id}_{description.unique_id_suffix or description.key}"
        )
        entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
        row = registry.async_get(entity_id) if entity_id else None
        if (
            row is not None
            and row.disabled_by is er.RegistryEntryDisabler.INTEGRATION
            and usable(data, description)
        ):
            registry.async_update_entity(row.entity_id, disabled_by=None)


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
        # An identifier this integration does not write: nothing recreates it.
        return True
    if kind is None:
        return False
    if not hasattr(entry, "runtime_data"):
        # An unloaded entry: nothing is polling to recreate the device.
        return True
    return getattr(entry.runtime_data.coordinator.data.snapshot, kind) is None


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
    return (await _entry_for_target(hass, call)).runtime_data.coordinator.client


def _format(value: float) -> str:
    """A number as written, unrounded: `2000`, not `2000.0` or `2e+03`."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return str(value)


def _limits(minimum: float | None, maximum: float | None) -> str:
    if maximum is None:
        return f"{_format(minimum or 0)} or more"
    if minimum is None:
        return f"{_format(maximum)} or less"
    return f"between {_format(minimum)} and {_format(maximum)}"


def _bounded(
    field: str, kind: type[int | float], minimum: float, maximum: float | None = None
) -> vol.All:
    """Coerce, then refuse out-of-range input with a `ServiceValidationError`.

    N.I.N.A. silently clamps out-of-range input and answers `Success: true`,
    and `services.yaml`'s selectors bind nothing from a script.
    """

    def validate(value: float) -> float:
        if value < minimum or (maximum is not None and value > maximum):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="out_of_range",
                translation_placeholders={
                    "field": field,
                    "value": _format(value),
                    "limits": _limits(minimum, maximum),
                },
            )
        return value

    return vol.All(vol.Coerce(kind), validate)


def _within_device_range(
    field: str,
    value: float,
    device: str,
    minimum: float | None,
    maximum: float | None,
) -> None:
    """Refuse a value outside the limits the device itself reports.

    A device reporting no range, or not connected, leaves the value to
    N.I.N.A., which refuses a command to a disconnected device itself.
    """
    if (minimum is None or value >= minimum) and (maximum is None or value <= maximum):
        return
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="outside_device_range",
        translation_placeholders={
            "field": field,
            "value": _format(value),
            "device": device,
            "limits": _limits(minimum, maximum),
        },
    )


def _service(handler: Callable[[ServiceCall], Awaitable[None]]):
    """Re-raise `NinaError` as `HomeAssistantError`."""

    @functools.wraps(handler)
    async def wrapped(call: ServiceCall) -> None:
        with refusals_raised():
            await handler(call)

    return wrapped


def _refuse_unsupported(supported: bool | None, feature: str) -> None:
    """Refuse a command for a feature the connected panel reports it lacks.

    A disconnected panel reports every capability false, so only an
    explicit false from a connected one is believed.
    """
    if supported is False:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="flat_panel_unsupported",
            translation_placeholders={"feature": feature},
        )


async def _handle_flat_panel_set_cover(call: ServiceCall) -> None:
    coordinator = (await _entry_for_target(call.hass, call)).runtime_data.coordinator
    panel = coordinator.data.snapshot.flat_device
    if panel is not None and panel.connected:
        _refuse_unsupported(panel.supports_open_close, "cover")
    if call.data["open"]:
        await coordinator.client.open_flat_cover()
    else:
        await coordinator.client.close_flat_cover()


async def _handle_flat_panel_set_light(call: ServiceCall) -> None:
    """Switch the light, sending a brightness before every switch on.

    A bare `set-light?on=true` lights the panel at the level N.I.N.A. last set
    in this process, or at `MaxBrightness` when it has set none; so switching on
    a panel reporting no range is refused rather than sent. An ASCOM panel off
    reports brightness 0, so the level kept is only a lit panel's own.
    `light.async_light_at` says when the `set-light` follows.
    """
    coordinator = (await _entry_for_target(call.hass, call)).runtime_data.coordinator
    client, panel = coordinator.client, coordinator.data.snapshot.flat_device
    requested = call.data.get("brightness")
    if panel is not None and panel.connected:
        _refuse_unsupported(panel.supports_on_off, "light")
    if not call.data["light_on"]:
        if requested is not None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="flat_panel_brightness_while_off",
            )
        await client.set_flat_light(False)
        return
    if panel is None or panel.brightness_range is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="flat_panel_no_range"
        )
    low, high = panel.brightness_range
    if requested is not None:
        # Above the minimum: an ASCOM panel at 0 is dark, and the set-light
        # after it lights the panel at MaxBrightness.
        _within_device_range(
            "Brightness", requested, "flat panel", math.floor(low) + 1, high
        )
        level = requested
    elif panel.light_on and panel.brightness is not None and panel.brightness > low:
        level = round(panel.brightness)
    else:
        level = light.dimmest_level((low, high))
    await light.async_light_at(client, level)


async def _handle_flat_panel_set_brightness(call: ServiceCall) -> None:
    """Set a level within the panel's range, refusing a panel reporting none.

    An ASCOM panel lights at any level above 0 and N.I.N.A. clamps to
    `MaxBrightness`, so a level sent to a panel whose range is unknown, or that
    connects before the next poll, could light it at full output.
    """
    coordinator = (await _entry_for_target(call.hass, call)).runtime_data.coordinator
    level = call.data["level"]
    panel = coordinator.data.snapshot.flat_device
    if panel is None or panel.brightness_range is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="flat_panel_no_range"
        )
    _within_device_range("Level", level, "flat panel", *panel.brightness_range)
    await coordinator.client.set_flat_brightness(level)


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

        `services.yaml`'s `target:` filters on this integration's entities,
        since hassfest refuses a device filter there; the picker then offers
        only the devices, areas, floors and labels holding one. A target
        field sent in `data` rather than `target` binds the same.
        """
        hass.services.async_register(
            DOMAIN,
            service,
            _service(handler),
            # Home Assistant 2026.10 annotates a schema as probatio's, which
            # stands in for voluptuous at runtime; 2026.9 imports only voluptuous.
            schema=vol.Schema({**cv.TARGET_SERVICE_FIELDS, **(fields or {})}),  # pyright: ignore[reportArgumentType]
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
        (SERVICE_DOME_CLOSE, NinaClientV2.close_dome),
        (SERVICE_DOME_PARK, NinaClientV2.park_dome),
        (SERVICE_SEQUENCE_START, NinaClientV2.start_sequence),
        (SERVICE_SEQUENCE_STOP, NinaClientV2.stop_sequence),
    ):
        register_command(service, command)

    async def handle_dome_open(call: ServiceCall) -> None:
        entry = await _entry_for_target(hass, call)
        coordinator = entry.runtime_data.coordinator
        if (key := refused_while_unsafe(coordinator.data)) is not None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=key)
        await coordinator.client.open_dome()

    register(SERVICE_DOME_OPEN, handle_dome_open)

    # ── Camera ──────────────────────────────────────────────────────────────

    async def handle_camera_cool(call: ServiceCall) -> None:
        client = await _client_for_target(hass, call)
        await client.cool_camera(
            call.data["temperature"], minutes=call.data.get("minutes", -1)
        )

    # `minutes` has no default: the client then sends -1, which asks N.I.N.A.
    # for the ramp the profile specifies for this camera. `minutes` is a
    # minimum, so it has no ceiling. No setpoint range reaches the wire, so the
    # temperature bounds are the target temperature number's.
    register(
        SERVICE_CAMERA_COOL,
        handle_camera_cool,
        {
            vol.Required("temperature"): _bounded(
                "Target temperature", float, *CAMERA_SETPOINT_RANGE
            ),
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
        coordinator = (await _entry_for_target(hass, call)).runtime_data.coordinator
        duration, gain = call.data["duration"], call.data.get("gain")
        if gain is not None and gain < 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="gain_not_settable",
                translation_placeholders={"value": str(gain)},
            )
        camera = coordinator.data.snapshot.camera
        if camera is not None and camera.exposure_range is not None:
            # Held to the maximum alone: a 0 s exposure is a bias frame, which
            # a driver may take below its `ExposureMin`.
            maximum = camera.exposure_range[1]
            _within_device_range("Duration", duration, "camera", None, maximum)
        if camera is not None and camera.gain_range is not None and gain is not None:
            low, high = camera.gain_range
            _within_device_range("Gain", gain, "camera", max(low, 1), high)
        await coordinator.client.capture_image(
            duration, gain=gain, save=call.data["save"]
        )

    # No `binning` or `filter_index`: `/equipment/camera/capture` binds neither.
    # The API applies only a gain above 0, so a lower one is refused rather
    # than replaced by the camera's default.
    register(
        SERVICE_CAMERA_CAPTURE,
        handle_camera_capture,
        {
            vol.Required("duration"): _bounded("Duration", float, 0),
            vol.Optional("gain"): vol.Coerce(int),
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

    # No ceiling: travel is per focuser, and no `MaxStep` reaches the wire.
    register(
        SERVICE_FOCUSER_MOVE,
        handle_focuser_move,
        {
            vol.Required("position"): _bounded("Position", int, 0),
        },
    )

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def handle_filterwheel_change_filter(call: ServiceCall) -> None:
        coordinator = (await _entry_for_target(hass, call)).runtime_data.coordinator
        index = call.data["filter_index"]
        wheel = coordinator.data.snapshot.filter_wheel
        # Slots are the wheel's own `Id`s, which need not run 0..n-1.
        slots = sorted(wheel.filter_ids) if wheel else []
        if wheel is not None and wheel.connected and slots and index not in slots:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_filter_slot",
                translation_placeholders={
                    "value": str(index),
                    "slots": ", ".join(map(str, slots)),
                },
            )
        await coordinator.client.change_filter(index)

    register(
        SERVICE_FILTERWHEEL_CHANGE,
        handle_filterwheel_change_filter,
        {
            vol.Required("filter_index"): _bounded("Filter index", int, 0),
        },
    )

    # ── Flat panel ───────────────────────────────────────────────────────────

    register(
        SERVICE_FLAT_PANEL_SET_COVER,
        _handle_flat_panel_set_cover,
        {
            vol.Required("open"): cv.boolean,
        },
    )

    register(
        SERVICE_FLAT_PANEL_SET_LIGHT,
        _handle_flat_panel_set_light,
        {
            vol.Required("light_on"): cv.boolean,
            vol.Optional("brightness"): _bounded("Brightness", int, 0),
        },
    )

    # Driver units, within the panel's own `MinBrightness`–`MaxBrightness`. An
    # ASCOM panel lights at any level above 0; a native driver keeps the light
    # as it is.
    register(
        SERVICE_FLAT_PANEL_SET_BRIGHTNESS,
        _handle_flat_panel_set_brightness,
        {
            vol.Required("level"): _bounded("Level", int, 0),
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

    # ── Rotator ──────────────────────────────────────────────────────────────

    async def handle_rotator_move(call: ServiceCall) -> None:
        coordinator = (await _entry_for_target(hass, call)).runtime_data.coordinator
        if (key := refused_while_unsynced(coordinator.data)) is not None:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key=key)
        await coordinator.client.move_rotator(call.data["position"])

    # Not held to the profile's range: N.I.N.A. folds a sky angle into it, which
    # on a half range is the same framing flipped.
    register(
        SERVICE_ROTATOR_MOVE,
        handle_rotator_move,
        {vol.Required("position"): _bounded("Position", float, 0, 360)},
    )

    async def handle_rotator_move_mechanical(call: ServiceCall) -> None:
        coordinator = (await _entry_for_target(hass, call)).runtime_data.coordinator
        raise_outside_rotator_range(coordinator.data, call.data["position"])
        await coordinator.client.move_rotator_mechanical(call.data["position"])

    register(
        SERVICE_ROTATOR_MOVE_MECHANICAL,
        handle_rotator_move_mechanical,
        {vol.Required("position"): _bounded("Position", float, 0, 360)},
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

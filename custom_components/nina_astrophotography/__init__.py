"""N.I.N.A. Astrophotography integration for Home Assistant."""
from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import timedelta

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import (
    ConfigEntryError,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from .api.models import NinaEvent
from .api.v2 import NinaClientV2, NinaEventStream
from .legacy_api import NinaApiClient
from .frame_statistics import NinaFrameStatisticsStore
from .const import (
    CONF_API_VERSION,
    CONF_HOST,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DEFAULT_API_VERSION,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_PORT,
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
)
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaRuntimeData

_LOGGER = logging.getLogger(__name__)

# A platform is registered only once it reads NinaData: Home Assistant imports
# every listed platform module during entry setup, so listing one that still
# speaks the 1.4.x coordinator fails the entry. Each remaining platform is
# re-added by the phase-C PR that migrates it; until then it stays on disk,
# unregistered.
PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Set up N.I.N.A. from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)
    api_version = entry.data.get(CONF_API_VERSION, DEFAULT_API_VERSION)
    poll_interval = entry.options.get(
        CONF_POLL_INTERVAL,
        entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
    )

    session = async_get_clientsession(hass)
    client = NinaClientV2(host, port, session)
    # The unmigrated services still speak 1.4.x; phase D retires this client.
    service_client = NinaApiClient(
        host=host, port=port, api_version=api_version, session=session
    )

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
    )
    await coordinator.async_config_entry_first_refresh()

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

    def _fire_connection_event(connected: bool) -> None:
        hass.bus.async_fire(
            "nina_websocket_connected" if connected else "nina_websocket_disconnected",
            {},
        )

    events = NinaEventStream(
        host=host,
        port=port,
        session=session,
        rig_offset=lambda: client.rig_offset,
        on_connection=_fire_connection_event,
    )
    # B4 keeps this current from the poll; at setup the first refresh has
    # already read /application-start.
    events.generation = coordinator.generation
    events.subscribe(coordinator.handle_event)
    events.subscribe(_fire_bus_event)

    # No longer fed: its only consumer, frame_stats_sensor.py, is unregistered
    # and B4 deletes both.
    frame_store = NinaFrameStatisticsStore()

    entry.runtime_data = NinaRuntimeData(
        client=client,
        coordinator=coordinator,
        service_client=service_client,
        instance_name=entry.title,
        events=events,
        frame_store=frame_store,
    )
    # Registered before the socket starts: on_unload callbacks also run when a
    # later setup step fails, which is what keeps the reconnect task from
    # outliving a failed entry.
    entry.async_on_unload(events.stop)
    await events.start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NinaConfigEntry) -> bool:
    """Unload a config entry. The socket stops via `async_on_unload`."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: NinaConfigEntry) -> None:
    """Handle options update — reload to apply new poll interval."""
    await hass.config_entries.async_reload(entry.entry_id)


# ─── Service registration ─────────────────────────────────────────────────────

def _get_client(hass: HomeAssistant) -> NinaApiClient:
    """Return the first loaded entry's service client.

    Still "first entry wins" — phase D replaces this with device targeting.
    What changes here is only where the client is stored.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data.service_client
    raise ServiceValidationError("No N.I.N.A. instance is configured")


def _register_services(hass: HomeAssistant) -> None:
    """Register all HA services for N.I.N.A. control."""

    # ── Camera ──────────────────────────────────────────────────────────────

    async def handle_camera_cool(call: ServiceCall) -> None:
        temperature = call.data["temperature"]
        minutes = call.data.get("minutes", 10)
        await _get_client(hass).cool_camera(temperature, minutes)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAMERA_COOL,
        handle_camera_cool,
        schema=vol.Schema(
            {
                vol.Required("temperature"): vol.Coerce(float),
                vol.Optional("minutes", default=10): vol.Coerce(float),
            }
        ),
    )

    async def handle_camera_warm(call: ServiceCall) -> None:
        minutes = call.data.get("minutes", 10)
        await _get_client(hass).warm_camera(minutes)

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAMERA_WARM,
        handle_camera_warm,
        schema=vol.Schema({vol.Optional("minutes", default=10): vol.Coerce(float)}),
    )

    async def handle_capture(call: ServiceCall) -> None:
        await _get_client(hass).capture_image(
            exposure=call.data["exposure"],
            gain=call.data.get("gain"),
            filter_index=call.data.get("filter_index"),
            binning=call.data.get("binning", 1),
            save=call.data.get("save", False),
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_CAMERA_CAPTURE,
        handle_capture,
        schema=vol.Schema(
            {
                vol.Required("exposure"): vol.Coerce(float),
                vol.Optional("gain"): vol.Coerce(int),
                vol.Optional("filter_index"): vol.Coerce(int),
                vol.Optional("binning", default=1): vol.All(int, vol.Range(min=1, max=4)),
                vol.Optional("save", default=False): cv.boolean,
            }
        ),
    )

    async def handle_abort_capture(call: ServiceCall) -> None:
        await _get_client(hass).abort_capture()

    hass.services.async_register(DOMAIN, SERVICE_CAMERA_ABORT_CAPTURE, handle_abort_capture)

    # ── Mount ────────────────────────────────────────────────────────────────

    async def handle_slew(call: ServiceCall) -> None:
        await _get_client(hass).slew_mount(
            ra_hours=call.data["ra"], dec=call.data["dec"]
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_MOUNT_SLEW,
        handle_slew,
        schema=vol.Schema(
            {
                vol.Required("ra"): vol.Coerce(float),
                vol.Required("dec"): vol.Coerce(float),
            }
        ),
    )

    async def handle_park(call: ServiceCall) -> None:
        await _get_client(hass).park_mount()

    hass.services.async_register(DOMAIN, SERVICE_MOUNT_PARK, handle_park)

    async def handle_unpark(call: ServiceCall) -> None:
        await _get_client(hass).unpark_mount()

    hass.services.async_register(DOMAIN, SERVICE_MOUNT_UNPARK, handle_unpark)

    async def handle_tracking(call: ServiceCall) -> None:
        await _get_client(hass).set_tracking(call.data["enabled"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_MOUNT_TRACKING,
        handle_tracking,
        schema=vol.Schema({vol.Required("enabled"): cv.boolean}),
    )

    # ── Focuser ──────────────────────────────────────────────────────────────

    async def handle_focuser_move(call: ServiceCall) -> None:
        await _get_client(hass).move_focuser(call.data["position"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_FOCUSER_MOVE,
        handle_focuser_move,
        schema=vol.Schema({vol.Required("position"): vol.Coerce(int)}),
    )

    async def handle_autofocus(call: ServiceCall) -> None:
        await _get_client(hass).auto_focus()

    hass.services.async_register(DOMAIN, SERVICE_FOCUSER_AUTO_FOCUS, handle_autofocus)

    # ── Filter Wheel ─────────────────────────────────────────────────────────

    async def handle_filter_change(call: ServiceCall) -> None:
        await _get_client(hass).change_filter(call.data["filter_index"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_FILTERWHEEL_CHANGE,
        handle_filter_change,
        schema=vol.Schema({vol.Required("filter_index"): vol.Coerce(int)}),
    )

    # ── Guider ───────────────────────────────────────────────────────────────

    async def handle_guider_start(call: ServiceCall) -> None:
        force_cal = call.data.get("force_calibration", False)
        await _get_client(hass).start_guiding(force_calibration=force_cal)

    hass.services.async_register(
        DOMAIN,
        SERVICE_GUIDER_START,
        handle_guider_start,
        schema=vol.Schema(
            {vol.Optional("force_calibration", default=False): cv.boolean}
        ),
    )

    async def handle_guider_stop(call: ServiceCall) -> None:
        await _get_client(hass).stop_guiding()

    hass.services.async_register(DOMAIN, SERVICE_GUIDER_STOP, handle_guider_stop)

    # ── Dome ─────────────────────────────────────────────────────────────────

    async def handle_dome_open(call: ServiceCall) -> None:
        await _get_client(hass).open_dome()

    hass.services.async_register(DOMAIN, SERVICE_DOME_OPEN, handle_dome_open)

    async def handle_dome_close(call: ServiceCall) -> None:
        await _get_client(hass).close_dome()

    hass.services.async_register(DOMAIN, SERVICE_DOME_CLOSE, handle_dome_close)

    async def handle_dome_park(call: ServiceCall) -> None:
        await _get_client(hass).park_dome()

    hass.services.async_register(DOMAIN, SERVICE_DOME_PARK, handle_dome_park)

    # ── Sequence ─────────────────────────────────────────────────────────────

    async def handle_seq_start(call: ServiceCall) -> None:
        await _get_client(hass).start_sequence()

    hass.services.async_register(DOMAIN, SERVICE_SEQUENCE_START, handle_seq_start)

    async def handle_seq_stop(call: ServiceCall) -> None:
        await _get_client(hass).stop_sequence()

    hass.services.async_register(DOMAIN, SERVICE_SEQUENCE_STOP, handle_seq_stop)

    async def handle_seq_load(call: ServiceCall) -> None:
        await _get_client(hass).load_sequence(call.data["path"])

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEQUENCE_LOAD,
        handle_seq_load,
        schema=vol.Schema({vol.Required("path"): cv.string}),
    )

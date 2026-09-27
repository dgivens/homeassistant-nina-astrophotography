"""`event.nina_error`: failures that are occurrences, not conditions.

**Best-effort.** The plugin scrapes `ERROR-*` events from N.I.N.A.'s log:
`ERROR-PLATESOLVE` matches ASTAP only, and `ERROR-AF` never fires, so the
autofocus arm is the fold's timeout verdict instead. `CAMERA-DOWNLOAD-TIMEOUT`
is named from the plugin's source and never yet captured.
"""

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import NinaEvent
from .coordinator import NinaConfigEntry, NinaCoordinator
from .entity import NinaEntity

PARALLEL_UPDATES = 0

PLATESOLVE_FAILED = "platesolve_failed"
CAMERA_DOWNLOAD_TIMEOUT = "camera_download_timeout"
AUTOFOCUS_TIMEOUT = "autofocus_timeout"

# The wire's event name → the event type this entity fires.
_FROM_SOCKET = {
    "ERROR-PLATESOLVE": PLATESOLVE_FAILED,
    "CAMERA-DOWNLOAD-TIMEOUT": CAMERA_DOWNLOAD_TIMEOUT,
}

DESCRIPTION = EventEntityDescription(
    key="nina_error",
    translation_key="nina_error",
    entity_category=EntityCategory.DIAGNOSTIC,
    event_types=[PLATESOLVE_FAILED, CAMERA_DOWNLOAD_TIMEOUT, AUTOFOCUS_TIMEOUT],
)


class NinaErrorEvent(NinaEntity, EventEntity):
    """One entity for three failures, on the hub.

    Plate-solve and download failures arrive on the socket, so it subscribes
    to the stream. An autofocus timeout is an absence, so it watches the
    fold's verdict for its rising edge.
    """

    entity_description = DESCRIPTION

    def __init__(self, coordinator: NinaCoordinator, entry: NinaConfigEntry) -> None:
        super().__init__(coordinator, entry, DESCRIPTION.key)
        self._entry = entry
        # A failure from before Home Assistant started does not fire.
        self._autofocus_failed = coordinator.data.session.autofocus.failed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._entry.runtime_data.events.subscribe(self._pushed))

    @callback
    def _pushed(self, event: NinaEvent) -> None:
        """Fire on a live socket event; replay does not reach subscribers."""
        event_type = _FROM_SOCKET.get(event.name)
        if event_type is None:
            return
        self._trigger_event(event_type)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Fire on the rising edge of the fold's autofocus timeout verdict."""
        failed = self.coordinator.data.session.autofocus.failed
        if failed and not self._autofocus_failed:
            self._trigger_event(AUTOFOCUS_TIMEOUT)
        self._autofocus_failed = failed
        super()._handle_coordinator_update()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([NinaErrorEvent(entry.runtime_data.coordinator, entry)])

"""`event.nina_error`: the failures N.I.N.A. reports and nothing holds.

An `event` entity rather than a `sensor`, because these are discrete
occurrences with no state between them: a plate solve that failed twenty
minutes ago is not a condition the rig is still in, and a sensor holding the
last one forever would read like one.

**Best-effort and solver-specific** (§3.4). The `ERROR-*` events are scraped out
of N.I.N.A.'s log with regexes: `ERROR-PLATESOLVE` matches ASTAP only, so a rig
solving with PlateSolve2 or Pinpoint fires nothing, and `ERROR-AF` appears dead
in the plugin — which is why the autofocus arm here is the fold's own timeout
verdict rather than an event.

`CAMERA-DOWNLOAD-TIMEOUT` is named from the plugin's source and has never
appeared in a capture. It costs one table row and fires nothing if the name is
wrong.
"""
from __future__ import annotations

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import NinaEvent
from .coordinator import NinaConfigEntry, NinaCoordinator
from .entity import NinaEntity

# Read-only: nothing here commands the rig.
PARALLEL_UPDATES = 0

PLATESOLVE_FAILED = "platesolve_failed"
CAMERA_DOWNLOAD_TIMEOUT = "camera_download_timeout"
AUTOFOCUS_TIMEOUT = "autofocus_timeout"

# The wire's event name → the type this entity publishes. Home Assistant's
# event types are the automation's vocabulary, so they are ours rather than
# N.I.N.A.'s.
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

    Two arms, because the two kinds of failure are reported differently. The
    solver and download timeouts arrive as socket events, so this subscribes to
    the stream directly (Bronze `entity-event-setup`) rather than waiting for a
    publish. The autofocus timeout is an ABSENCE — a start with no finish — so
    there is no event to subscribe to and the fold's verdict is watched for its
    rising edge instead.
    """

    entity_description = DESCRIPTION

    def __init__(
        self, coordinator: NinaCoordinator, entry: NinaConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, DESCRIPTION.key)
        self._entry = entry
        # Seeded from the first published fold, so a failure that happened
        # before Home Assistant started is history rather than a fresh alarm.
        self._autofocus_failed = coordinator.data.session.autofocus.failed

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._entry.runtime_data.events.subscribe(self._pushed))

    @callback
    def _pushed(self, event: NinaEvent) -> None:
        """Fire on a socket event this entity publishes a type for.

        Live pushes only: `/event-history` replay folds into the coordinator
        without reaching subscribers, so a restart does not re-fire the night's
        failures at whatever automations are listening.
        """
        event_type = _FROM_SOCKET.get(event.name)
        if event_type is None:
            return
        self._trigger_event(event_type)
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """The autofocus arm: the rising edge of the fold's timeout verdict.

        The edge, not the level — the verdict stays true until the next run
        finishes, and firing once per publish would be hundreds of events a
        night.
        """
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

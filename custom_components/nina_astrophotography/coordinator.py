"""The single DataUpdateCoordinator.

It owns the accumulated frame and event set. session.py is stateless and
receives that set as an argument.

All mutation happens on the event loop, and NinaData is assembled from the live
set at the moment of publication with no `await` between reading the set and
freezing the dataclass. Four writers touch it — the poll, the WebSocket
callback, /event-history replay and the restart reseed — and without that rule a
poll awaiting /equipment/info while IMAGE-SAVE arrives publishes a snapshot
assembled from a pre-event read, so the frame appears, vanishes and reappears.

The polling decisions themselves — is this a restart, does the invariant hold —
live in `polling.py`, which knows nothing of Home Assistant. This module is the
I/O and the ownership.

Polling runs in six tiers behind ONE 10 s tick, not three coordinators: the
per-tier due-time checks live inside `_async_update_data`.

    fast       7,420 B @ 10 s  =  44,520 B/min
    sequence   8,418 B @ 30 s  =  16,836 B/min
                                  ──────────
                                  61,356 B/min ~ 3.7 MB/h ~ 37 MB / 10 h night
    before                        82,606 B x 6/min ~ 297 MB / night
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.errors import NinaEndpointError, NinaError, NinaRequestError
from .api.models import (
    EquipmentSnapshot,
    FlatsStatus,
    Frame,
    LivestackStatus,
    NinaEvent,
    ProfileSettings,
    SequenceNode,
    SessionStats,
    VersionInfo,
)
from .api.v2 import NinaClientV2
from .const import CONF_HOST, DEFAULT_ROLLOVER_HOUR
from .device import KINDS
from .polling import (
    EventLedger,
    ReseedGuard,
    RestartDetector,
    TierSchedule,
    imaging,
)
from .session import DEFAULT_AUTOFOCUS_TIMEOUT, fold

if TYPE_CHECKING:
    from .api.v2.events import NinaEventStream
    from .legacy_api import NinaApiClient

_LOGGER = logging.getLogger(__name__)

FAST_INTERVAL = timedelta(seconds=10)

# endpoint -> (the attribute the model is stored on, the client getter).
# `/equipment/focuser/last-af` is deliberately absent: phase C adds its model,
# and there is nothing to store until then.
_TIER_READS: dict[str, tuple[str, str]] = {
    "/sequence/json": ("_sequence", "get_sequence"),
    "/flats/status": ("_flats", "get_flats"),
    "/livestack/status": ("_livestack", "get_livestack"),
    "/profile/show": ("_profile", "get_profile"),
}

# The floor backstops the event-driven set. `/flats/status` has no event at
# all — the FLAT-* events are panel hardware, not the flat wizard.
_FLOOR_ENDPOINTS = ("/flats/status", "/livestack/status", "/profile/show")

# What a tier publishes before its endpoint has ever answered, and what it goes
# on publishing if the build does not serve it.
_NO_FLATS = FlatsStatus(state=None, total_iterations=None, completed_iterations=None)
_NO_LIVESTACK = LivestackStatus(running=False, raw_state="")
_NO_PROFILE = ProfileSettings(
    focal_length=None,
    pixel_size=None,
    autofocus_timeout_seconds=None,
    r_squared_threshold=None,
    min_minutes_after_meridian=None,
    max_minutes_after_meridian=None,
    use_side_of_pier=None,
)


@dataclass(frozen=True, slots=True)
class NinaData:
    """One published snapshot. Frozen, and assembled without awaiting."""

    snapshot: EquipmentSnapshot
    session: SessionStats
    sequence: SequenceNode | None
    flats: FlatsStatus
    livestack: LivestackStatus
    profile: ProfileSettings
    generation: str | None
    version: VersionInfo


class NinaCoordinator(DataUpdateCoordinator[NinaData]):
    """Polls the fast tier and publishes `NinaData`.

    The §5.2.2 first-sight rule lives here because the mapper is stateless:
    `/equipment/info` always emits all eleven device blocks, so a block's
    presence proves nothing. A device is *observed* once it has carried a
    `DeviceId`, and the observation is latched for the coordinator's lifetime —
    disconnection drops the `DeviceId`, so evaluating it per poll would delete
    the device the moment it went down. A never-observed kind publishes as
    `None`; an observed one that is down publishes with `connected=False`.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: NinaClientV2,
        *,
        config_entry: ConfigEntry,
        update_interval: timedelta = FAST_INTERVAL,
        version: VersionInfo = VersionInfo(None, None),
        rollover_hour: int = DEFAULT_ROLLOVER_HOUR,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="N.I.N.A. Astrophotography",
            update_interval=update_interval,
        )
        self.client = client
        self.frames: dict[tuple[datetime, str], Frame] = {}
        self.events: list[NinaEvent] = []
        self.generation: str | None = None
        # Set by setup once the socket exists, so the generation reaches the
        # push path: an event tagged with a stale one is filtered out of the
        # fold the moment it arrives.
        self.event_stream: NinaEventStream | None = None
        self._version = version
        self._rollover_hour = rollover_hour
        self._observed: set[str] = set()
        self._rejection_logged = False
        self._unavailable_logged = False
        self._restart = RestartDetector()
        self._reseed_guard = ReseedGuard()
        self._ledger = EventLedger()
        self._seeded = False
        self._replayed = False
        self._mismatch_logged = False
        self._schedule = TierSchedule()
        self._sequence: SequenceNode | None = None
        self._flats = _NO_FLATS
        self._livestack = _NO_LIVESTACK
        self._profile = _NO_PROFILE
        self._not_served: set[str] = set()
        self._tier_warned: set[str] = set()
        self._last_image_save: float | None = None
        self._last_count: int | None = None
        # The latched snapshot of the last successful poll. A push publishes
        # against it rather than reading /equipment/info of its own: an event
        # says nothing about the eleven devices, and a read would put an await
        # between the fold and the publish.
        self._last_snapshot: EquipmentSnapshot | None = None

    async def _async_update_data(self) -> NinaData:
        try:
            snapshot = await self.client.get_equipment()
            application_start = await self.client.get_application_start()
            count = await self.client.get_image_history_count()
            await self._track_process(application_start, count)
        except (NinaRequestError, NinaEndpointError) as exc:
            # Neither becomes right by retrying. With a previous snapshot, log
            # once and keep it rather than making every entity unavailable;
            # with none, fail the entry — ConfigEntryNotReady would retry a
            # permanent condition forever.
            if self.data is None:
                raise ConfigEntryError(f"N.I.N.A. rejected a request: {exc}") from exc
            if not self._rejection_logged:
                _LOGGER.error("N.I.N.A. rejected a request: %s", exc)
                self._rejection_logged = True
            # A refused request is an answer, so the rig is up and the entities
            # are available again on the retained data.
            self._note_reachable()
            return self.data
        except NinaError as exc:
            # log-when-unavailable (§7.3). Home Assistant logs its own "Error
            # fetching …" for the UpdateFailed; this one is the ENTITY-visible
            # transition, and it is logged once per outage rather than once per
            # ten-second tick.
            if not self._unavailable_logged:
                _LOGGER.warning("N.I.N.A. at %s is unavailable: %s", self._host, exc)
                self._unavailable_logged = True
            raise UpdateFailed(str(exc)) from exc

        self._rejection_logged = False
        self._note_reachable()
        snapshot = self._latch_observed(snapshot)
        self._log_connection_changes(snapshot)
        await self._run_tiers(snapshot, count)
        self._last_snapshot = snapshot
        if not self._replayed:
            # Setup: fold what the socket could not deliver because it was not
            # connected yet. Before `_assemble`, so the first published snapshot
            # already carries it and no extra publish is needed.
            await self._replay()
        return self._assemble(snapshot)

    async def _track_process(self, application_start: str | None, count: int) -> None:
        """Apply the process boundary, and keep the frame set whole across it.

        Runs inside the poll's own error handling: every call it makes can
        raise, and a failure here is a failed poll rather than a silent gap in
        the fold.
        """
        restarted = self._restart.observe(application_start, count)
        if restarted:
            _LOGGER.info(
                "N.I.N.A. restarted (%s); reseeding from /image-history?all=true",
                application_start,
            )
            # A restart is exactly when the served routes change — a plugin
            # enabled, the API updated — so what the old process refused says
            # nothing about the new one. `/event-history` is replayed again for
            # the same reason, under the new generation.
            self._not_served.clear()
            self._tier_warned.clear()
            self._replayed = False
        # Only a restart moves the generation on. A single unreadable
        # /application-start is missing information, not a new process, and
        # adopting its `None` would filter the whole session away for a tick.
        if restarted or self.generation is None:
            self._set_generation(application_start)
        # The frame set is never seeded from the bare path: it answers the
        # newest frame alone, which leaves the session count reading 1. The
        # guard is consulted only when nothing else has already asked for a
        # reseed — a tick that reseeds anyway must not spend one of its two
        # strikes.
        if restarted or not self._seeded:
            await self._reseed(count)
        elif self._reseed_guard.check(self._generation_frames(), count):
            await self._reseed(count)
        self._restart.update(application_start, count)

    def handle_event(self, event: NinaEvent) -> None:
        """Fold one pushed event into the accumulated sets and publish.

        `async_set_updated_data`, never `async_request_refresh`: publishing the
        fold directly is what makes the design push-first rather than
        socket-as-a-hint (§6.3). `_react_to` holds the exceptions — the events
        that ask for a value the event itself does not carry.

        The publish comes FIRST, and the order is load-bearing:
        `async_set_updated_data` cancels the debouncer, so a publish after
        §6.4's `async_request_refresh` would eat the very refetch that branch
        had just asked for.
        """
        if not self._take(event):
            return
        self._publish()
        self._react_to(event)

    def _react_to(self, event: NinaEvent) -> None:
        """Queue what one event's own payload cannot answer.

        AUTOFOCUS-FINISHED queues nothing yet: /equipment/focuser/last-af has
        no model until phase C. TS-* queue nothing by design — TS-TARGETSTART
        fires once per exposure and its payload already carries TargetName,
        ProjectName, Rotation and TargetEndTime (§6.1).
        """
        name = event.name
        if name == "IMAGE-SAVE":
            # The imaging heuristic only — the frame itself rides the push path.
            self._last_image_save = time.monotonic()
        elif name == "SEQUENCE-FINISHED":
            # The recency arm of the heuristic is what keeps the tier at 30 s
            # for five minutes after the last frame, so the event has to clear
            # it as well as the cadence; live activity — a rising count, a
            # camera still exposing — still overrides both on the next tick.
            self._last_image_save = None
            self._schedule.sequence_finished()
            self._schedule.add_pending("/sequence/json")
        elif name == "SEQUENCE-STARTING":
            # Both boundaries move every node's status at once, and the
            # document is the only place that is reported. Queued rather than
            # fetched: /sequence/json passes the same ≤1 per 30 s debounce
            # whichever caller asked for it.
            self._schedule.add_pending("/sequence/json")
        elif name.startswith("PROFILE-"):
            self._schedule.add_pending("/profile/show")
        elif name == "STACK-STATUS":
            # The payload's `Status` is the transition the plugin announced,
            # not the server's own state, and only /livestack/status reports
            # whether the stack is running — so it is read back.
            self._schedule.add_pending("/livestack/status")
        elif (name == "SAFETY-CHANGED" or name.startswith("FLAT-")
                or name.endswith(("-CONNECTED", "-DISCONNECTED"))):
            # Nothing safety-related waits for a tier (§6.4), and a connection
            # change moves all eleven device blocks at once. The FLAT-* events
            # are change hints and nothing more (§5.3.4) — FLAT-LIGHT-TOGGLED
            # carries an empty payload and FLAT-BRIGHTNESS-CHANGED fires
            # through a ramp with inconsistent `Previous` values — so the
            # panel's state comes from /equipment/info.
            #
            # `async_request_refresh`, not `async_refresh`: its debouncer runs
            # the first call immediately and coalesces the rest. A N.I.N.A.
            # start emits eleven connection events in a few seconds, and eleven
            # bare refreshes would both spend eleven snapshots and interleave
            # their awaits over the frame set.
            #
            # On the entry, like the reconnect task, so unload cancels it.
            self.config_entry.async_create_task(
                self.hass, self.async_request_refresh(), "nina_event_refresh"
            )

    def schedule_reconnect(self) -> None:
        """Run the reconnect recovery on the entry, so unload cancels it."""
        self.config_entry.async_create_task(
            self.hass, self.async_reconnected(), "nina_reconnect"
        )

    async def async_reconnected(self) -> None:
        """The socket came back: recover what it could not deliver while down.

        The poll comes FIRST. N.I.N.A. may have restarted while the socket was
        down, and replaying under the stale generation would tag every replayed
        event to be filtered straight back out of the fold. That poll also
        performs §6.1's one-shot reseed: `/event-history` carries
        `{Event, Time}` only, so it can never reconstruct the statistics a
        missed `IMAGE-SAVE` push held — the frames come back from `?all=true`.
        """
        self._seeded = False
        await self.async_refresh()
        await self._replay()
        self._publish()

    async def _replay(self) -> None:
        """Fold `/event-history`. The caller publishes, once, afterwards."""
        if self.event_stream is None:
            return
        try:
            replayed = await self.event_stream.replay(self.client, self.generation)
        except NinaEndpointError:
            # A route this build does not serve cannot start working, and the
            # setup replay would otherwise ask again on every 10 s tick.
            _LOGGER.info("/event-history is not served by this N.I.N.A.; not replaying")
            self._replayed = True
            return
        except NinaError as exc:
            # An empty history is normal; an unreadable one is not worth failing
            # setup over, and the next poll tries again.
            _LOGGER.debug("Could not replay /event-history: %s", exc)
            return
        for event in replayed:
            self._take(event)
        self._replayed = True

    def _take(self, event: NinaEvent) -> bool:
        """Accept one event into the sets; False if it has been taken already.

        One ledger serves the socket and the replay, so an event that arrives
        by both paths is folded once. The mapper has already turned an
        `IMAGE-SAVE` payload into a `Frame` — no wire dict reaches this module.
        """
        if self._ledger.seen(event):
            return False
        self._ledger.mark(event)
        self.events.append(event)
        if event.frame is not None:
            self.frames[(event.frame.date, event.frame.filename)] = event.frame
        return True

    def _publish(self) -> None:
        """Freeze the live sets and hand them to the entities, with no poll.

        Silent while the last poll failed, and before the first has succeeded.
        `async_set_updated_data` sets `last_update_success`, so publishing
        against a stale `_last_snapshot` would flip eleven devices back to
        available on a rig that is still unreachable. The fold accumulates
        either way; the next successful poll publishes what piled up.

        Each publish also restarts the fast tier's interval — that is what
        `async_set_updated_data` does — so a busy night's ~600 events push the
        next tick out by up to 10 s apiece. Bounded and harmless: an event
        arriving IS the fresher information the tick would have gone to fetch.
        """
        if self._last_snapshot is None or not self.last_update_success:
            return
        self.async_set_updated_data(self._assemble(self._last_snapshot))

    async def _run_tiers(self, snapshot: EquipmentSnapshot, count: int) -> None:
        """The non-fast tiers, behind the fast tier's own tick.

        A tier never fails the poll: the fast tier owns the entry's
        availability, and a five-minute endpoint going quiet must not make
        eleven devices unavailable.
        """
        schedule = self._schedule
        # The first read has no baseline, so 122 frames against an initial 0 is
        # not a rise — the same first-read rule the restart detector applies.
        baseline = count if self._last_count is None else self._last_count
        self._last_count = count
        schedule.set_imaging(
            imaging(snapshot, count, baseline, self._since_last_image_save())
        )
        queued = schedule.take_pending()
        # Every /sequence/json read passes one debounce — the tier's own and
        # any an event queued — so ≤1 per 30 s is structural rather than a
        # property of whichever caller asked (§6.1). It re-enters `endpoints`
        # only through that debounce.
        endpoints = queued - {"/sequence/json"}
        asked_for = "/sequence/json" in queued
        wanted = asked_for or schedule.due("sequence")
        if wanted and schedule.request_sequence_refetch(
            requeue="/sequence/json" if asked_for else None
        ):
            endpoints.add("/sequence/json")
            schedule.mark("sequence")
        if schedule.due("floor"):
            endpoints.update(_FLOOR_ENDPOINTS)
            schedule.mark("floor")
        for endpoint in sorted(endpoints):
            await self._read_tier(endpoint, queued=endpoint in queued)

    async def _read_tier(self, endpoint: str, *, queued: bool) -> None:
        """One tier read, which cannot fail the poll by any route.

        `queued` says the read was asked for by an event rather than by a
        cadence: a transient failure re-queues it, because the alternative is
        losing the event's request until the five-minute floor comes round.
        """
        if endpoint in self._not_served:
            return
        attribute, getter = _TIER_READS[endpoint]
        try:
            model = await getattr(self.client, getter)()
        except NinaEndpointError:
            # A build without the livestack plugin, or a route this API version
            # does not carry. It cannot start working, so stop asking and leave
            # the model at its empty value — the entities read "nothing here"
            # rather than going unavailable.
            self._not_served.add(endpoint)
            _LOGGER.info("%s is not served by this N.I.N.A.; not polling it again",
                         endpoint)
            return
        except NinaError as exc:
            # Transient. Keep what the last successful read left and try again
            # when the tier is next due.
            _LOGGER.debug("%s failed this tick: %s", endpoint, exc)
            if queued:
                self._schedule.add_pending(endpoint)
            return
        except Exception:                                          # noqa: BLE001
            # A wire shape no mapper anticipated. Broad on purpose: this runs
            # outside the fast tier's own guard, so anything escaping here
            # fails the poll and takes eleven devices unavailable over one
            # five-minute endpoint. Warned once per endpoint, and again if it
            # recovers and breaks anew.
            if endpoint not in self._tier_warned:
                self._tier_warned.add(endpoint)
                _LOGGER.warning("Could not read %s; keeping the last value",
                                endpoint, exc_info=True)
            return
        setattr(self, attribute, model)
        self._tier_warned.discard(endpoint)

    @property
    def _host(self) -> str:
        """What the logs name this rig by; two entries share a logger."""
        return self.config_entry.data[CONF_HOST]

    def _note_reachable(self) -> None:
        """Announce the recovery once, and only after an outage was announced."""
        if self._unavailable_logged:
            _LOGGER.info("N.I.N.A. at %s is back online", self._host)
            self._unavailable_logged = False

    def _log_connection_changes(self, snapshot: EquipmentSnapshot) -> None:
        """Level 2's transitions: one line when a device drops, one when it returns.

        A kind that has never been observed connected has not "come back" —
        equipment is routinely down when Home Assistant starts, and treating
        first sight as a recovery would log a line per device at every startup.
        """
        previous = self._last_snapshot
        if previous is None:
            return
        for kind, label in KINDS.items():
            before = getattr(previous, kind)
            after = getattr(snapshot, kind)
            if before is None or after is None or before.connected == after.connected:
                continue
            if after.connected:
                _LOGGER.info("%s reconnected on %s", label, self._host)
            else:
                _LOGGER.warning("%s disconnected on %s", label, self._host)

    def _since_last_image_save(self) -> float:
        """Seconds since the last IMAGE-SAVE; infinite before the first."""
        if self._last_image_save is None:
            return float("inf")
        return time.monotonic() - self._last_image_save

    def _set_generation(self, generation: str | None) -> None:
        """Publish the process tag everything the fold keeps is stamped with.

        A change unseeds the frame set. Everything held was stamped with the
        old tag and the fold filters on the new one, so without this the
        session reads zero until the reseed guard's two-tick rule restores it —
        which is what an `/application-start` unreadable on the first poll then
        readable on the second does.
        """
        if generation != self.generation:
            self._seeded = False
        self.generation = generation
        if self.event_stream is not None:
            self.event_stream.generation = generation

    def _generation_frames(self) -> int:
        """Frames held for the CURRENT process — what `?count=true` counts.

        `?count=true` is process-scoped, not session-scoped, so the invariant
        is checked against the whole generation and not the night. The set is
        therefore unbounded for the N.I.N.A. process lifetime: pruning it makes
        the fold smaller than the count forever, and so reseeds forever. At
        Target Scheduler volumes a week is a few thousand frames.
        """
        return sum(1 for f in self.frames.values() if f.generation == self.generation)

    async def _reseed(self, count: int) -> None:
        """Union `/image-history?all=true` into the frame set. Never clears.

        Clearing races a concurrent poll and loses what arrives during the
        refetch; the stale generation is dropped by the fold's filter instead.
        """
        for frame in await self.client.get_frames(
            include_all=True, generation=self.generation
        ):
            self.frames[(frame.date, frame.filename)] = frame
        self._seeded = True
        held = self._generation_frames()
        if not self._reseed_guard.settle(held, count):
            self._mismatch_logged = False
        elif not self._mismatch_logged:
            _LOGGER.info(
                "history count %s differs from %s mapped frames after a reseed; "
                "will re-check when the count changes",
                count, held,
            )
            self._mismatch_logged = True

    def _latch_observed(self, snapshot: EquipmentSnapshot) -> EquipmentSnapshot:
        """Record every kind carrying a `DeviceId`; blank the never-observed.

        `KINDS` and the `EquipmentSnapshot` field names are one list — a kind
        indexes the snapshot directly.
        """
        for kind in KINDS:
            device = getattr(snapshot, kind)
            if device is not None and device.meta.device_id is not None:
                self._observed.add(kind)
        unseen = {kind: None for kind in KINDS if kind not in self._observed}
        return replace(snapshot, **unseen)

    def _now(self) -> datetime:
        """The clock the session's rollover is measured against.

        Frame dates carry the RIG's offset, so the boundary must be rig-local:
        12:00 UTC is 07:00 on a UTC-5 rig, inside its dawn flats. Home
        Assistant's own zone is the fallback until the mount's clock has been
        read, and the two differ on any rig not co-located with the server.
        """
        offset = self.client.rig_offset
        if offset is None:
            return dt_util.now()
        return dt_util.utcnow().astimezone(timezone(offset))

    def _assemble(self, snapshot: EquipmentSnapshot) -> NinaData:
        """Freeze the live sets into one snapshot. Synchronous by design."""
        return NinaData(
            snapshot=snapshot,
            session=fold(
                self.frames.values(),
                self.events,
                self.generation,
                autofocus_timeout_seconds=(
                    self._profile.autofocus_timeout_seconds
                    or DEFAULT_AUTOFOCUS_TIMEOUT
                ),
                now=self._now(),
                rollover_hour=self._rollover_hour,
            ),
            sequence=self._sequence,
            flats=self._flats,
            livestack=self._livestack,
            profile=self._profile,
            generation=self.generation,
            version=self._version,
        )


@dataclass
class NinaRuntimeData:
    """Everything setup builds, hung on `entry.runtime_data` (Bronze).

    `service_client` is the 1.4.x client the unmigrated services still call;
    phase D retires it.
    """

    client: NinaClientV2
    coordinator: NinaCoordinator
    service_client: NinaApiClient
    instance_name: str
    events: NinaEventStream


type NinaConfigEntry = ConfigEntry[NinaRuntimeData]

"""The DataUpdateCoordinator: the I/O, and the frame and event sets it owns.

`session.py` folds those sets statelessly; the polling decisions live in
`polling.py`. Four writers touch the sets — the poll, the socket, the
/event-history replay and the restart reseed — so `NinaData` is assembled
with no `await` between reading them and freezing it. Otherwise a poll
awaiting /equipment/info while IMAGE-SAVE arrives publishes a read from
before the event, and the frame appears, vanishes and reappears.

The slower tiers run behind the one 10 s tick; `_run_tiers` decides which are
due.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api.errors import NinaEndpointError, NinaError, NinaRequestError
from .api.models import (
    AutoFocusReport,
    EquipmentSnapshot,
    FlatsStatus,
    Frame,
    LivestackStatus,
    NinaEvent,
    ProfileSettings,
    SequenceNode,
    SessionStats,
    StackState,
    VersionInfo,
)
from .api.v2 import NinaClientV2
from .const import CONF_HOST, DEFAULT_ROLLOVER_HOUR
from .device import KINDS
from .polling import (
    EventLedger,
    GuiderStopLatch,
    ReseedGuard,
    RestartDetector,
    TierSchedule,
    imaging,
)
from .sequence import running, target_name
from .session import (
    DEFAULT_AUTOFOCUS_TIMEOUT,
    fold,
    latest_stack,
    latest_target,
    pending_guider_stop,
    recent_frames,
    scheduler_wait,
)

if TYPE_CHECKING:
    from .api.v2.events import NinaEventStream

_LOGGER = logging.getLogger(__name__)

FAST_INTERVAL = timedelta(seconds=10)

# endpoint -> (the attribute the model is stored on, the client getter).
_TIER_READS: dict[str, tuple[str, str]] = {
    "/sequence/json": ("_sequence", "get_sequence"),
    "/flats/status": ("_flats", "get_flats"),
    "/livestack/status": ("_livestack", "get_livestack"),
    "/profile/show": ("_profile", "get_profile"),
    "/equipment/focuser/last-af": ("_last_autofocus", "get_last_autofocus"),
}

# Read every five minutes whatever the events say. `/flats/status` has no event
# (the FLAT-* events are the panel, not the flat wizard), and last-af is the
# only evidence a finished autofocus was rejected, so a missed
# AUTOFOCUS-FINISHED must not leave it unread.
_FLOOR_ENDPOINTS = (
    "/flats/status",
    "/livestack/status",
    "/profile/show",
    "/equipment/focuser/last-af",
)

# Published until the endpoint first answers, and for good if it is not served.
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
    site_latitude=None,
    site_longitude=None,
    site_elevation=None,
)


@dataclass(frozen=True, slots=True)
class NinaData:
    """One published snapshot. Frozen, and assembled without awaiting."""

    snapshot: EquipmentSnapshot
    session: SessionStats
    sequence: SequenceNode | None
    flats: FlatsStatus
    livestack: LivestackStatus
    stack: StackState | None
    """What `image.livestack` fetches; None until a stack has updated."""
    target: str | None
    """What the sequence is shooting: the newest `TS-*TARGETSTART`'s name, else
    the innermost `TargetName` in `/sequence/json`. Unlike
    `session.last_frame.target_name`, it moves before a new target's first
    sub."""
    autofocus_report: AutoFocusReport | None
    """The newest `/equipment/focuser/last-af`, or `None` if none was ever run.
    It survives a restart, so it is dated against the session before use."""
    newest_frame: Frame | None
    """The newest frame of any type this process saved. `session.last_frame`
    is the newest light inside the session window, so after a flat run or the
    rollover the two differ."""
    recent_frames: tuple[Frame, ...]
    """The newest frames of any type, newest first, bounded."""
    profile: ProfileSettings
    generation: str | None
    version: VersionInfo
    imaging: bool
    """The activity heuristic, computed once per tick for both the tier
    schedule and `binary_sensor.imaging`."""
    running: bool
    """Whether the sequencer is executing, which it is while Target Scheduler
    waits out a start window and `imaging` is false. See `sequence.running`."""
    wait_ends_at: datetime | None
    """When Target Scheduler's current wait ends, or None if it is not waiting."""
    guider_stopped: bool
    """Whether a `GUIDER-STOP` is still in force: no `GUIDER-START` or running
    guider seen since. Tells a stale `LostLock` from a guider hunting for its
    star."""


class NinaCoordinator(DataUpdateCoordinator[NinaData]):
    """Polls, folds pushed events, and publishes `NinaData`.

    `/equipment/info` always carries all eleven device blocks, so a block
    proves nothing. A kind is observed once it has carried a `DeviceId`, and
    that is latched for the coordinator's lifetime, because disconnecting drops
    the `DeviceId`. A never-observed kind publishes as `None`; an observed one
    that is down publishes with `connected=False`.
    """

    config_entry: ConfigEntry

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
        # Set by setup, so the stream stamps events with the current generation.
        self.event_stream: NinaEventStream | None = None
        self._version = version
        self._rollover_hour = rollover_hour
        self._observed: set[str] = set()
        self._rejection_logged = False
        self._unavailable_logged = False
        self._restart = RestartDetector()
        self._reseed_guard = ReseedGuard()
        self._ledger = EventLedger()
        self._guider_stop = GuiderStopLatch()
        self._seeded = False
        self._replayed = False
        self._mismatch_logged = False
        self._schedule = TierSchedule()
        self._sequence: SequenceNode | None = None
        self._flats = _NO_FLATS
        self._livestack = _NO_LIVESTACK
        self._profile = _NO_PROFILE
        self._last_autofocus: AutoFocusReport | None = None
        self._not_served: set[str] = set()
        self._tier_warned: set[str] = set()
        self._last_image_save: float | None = None
        self._last_count: int | None = None
        self._imaging = False
        # The last successful poll's snapshot, which a push publishes against:
        # reading /equipment/info would put an await between fold and publish.
        self._last_snapshot: EquipmentSnapshot | None = None

    async def _async_update_data(self) -> NinaData:
        # Before the fetch — see `GuiderStopLatch`.
        guider_stop = pending_guider_stop(self.events, self.generation)
        try:
            snapshot = await self.client.get_equipment()
            application_start = await self.client.get_application_start()
            count = await self.client.get_image_history_count()
            await self._track_process(application_start, count)
        except (NinaRequestError, NinaEndpointError) as exc:
            # Retrying will not fix either. Keep the last data if there is any;
            # otherwise fail the entry rather than retry forever.
            if self.data is None:
                raise ConfigEntryError(f"N.I.N.A. rejected a request: {exc}") from exc
            if not self._rejection_logged:
                _LOGGER.error("N.I.N.A. rejected a request: %s", exc)
                self._rejection_logged = True
            # A refusal is an answer: the rig is up.
            self._note_reachable()
            return self.data
        except NinaError as exc:
            # Once per outage, not once per tick.
            if not self._unavailable_logged:
                _LOGGER.warning("N.I.N.A. at %s is unavailable: %s", self._host, exc)
                self._unavailable_logged = True
            raise UpdateFailed(str(exc)) from exc

        self._rejection_logged = False
        self._note_reachable()
        snapshot = self._latch_observed(snapshot)
        self._guider_stop.observe(
            snapshot.guider.state if snapshot.guider is not None else None,
            guider_stop,
        )
        self._log_connection_changes(snapshot)
        await self._run_tiers(snapshot, count)
        self._last_snapshot = snapshot
        if not self._replayed:
            # What happened before the socket connected, folded before
            # `_assemble` so the first publish carries it.
            await self._replay()
        return self._assemble(snapshot)

    async def _track_process(self, application_start: str | None, count: int) -> None:
        """Detect a N.I.N.A. restart, and keep the frame set whole across it.

        Runs inside the poll's error handling, so a failure here fails the poll
        rather than leaving a gap in the fold.
        """
        restarted = self._restart.observe(application_start, count)
        if restarted:
            _LOGGER.info(
                "N.I.N.A. restarted (%s); reseeding from /image-history?all=true",
                application_start,
            )
            # A new process may serve different routes (a plugin enabled, the
            # API updated), and its /event-history is replayed afresh.
            self._not_served.clear()
            self._tier_warned.clear()
            self._replayed = False
        # Only a restart moves the generation. One unreadable
        # /application-start is not a new process, and adopting its `None`
        # would filter the whole session away for a tick.
        if restarted or self.generation is None:
            self._set_generation(application_start)
        # Seeded from `?all=true`: the bare path answers the newest frame alone.
        # The guard is asked last, so a tick that reseeds anyway spends none of
        # its strikes.
        if (
            restarted
            or not self._seeded
            or self._reseed_guard.check(self._generation_frames(), count)
        ):
            await self._reseed(count)
        self._restart.update(application_start, count)

    def handle_event(self, event: NinaEvent) -> None:
        """Fold one pushed event into the sets and publish it without a poll.

        `_react_to` handles the events whose payload does not carry the value
        they announce. It runs after the publish, because
        `async_set_updated_data` cancels the debouncer and would swallow the
        refresh `_react_to` requests.
        """
        if not self._take(event):
            return
        self._publish()
        self._react_to(event)

    def _react_to(self, event: NinaEvent) -> None:
        """Queue the reads an event announces but does not carry.

        TS-* queue nothing: their payloads carry everything published.
        """
        name = event.name
        if name == "IMAGE-SAVE":
            self._last_image_save = time.monotonic()
        elif name == "SEQUENCE-FINISHED":
            # Clears the recency that would hold the tier at 30 s for five
            # minutes; live activity still overrides it on the next tick.
            self._last_image_save = None
            self._schedule.sequence_finished()
            self._schedule.add_pending("/sequence/json")
        elif name == "SEQUENCE-STARTING":
            # Queued, not fetched, so it passes the ≤1 per 30 s debounce.
            self._schedule.add_pending("/sequence/json")
        elif name.startswith("PROFILE-"):
            self._schedule.add_pending("/profile/show")
        elif name == "AUTOFOCUS-FINISHED":
            # Only /last-af says whether the run was rejected on its fit.
            self._schedule.add_pending("/equipment/focuser/last-af")
        elif name == "STACK-STATUS":
            # `Status` is the transition announced, not whether the stack runs.
            self._schedule.add_pending("/livestack/status")
        elif (
            name == "SAFETY-CHANGED"
            or name.startswith("FLAT-")
            or name.endswith(("-CONNECTED", "-DISCONNECTED"))
        ):
            # Safety must not wait for a tier; a connection change moves every
            # device block; FLAT-* payloads are empty or unreliable through a
            # ramp. The debounced refresh coalesces the burst of connection
            # events a N.I.N.A. start emits.
            self.config_entry.async_create_task(
                self.hass, self.async_request_refresh(), "nina_event_refresh"
            )

    def schedule_reconnect(self) -> None:
        """Run the reconnect recovery on the entry, so unload cancels it."""
        self.config_entry.async_create_task(
            self.hass, self.async_reconnected(), "nina_reconnect"
        )

    async def async_reconnected(self) -> None:
        """Recover what the socket missed while it was down.

        Poll first: N.I.N.A. may have restarted meanwhile, and a replay under
        the old generation would be filtered straight out of the fold. The poll
        also reseeds the frames, since `/event-history` carries no `IMAGE-SAVE`
        statistics.
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
            # Otherwise the setup replay would ask again every tick.
            _LOGGER.info("/event-history is not served by this N.I.N.A.; not replaying")
            self._replayed = True
            return
        except NinaError as exc:
            # The next poll tries again.
            _LOGGER.debug("Could not replay /event-history: %s", exc)
            return
        for event in replayed:
            self._take(event)
        self._replayed = True

    def _take(self, event: NinaEvent) -> bool:
        """Accept one event into the sets; False if it was already taken.

        The socket and the replay share one ledger, so an event arriving by
        both is folded once.
        """
        if self._ledger.seen(event):
            return False
        self._ledger.mark(event)
        self.events.append(event)
        if event.frame is not None:
            self.frames[(event.frame.date, event.frame.filename)] = event.frame
        return True

    def _publish(self) -> None:
        """Publish the live sets without a poll.

        Silent until a poll has succeeded, and while the last one failed:
        `async_set_updated_data` sets `last_update_success`, which would mark
        an unreachable rig available. The next successful poll publishes what
        accumulated. Each publish also restarts the tick's interval, which is
        harmless: the event is the fresher news.
        """
        if self._last_snapshot is None or not self.last_update_success:
            return
        self.async_set_updated_data(self._assemble(self._last_snapshot))

    async def _run_tiers(self, snapshot: EquipmentSnapshot, count: int) -> None:
        """Read the slower tiers that are due. A tier never fails the poll."""
        schedule = self._schedule
        # The first read has no baseline, so it is not a rise.
        baseline = count if self._last_count is None else self._last_count
        self._last_count = count
        self._imaging = imaging(
            snapshot, count, baseline, self._since_last_image_save()
        )
        schedule.set_imaging(self._imaging)
        queued = schedule.take_pending()
        # Every /sequence/json read, scheduled or queued, passes one debounce.
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
        """One tier read, which cannot fail the poll.

        A transient failure of a read an event `queued` re-queues it, rather
        than losing the request until the next five-minute floor.
        """
        if endpoint in self._not_served:
            return
        attribute, getter = _TIER_READS[endpoint]
        try:
            model = await getattr(self.client, getter)()
        except NinaEndpointError:
            # No livestack plugin, say. Stop asking; the entities read the
            # empty model rather than going unavailable.
            self._not_served.add(endpoint)
            _LOGGER.info(
                "%s is not served by this N.I.N.A.; not polling it again", endpoint
            )
            return
        except NinaError as exc:
            # Transient: keep the last read.
            _LOGGER.debug("%s failed this tick: %s", endpoint, exc)
            if queued:
                self._schedule.add_pending(endpoint)
            return
        except Exception:
            # A wire shape the mapper did not anticipate. Broad on purpose: one
            # slow endpoint must not take every device unavailable.
            if endpoint not in self._tier_warned:
                self._tier_warned.add(endpoint)
                _LOGGER.warning(
                    "Could not read %s; keeping the last value", endpoint, exc_info=True
                )
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
        """Log a device dropping and returning, but not its first sighting."""
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
        """Set the process tag the fold filters on.

        A change unseeds the frame set: every frame held carries the old tag,
        so the session would read zero until the reseed guard caught up.
        """
        if generation != self.generation:
            self._seeded = False
        self.generation = generation
        if self.event_stream is not None:
            self.event_stream.generation = generation

    def _generation_frames(self) -> int:
        """Frames held for the current process, which is what `?count=true` counts.

        So the set is never pruned within a process: a pruned set would
        disagree with the count and reseed forever. A week of Target Scheduler
        is a few thousand frames.
        """
        return sum(1 for f in self.frames.values() if f.generation == self.generation)

    async def _reseed(self, count: int) -> None:
        """Union `/image-history?all=true` into the frame set. Never clears.

        Clearing would lose what arrives during the refetch; the fold filters
        out the stale generation instead.
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
                count,
                held,
            )
            self._mismatch_logged = True

    def _latch_observed(self, snapshot: EquipmentSnapshot) -> EquipmentSnapshot:
        """Record every kind carrying a `DeviceId`; blank the never-observed."""
        for kind in KINDS:
            device = getattr(snapshot, kind)
            if device is not None and device.meta.device_id is not None:
                self._observed.add(kind)
        unseen = {kind: None for kind in KINDS if kind not in self._observed}
        return replace(snapshot, **unseen)

    def _now(self) -> datetime:
        """Now, in the rig's zone, which frame dates and the rollover use.

        Home Assistant's zone stands in until the rig's offset is known.
        """
        offset = self.client.rig_offset
        if offset is None:
            return dt_util.now()
        return dt_util.utcnow().astimezone(timezone(offset))

    def _assemble(self, snapshot: EquipmentSnapshot) -> NinaData:
        """Freeze the live sets into one snapshot, synchronously, at one moment."""
        moment = self._now()
        recent = recent_frames(self.frames.values(), self.generation)
        return NinaData(
            snapshot=snapshot,
            session=fold(
                self.frames.values(),
                self.events,
                self.generation,
                autofocus_timeout_seconds=(
                    self._profile.autofocus_timeout_seconds or DEFAULT_AUTOFOCUS_TIMEOUT
                ),
                now=moment,
                rollover_hour=self._rollover_hour,
            ),
            sequence=self._sequence,
            flats=self._flats,
            livestack=self._livestack,
            stack=latest_stack(self.events, self.generation),
            target=(
                latest_target(self.events, self.generation)
                or target_name(self._sequence)
            ),
            autofocus_report=self._last_autofocus,
            newest_frame=recent[0] if recent else None,
            recent_frames=recent,
            profile=self._profile,
            generation=self.generation,
            version=self._version,
            imaging=self._imaging,
            running=running(self._sequence, self.events, self.generation),
            wait_ends_at=scheduler_wait(self.events, self.generation, now=moment),
            guider_stopped=self._guider_stop.stopped(
                pending_guider_stop(self.events, self.generation)
            ),
        )


@dataclass
class NinaRuntimeData:
    """Everything setup builds, on `entry.runtime_data`."""

    client: NinaClientV2
    coordinator: NinaCoordinator
    instance_name: str
    events: NinaEventStream


type NinaConfigEntry = ConfigEntry[NinaRuntimeData]

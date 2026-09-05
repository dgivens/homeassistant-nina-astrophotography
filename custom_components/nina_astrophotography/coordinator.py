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
    sequence   8,429 B @ 30 s  =  16,858 B/min
                                  ──────────
                                  61,378 B/min ~ 3.7 MB/h ~ 37 MB / 10 h night
    before                        82,606 B x 6/min ~ 297 MB / night
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, fields, replace
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
from .polling import ReseedGuard, RestartDetector, TierSchedule, imaging
from .session import fold

if TYPE_CHECKING:
    from .api.v2.events import NinaEventStream
    from .frame_statistics import NinaFrameStatisticsStore
    from .legacy_api import NinaApiClient

_LOGGER = logging.getLogger(__name__)

FAST_INTERVAL = timedelta(seconds=10)

_DEVICE_SLOTS = tuple(field.name for field in fields(EquipmentSnapshot))

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

# What a slot reads before its endpoint has ever answered, and what it goes on
# reading if the build does not serve it.
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
    the device the moment it went down. A never-observed slot publishes as
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
        self._observed: set[str] = set()
        self._rejection_logged = False
        self._restart = RestartDetector()
        self._reseed_guard = ReseedGuard()
        self._seeded = False
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

    async def _async_update_data(self) -> NinaData:
        try:
            snapshot = await self.client.get_equipment()
            application_start = await self.client.get_application_start()
            count = await self.client.get_image_history_count()
            restarted = self._restart.observe(application_start, count)
            if restarted:
                _LOGGER.info(
                    "N.I.N.A. restarted (%s); reseeding from /image-history?all=true",
                    application_start,
                )
            # Only a restart moves the generation on. A single unreadable
            # /application-start is missing information, not a new process, and
            # adopting its `None` would filter the whole session away for a tick.
            if restarted or self.generation is None:
                self._set_generation(application_start)
            # The frame set is never seeded from the bare path: it answers the
            # newest frame alone, which leaves the session count reading 1.
            if restarted or not self._seeded:
                await self._reseed(count)
            elif self._reseed_guard.check(self._generation_frames(), count):
                await self._reseed(count)
            self._restart.update(application_start, count)
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
            return self.data
        except NinaError as exc:
            raise UpdateFailed(str(exc)) from exc

        self._rejection_logged = False
        snapshot = self._latch_observed(snapshot)
        await self._run_tiers(snapshot, count)
        return self._assemble(snapshot)

    def handle_event(self, event: NinaEvent) -> None:
        """React to one pushed event on the tiers. The fold and the push
        publish are B4's; nothing here touches the accumulated sets.
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
        elif name.startswith("PROFILE-"):
            self._schedule.add_pending("/profile/show")
        elif name == "STACK-STATUS":
            # A bare {Event, Time}: it says THAT the status changed, never
            # what to, so the status has to be read back.
            self._schedule.add_pending("/livestack/status")
        elif name == "SAFETY-CHANGED" or name.endswith(("-CONNECTED", "-DISCONNECTED")):
            # Nothing safety-related waits for a tier (§6.4), and a connection
            # change moves all eleven device blocks at once.
            #
            # `async_request_refresh`, not `async_refresh`: its debouncer runs
            # the first call immediately and coalesces the rest. A N.I.N.A.
            # start emits eleven connection events in a few seconds, and eleven
            # bare refreshes would both spend eleven snapshots and interleave
            # their awaits over the frame set.
            self.hass.async_create_task(self.async_request_refresh())
        # AUTOFOCUS-FINISHED queues nothing yet: /equipment/focuser/last-af has
        # no model until phase C. TS-* queue nothing by design — TS-TARGETSTART
        # fires once per exposure and its payload already carries TargetName,
        # ProjectName, Rotation and TargetEndTime (§6.1).

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
        endpoints = set(queued)
        # Every /sequence/json read passes one debounce — the tier's own and
        # any an event queued — so ≤1 per 30 s is structural rather than a
        # property of whichever caller asked (§6.1).
        wanted = "/sequence/json" in endpoints or schedule.due("sequence")
        endpoints.discard("/sequence/json")
        if wanted and schedule.request_sequence_refetch():
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

    def _since_last_image_save(self) -> float:
        """Seconds since the last IMAGE-SAVE; infinite before the first."""
        if self._last_image_save is None:
            return float("inf")
        return time.monotonic() - self._last_image_save

    def _set_generation(self, generation: str | None) -> None:
        """Publish the process tag everything the fold keeps is stamped with."""
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
        """Record every slot carrying a `DeviceId`; blank the never-observed."""
        for slot in _DEVICE_SLOTS:
            device = getattr(snapshot, slot)
            if device is not None and device.meta.device_id is not None:
                self._observed.add(slot)
        unseen = {slot: None for slot in _DEVICE_SLOTS if slot not in self._observed}
        return replace(snapshot, **unseen)

    def _now(self) -> datetime:
        """The clock the session's noon rollover is measured against.

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
                now=self._now(),
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

    `service_client` and `frame_store` are the 1.4.x modules the unmigrated
    services still call; phases B–D retire them.
    """

    client: NinaClientV2
    coordinator: NinaCoordinator
    service_client: NinaApiClient
    instance_name: str
    events: NinaEventStream
    frame_store: NinaFrameStatisticsStore


type NinaConfigEntry = ConfigEntry[NinaRuntimeData]

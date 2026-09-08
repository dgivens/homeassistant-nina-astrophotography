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

Phase B polls the fast tier and holds the generation; the remaining tiers and
the push path follow.
"""
from __future__ import annotations

import logging
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
from .polling import ReseedGuard, RestartDetector
from .session import fold

if TYPE_CHECKING:
    from .api.v2.events import NinaEventStream
    from .frame_statistics import NinaFrameStatisticsStore
    from .legacy_api import NinaApiClient

_LOGGER = logging.getLogger(__name__)

FAST_INTERVAL = timedelta(seconds=10)

_DEVICE_SLOTS = tuple(field.name for field in fields(EquipmentSnapshot))

# Phase A polls the fast tier only, so these three publish as "nothing read yet"
# until phase B adds their endpoints to the poll.
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
        return self._assemble(self._latch_observed(snapshot))

    def handle_event(self, event: NinaEvent) -> None:
        """Take one pushed event. A no-op until B4 gives it the fold."""

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
            sequence=None,
            flats=_NO_FLATS,
            livestack=_NO_LIVESTACK,
            profile=_NO_PROFILE,
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

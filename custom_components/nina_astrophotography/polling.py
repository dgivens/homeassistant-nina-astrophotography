"""The polling decisions, as state machines with no I/O, clock or Home
Assistant; the coordinator composes them.

Nothing here clears anything: a N.I.N.A. restart is a generation change, which
the fold filters on.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import time

from .api.models import EquipmentSnapshot, NinaEvent


class EventLedger:
    """Which events the fold has already taken.

    Keyed on `(generation, name, time)`, all the identity a replayed event
    has: `/event-history` stores only `{Event, Time}`. The generation keeps a
    restarted process's history, whose times can repeat, from reading as seen.

    `IMAGE-SAVE` cannot be deduplicated: the socket's copy is stamped from the
    frame's `Date`, the replayed one with the rig's `Time`. So events are never
    counted; frames are.
    """

    def __init__(self) -> None:
        self._taken: set[tuple[str | None, str, datetime]] = set()

    @staticmethod
    def _key(event: NinaEvent) -> tuple[str | None, str, datetime]:
        return (event.generation, event.name, event.time)

    def seen(self, event: NinaEvent) -> bool:
        return self._key(event) in self._taken

    def mark(self, event: NinaEvent) -> None:
        self._taken.add(self._key(event))


# States only a start produces, so any of them after a GUIDER-STOP means the
# guider is running again.
_GUIDER_RUNNING = frozenset({"Looping", "Calibrating", "Guiding"})

# A pushed and a replayed copy of one stop differ by the clocks' skew.
_SAME_STOP = timedelta(minutes=1)


class GuiderStopLatch:
    """Which `GUIDER-STOP` a poll has since seen the guider running past.

    `GUIDER-START` fires only once a start has settled, which can take
    minutes, so a star lost during the settle is a `LostLock` whose newest
    guider event is still the stop. Seeing the guider running since the stop
    tells that apart from the `LostLock` the stop left behind.

    Only the second poll to find a stop pending can pass it: N.I.N.A. raises
    `GUIDER-STOP` up to half a second before its state leaves `Guiding`, so
    the first may have read `Guiding` from before the stop.
    """

    def __init__(self) -> None:
        self._pending: datetime | None = None
        self._passed: datetime | None = None

    def observe(self, state: str | None, stop: datetime | None) -> None:
        """One poll: `stop` as read before its fetch, `state` as fetched."""
        if stop is None:
            self._passed = None
        elif state in _GUIDER_RUNNING and _same_stop(stop, self._pending):
            self._passed = stop
        self._pending = stop

    def stopped(self, stop: datetime | None) -> bool:
        """Whether `stop` is still in force: logged, and not run past since."""
        return stop is not None and not _same_stop(stop, self._passed)


def _same_stop(stop: datetime, other: datetime | None) -> bool:
    return other is not None and abs(stop - other) <= _SAME_STOP


@dataclass
class RestartDetector:
    """Detects a N.I.N.A. restart.

    `/application-start` changing is authoritative; the frame count going
    backwards also reports one when `/application-start` reads null. A first
    read has no baseline, so it is never a restart.
    """

    generation: str | None = None
    last_count: int = 0

    def observe(self, application_start: str | None, count: int) -> bool:
        if self.generation is None:
            return False
        if application_start and application_start != self.generation:
            return True
        return count < self.last_count

    def update(self, application_start: str | None, count: int) -> None:
        """Record the next baseline, keeping the last start time through an
        unreadable one.
        """
        if application_start is not None:
            self.generation = application_start
        self.last_count = count


class ReseedGuard:
    """Refetch `?all=true` when the fold's size differs from `?count=true`.

    Only after two consecutive mismatches: a frame saved between the two
    requests mismatches once. A mismatch that survives a refetch is
    structural (a frame the mapper skips, or two sharing an identity), so
    `settle` silences the guard until the count moves.
    """

    def __init__(self, consecutive: int = 2) -> None:
        self._consecutive = consecutive
        self._mismatches = 0
        self.latched_count: int | None = None

    def check(self, fold_size: int, count: int) -> bool:
        if count == self.latched_count:
            return False
        self.latched_count = None
        if fold_size == count:
            self._mismatches = 0
            return False
        self._mismatches += 1
        if self._mismatches < self._consecutive:
            return False
        self.reset()
        return True

    def settle(self, fold_size: int, count: int) -> bool:
        """Record what a reseed left behind; True when the gap survived it."""
        self.reset()
        self.latched_count = None if fold_size == count else count
        return self.latched_count is not None

    def reset(self) -> None:
        self._mismatches = 0


class TierSchedule:
    """Per-tier due times, checked inside the one 10 s tick."""

    SEQUENCE_IMAGING = 30.0
    SEQUENCE_IDLE = 300.0
    FLOOR = 300.0
    SEQUENCE_DEBOUNCE = 30.0

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._requested: float | None = None
        self.sequence_interval = self.SEQUENCE_IDLE
        self._pending: set[str] = set()

    def _interval(self, tier: str) -> float:
        """The tier's interval; `KeyError` for an unknown tier."""
        if tier == "sequence":
            return self.sequence_interval
        return {"floor": self.FLOOR}[tier]

    def due(self, tier: str, now: float | None = None) -> bool:
        # First, so an unknown tier raises rather than reading as due.
        interval = self._interval(tier)
        moment = time.monotonic() if now is None else now
        last = self._last.get(tier)
        return last is None or moment - last >= interval

    def mark(self, tier: str, now: float | None = None) -> None:
        self._last[tier] = time.monotonic() if now is None else now

    def set_imaging(self, imaging_now: bool) -> None:
        """Choose the sequence tier's cadence from the activity heuristic."""
        self.sequence_interval = (
            self.SEQUENCE_IMAGING if imaging_now else self.SEQUENCE_IDLE
        )

    def sequence_finished(self) -> None:
        """Drop to the idle interval now, rather than when activity goes quiet.

        Not a latch: renewed activity restores 30 s through `set_imaging`.
        """
        self.sequence_interval = self.SEQUENCE_IDLE

    def request_sequence_refetch(
        self, now: float | None = None, *, requeue: str | None = None
    ) -> bool:
        """True at most once per 30 s.

        When refused, `requeue` is held pending for a later tick rather than
        dropped.
        """
        moment = time.monotonic() if now is None else now
        if (
            self._requested is not None
            and moment - self._requested < self.SEQUENCE_DEBOUNCE
        ):
            if requeue is not None:
                self._pending.add(requeue)
            return False
        self._requested = moment
        return True

    def add_pending(self, endpoint: str) -> None:
        """Queue an endpoint an event asked for; the next tick drains it."""
        self._pending.add(endpoint)

    def take_pending(self) -> set[str]:
        """Return and clear the queued endpoints."""
        pending, self._pending = self._pending, set()
        return pending


# An IMAGE-SAVE older than this is not activity. A longer sub is covered by
# `is_exposing`.
_RECENT_SAVE = 300.0


def imaging(
    snapshot: EquipmentSnapshot,
    count: int,
    last_count: int,
    seconds_since_last_image_save: float,
) -> bool:
    """Infer imaging from activity, never from `/sequence/json` node status,
    which persists from the loaded file and earlier runs on an idle rig.
    """
    if count > last_count:
        return True
    camera = snapshot.camera
    if camera is not None and camera.is_exposing:
        return True
    return seconds_since_last_image_save < _RECENT_SAVE

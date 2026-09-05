"""The polling decisions, as pure state machines.

The coordinator owns the I/O and composes these; they own no clock, no client
and no Home Assistant. That is what lets the unit suite drive a restart or a
transient invariant failure as a sequence of arguments rather than a rig.

Nothing here clears anything. A N.I.N.A. restart is a *generation* change, and
the process boundary is applied downstream by filtering on that tag (§3.6).
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .api.models import EquipmentSnapshot, NinaEvent


class EventLedger:
    """Which events the fold has already taken.

    The key is `(generation, name, time)` — all the identity a replayed event
    has, since `/event-history` stores exactly `{Event, Time}` even for the
    `IMAGE-SAVE` the socket sent with statistics attached.

    The mark is scoped to the GENERATION. A restart resets `/event-history`
    with fresh timestamps that can be EARLIER than a retained mark — a
    next-evening restart emits 21:00 events against an 05:30 one — so a mark
    spanning generations would filter a whole replay away as already-seen.
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


@dataclass
class RestartDetector:
    """The restart signals, all observed across two restarts in one day.

    `/application-start` is authoritative; `/image-history?count=true` going
    backwards is a free corroboration at the same resolution, and it is what
    still reports a restart across a tick whose `/application-start` reads
    null. A first read has no baseline, so it is never a restart — treating it
    as one would reseed on every startup and fire a false restart at every
    reload.
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
        """Record the baseline the next `observe` is measured against.

        An unreadable `/application-start` is missing information, not a new
        process, so the last value seen is kept: erasing it would leave the
        next tick with no baseline and so blind to the restart it reports.
        """
        if application_start is not None:
            self.generation = application_start
        self.last_count = count


class ReseedGuard:
    """`?count=true`'s job: fold size ≠ count ⇒ refetch `?all=true`.

    The mismatch must hold on two consecutive ticks. The count and the history
    are separate requests, so a frame saved between them fails the invariant
    transiently — and answering that immediately spends a 62 KB refetch every
    time it happens. A match resets the count, and so does firing.

    A mismatch that SURVIVES a refetch is structural, not transient: the count
    and the fold disagree about what a frame is — an item the mapper skips, or
    two the fold's `(date, filename)` identity merges. No refetch can close
    that, so `settle` latches the guard at that count and it stays quiet until
    the count moves; otherwise the invariant check reseeds every two ticks for
    the life of the process.
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
    """Per-tier due times, against an injected monotonic clock.

    Six tiers, one coordinator: a single 10 s tick with per-tier due-time
    checks inside it, not three coordinators.

        fast       7,420 B @ 10 s  =  44,520 B/min
        sequence   8,418 B @ 30 s  =  16,836 B/min
                                      ──────────
                                      61,356 B/min ~ 3.7 MB/h ~ 37 MB / night
        before                        82,606 B x 6/min ~ 297 MB / night
    """

    FAST = 10.0
    SEQUENCE_IMAGING = 30.0
    SEQUENCE_IDLE = 300.0
    FLOOR = 300.0
    SEQUENCE_DEBOUNCE = 30.0

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        # `time.monotonic` is resolved per call rather than bound as a default
        # argument, which would capture the real function at import time and
        # leave no seam for a test clock.
        self._clock = clock
        self._last: dict[str, float] = {}
        self._requested: float | None = None
        self.sequence_interval = self.SEQUENCE_IDLE
        self._pending: set[str] = set()

    def _now(self) -> float:
        return time.monotonic() if self._clock is None else self._clock()

    def _interval(self, tier: str) -> float:
        """`KeyError` on an unknown tier: a silent default would hand a
        misspelled caller a cadence it never asked for."""
        if tier == "sequence":
            return self.sequence_interval
        return {"fast": self.FAST, "floor": self.FLOOR}[tier]

    def due(self, tier: str, now: float | None = None) -> bool:
        # Resolved before the never-run shortcut, so an unknown tier raises
        # rather than reading as due.
        interval = self._interval(tier)
        moment = self._now() if now is None else now
        last = self._last.get(tier)
        return last is None or moment - last >= interval

    def mark(self, tier: str, now: float | None = None) -> None:
        self._last[tier] = self._now() if now is None else now

    def set_imaging(self, imaging_now: bool) -> None:
        """Choose the sequence tier's cadence from the activity heuristic."""
        self.sequence_interval = (
            self.SEQUENCE_IMAGING if imaging_now else self.SEQUENCE_IDLE
        )

    def sequence_finished(self) -> None:
        """Fall back to the idle interval — `SEQUENCE-FINISHED` fires once at
        session end, so the cadence need not wait the five minutes the activity
        heuristic (§6.2) takes to go quiet. Not a latch: a rising frame count
        afterwards puts the tier back at 30 s through `set_imaging`."""
        self.sequence_interval = self.SEQUENCE_IDLE

    def request_sequence_refetch(self, now: float | None = None, *,
                                 requeue: str | None = None) -> bool:
        """True at most once per 30 s.

        `TS-TARGETSTART` fires once per exposure and its payload already
        carries what a refetch would fetch, so an undebounced refetch turns the
        sequence tier's budget into a per-exposure cost.

        `requeue` names the endpoint to hold pending when the debounce refuses:
        the debounce is a rate limit, not a veto, and dropping a request an
        event made loses it until the five-minute floor comes round.
        """
        moment = self._now() if now is None else now
        if (self._requested is not None
                and moment - self._requested < self.SEQUENCE_DEBOUNCE):
            if requeue is not None:
                self._pending.add(requeue)
            return False
        self._requested = moment
        return True

    def add_pending(self, endpoint: str) -> None:
        """Queue an endpoint an event asked for; the next tick drains it."""
        self._pending.add(endpoint)

    def take_pending(self) -> set[str]:
        """The queued endpoints, cleared. Draining is the caller's obligation:
        a queue that is read without clearing re-reads on every tick."""
        pending, self._pending = self._pending, set()
        return pending


# An IMAGE-SAVE older than this no longer counts as activity. One 600 s sub is
# longer than the window, which is why `is_exposing` is a separate signal
# rather than a refinement of it.
_RECENT_SAVE = 300.0


def imaging(
    snapshot: EquipmentSnapshot,
    count: int,
    last_count: int,
    seconds_since_last_image_save: float,
) -> bool:
    """Infer imaging from activity, never from `/sequence/json` node status.

    Node `Status` persists from the loaded sequence file and from prior runs:
    on the idle rig three nodes read RUNNING with nothing happening and zero
    frames captured. Tree status drives only the displayed per-instruction
    state, so gating the sequence tier on it polls at 30 s indefinitely.

    All three signals are already on the fast tier, so this costs no request.
    """
    if count > last_count:
        return True
    camera = snapshot.camera
    if camera is not None and camera.is_exposing:
        return True
    return seconds_since_last_image_save < _RECENT_SAVE

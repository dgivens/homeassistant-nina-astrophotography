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


@dataclass
class RestartDetector:
    """The restart signals, all observed across two restarts in one day.

    `/application-start` is authoritative; `/image-history?count=true` going
    backwards is a free corroboration at the same resolution, and the only
    signal left on a build that does not serve `/application-start`. A first
    read has no baseline, so it is never a restart — treating it as one would
    reseed on every startup and fire a false restart at every reload.
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
        """Record the baseline the next `observe` is measured against."""
        self.generation = application_start
        self.last_count = count


class ReseedGuard:
    """`?count=true`'s job: fold size ≠ count ⇒ refetch `?all=true`.

    The mismatch must hold on two consecutive ticks. The count and the history
    are separate requests, so a frame saved between them fails the invariant
    transiently — and answering that immediately spends a 62 KB refetch every
    time it happens. A match resets the count, and so does firing.
    """

    def __init__(self, consecutive: int = 2) -> None:
        self._consecutive = consecutive
        self._mismatches = 0

    def check(self, fold_size: int, count: int) -> bool:
        if fold_size == count:
            self._mismatches = 0
            return False
        self._mismatches += 1
        if self._mismatches < self._consecutive:
            return False
        self.reset()
        return True

    def reset(self) -> None:
        self._mismatches = 0


class TierSchedule:
    """Per-tier due times, against an injected monotonic clock.

    Six tiers, one coordinator: a single 10 s tick with per-tier due-time
    checks inside it, not three coordinators. B2 uses the fast tier and the
    reseed hooks; the sequence, floor and event-driven tiers land in B3.
    """

    SEQUENCE_IMAGING = 30.0
    SEQUENCE_IDLE = 300.0
    FLOOR = 300.0
    SEQUENCE_DEBOUNCE = 30.0

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: dict[str, float] = {}
        self._requested: float | None = None
        self.sequence_interval = self.SEQUENCE_IDLE
        self.pending: set[str] = set()

    def _interval(self, tier: str) -> float:
        return self.sequence_interval if tier == "sequence" else self.FLOOR

    def due(self, tier: str, now: float | None = None) -> bool:
        moment = self._clock() if now is None else now
        last = self._last.get(tier)
        return last is None or moment - last >= self._interval(tier)

    def mark(self, tier: str, now: float | None = None) -> None:
        self._last[tier] = self._clock() if now is None else now

    def request_sequence_refetch(self, now: float | None = None) -> bool:
        """True at most once per 30 s.

        `TS-TARGETSTART` fires once per exposure and its payload already
        carries what a refetch would fetch, so an undebounced refetch turns the
        sequence tier's budget into a per-exposure cost.
        """
        moment = self._clock() if now is None else now
        if (self._requested is not None
                and moment - self._requested < self.SEQUENCE_DEBOUNCE):
            return False
        self._requested = moment
        return True

    def add_pending(self, endpoint: str) -> None:
        """Queue an endpoint an event asked for; the next tick drains it."""
        self.pending.add(endpoint)

    def drop_sequence_cadence(self) -> None:
        """Fall back to the idle interval — `SEQUENCE-FINISHED` fires once at
        session end, so the cadence need not wait for the activity heuristic
        (§6.2) to go quiet."""
        self.sequence_interval = self.SEQUENCE_IDLE

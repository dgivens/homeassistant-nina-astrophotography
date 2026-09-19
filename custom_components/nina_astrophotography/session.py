"""The session fold — pure, stateless, idempotent.

The coordinator owns the accumulated frame and event set; this module receives
it as an argument and returns a value. That is what makes push, poll and
/event-history replay the same operation, so arrival order stops mattering.

Frame identity is (Date, Filename), confirmed present and identical on both the
push and poll paths. Date is the SAVE time — start + exposure + download — so
anything reasoning about when a frame was taken must subtract ExposureTime.

Aggregates are computed once from a deterministic sorted iteration, never
accumulated incrementally: order-independence over floats is false under
incremental accumulation, and frozen-dataclass equality is exact.

The process boundary is the generation tag, applied by FILTERING. Clearing races
a concurrent poll, produces a false positive on the first read when no baseline
exists, and loses events arriving during the refetch.
"""
from __future__ import annotations

import heapq
from collections.abc import Callable, Container, Iterable, Sequence
from datetime import datetime, timedelta
from math import fsum
from statistics import fmean

from .api.models import (
    AutoFocusState,
    Frame,
    NinaEvent,
    SessionStats,
    StackState,
    TargetBreakdown,
)
from .derive import session_start

_LIGHT = "LIGHT"
_AUTOFOCUS_STARTING = "AUTOFOCUS-STARTING"
_AUTOFOCUS_FINISHED = "AUTOFOCUS-FINISHED"
_STACK_UPDATED = "STACK-UPDATED"
# Announced with the time it expects to resume; nothing announces its end.
_SCHEDULER_WAIT_STARTED = "TS-WAITSTART"
_SEQUENCE_FINISHED = "SEQUENCE-FINISHED"
# Target Scheduler announces a target twice: NEWTARGETSTART when it changes,
# TARGETSTART once per exposure. Both name it, so both count.
_TARGET_STARTED = frozenset({"TS-TARGETSTART", "TS-NEWTARGETSTART"})

# What ends a wait, there being no TS-WAITSTOP: the scheduler moving on, or the
# sequence stopping — `SEQUENCE-FINISHED` fires on a manual stop too.
_WAIT_ENDED_BY = _TARGET_STARTED | {"SEQUENCE-FINISHED"}

# Only a fallback: the rig's own `FocuserSettings.AutoFocusTimeoutSeconds` is
# polled from /profile/show and is 600 on the captured rig, so folding against
# this would call a seven-minute run failed.
DEFAULT_AUTOFOCUS_TIMEOUT = 300.0

# Events that cancel a running autofocus without it reporting: the sequence
# ending, a park, any device dropping, or the sequencer moving on to the next
# exposure. SAFETY-CHANGED counts only when it reports unsafe.
#
# `MOUNT-PARKED` is the one name here no capture holds — the full-night corpus
# has MOUNT-HOMED and no park — so if the wire spells it otherwise, a park
# during a hung run reads as a failure rather than an abort. Harmless to keep
# either way: a name the rig never sends matches nothing.
#
# Read as signals, never counted. IMAGE-SAVE is the one event that cannot be
# deduplicated across the live and replayed paths — the socket sends it with no
# `Time`, `/event-history` with the rig's — so the set can hold two copies of
# one save. Frames are what get counted; events only say that something
# happened.
_INTERRUPTIONS = frozenset({"SEQUENCE-FINISHED", "MOUNT-PARKED", "IMAGE-SAVE"})

_NOTHING = SessionStats(
    session_start=None, image_count=0, light_count=0, integration_seconds=0.0,
    hfr_mean=None, hfr_best=None, hfr_worst=None, star_count_mean=None,
    last_frame=None, by_target=(), by_filter=(),
    autofocus=AutoFocusState(last_finished_at=None, running_since=None, failed=False),
)


def _identity(frame: Frame) -> tuple[datetime, str]:
    return (frame.date, frame.filename)


def _mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return fmean(present) if present else None


def _integration(frames: Sequence[Frame]) -> float:
    return fsum(f.exposure_time for f in frames if f.exposure_time is not None)


def _breakdown(lights: Sequence[Frame],
               key: Callable[[Frame], str | None]) -> tuple[TargetBreakdown, ...]:
    """One row per named group, sorted by name.

    A light whose group name is missing gets no row: a row headed by nothing
    tells a dashboard reader less than its absence does.
    """
    groups: dict[str, list[Frame]] = {}
    for frame in lights:
        name = key(frame)
        if name is not None:
            groups.setdefault(name, []).append(frame)
    return tuple(
        TargetBreakdown(name=name, count=len(members),
                        integration_seconds=_integration(members),
                        hfr_mean=_mean(f.hfr for f in members))
        for name, members in sorted(groups.items())
    )


def _interrupts(event: NinaEvent) -> bool:
    if event.name == "SAFETY-CHANGED":
        return event.data.get("IsSafe") is False
    return event.name in _INTERRUPTIONS or event.name.endswith("-DISCONNECTED")


def _autofocus(events: Iterable[NinaEvent], moment: datetime,
               timeout_seconds: float) -> AutoFocusState:
    """There is no autofocus-failed event; a failure is an unanswered start.

    An interruption landing inside the timeout window aborts the run — nothing
    was wrong with the focuser. One landing after the window has closed shows
    the sequencer carried on past a hung run: it clears `running_since` but the
    failure verdict stands.
    """
    events = list(events)
    finished = max((e.time for e in events if e.name == _AUTOFOCUS_FINISHED), default=None)
    started = max((e.time for e in events if e.name == _AUTOFOCUS_STARTING), default=None)
    if started is None or (finished is not None and started <= finished):
        return AutoFocusState(last_finished_at=finished, running_since=None, failed=False)

    deadline = started + timedelta(seconds=timeout_seconds)
    interruptions = [e.time for e in events if e.time > started and _interrupts(e)]
    if any(t <= deadline for t in interruptions):
        return AutoFocusState(last_finished_at=finished, running_since=None, failed=False)
    return AutoFocusState(
        last_finished_at=finished,
        running_since=None if interruptions else started,
        failed=moment > deadline,
    )


def fold(frames: Iterable[Frame], events: Iterable[NinaEvent],
         generation: str | None, *,
         autofocus_timeout_seconds: float = DEFAULT_AUTOFOCUS_TIMEOUT,
         now: datetime | None = None, rollover_hour: int = 12) -> SessionStats:
    """Frames and events in, one session snapshot out.

    `now` is the clock the session window and the autofocus timeout are measured
    against; with none supplied it is the newest thing observed, which makes the
    fold a function of its arguments alone and so testable against a fixture.
    A caller that wants `autofocus.failed` must pass a real clock: a hung
    autofocus produces nothing newer, so under the derived default the STARTING
    event is itself the newest thing and no time can ever have elapsed.

    The generation filter runs BEFORE the dedupe. A restart leaves a pre-restart
    and a refetched copy of the same `(date, filename)` in the store, and
    deduplicating first would let the stale copy win and then be discarded.
    """
    kept_frames = list({_identity(f): f for f in frames
                        if f.generation == generation}.values())
    kept_events = [e for e in events if e.generation == generation]

    moment = now
    if moment is None:
        observed = [f.date for f in kept_frames] + [e.time for e in kept_events]
        if not observed:
            return _NOTHING
        moment = max(observed)
    start = session_start(moment, rollover_hour)

    session_frames = sorted((f for f in kept_frames if f.date >= start), key=_identity)
    lights = [f for f in session_frames if f.image_type == _LIGHT]
    hfrs = [f.hfr for f in lights if f.hfr is not None]

    return SessionStats(
        session_start=start,
        image_count=len(session_frames),
        light_count=len(lights),
        integration_seconds=_integration(lights),
        hfr_mean=_mean(hfrs),
        hfr_best=min(hfrs, default=None),
        hfr_worst=max(hfrs, default=None),
        star_count_mean=_mean(f.stars for f in lights),
        # session_frames is sorted, so the newest light is the last one.
        last_frame=lights[-1] if lights else None,
        by_target=_breakdown(lights, lambda f: f.target_name),
        by_filter=_breakdown(lights, lambda f: f.filter_name),
        autofocus=_autofocus((e for e in kept_events if e.time >= start),
                             moment, autofocus_timeout_seconds),
    )


def _newest(events: Iterable[NinaEvent], names: Container[str],
            generation: str | None) -> NinaEvent | None:
    """The newest event this generation named, or None if it named none."""
    matching = [event for event in events
                if event.name in names and event.generation == generation]
    return max(matching, key=lambda event: event.time, default=None)


def scheduler_wait(events: Iterable[NinaEvent], generation: str | None, *,
                   now: datetime) -> datetime | None:
    """When the wait Target Scheduler is currently in ends, or None if it is
    not waiting.

    `TS-WAITSTART` announces the time it expects to resume and **there is no
    matching stop event**, so the wait is ended by what follows it: a target
    start, a `SEQUENCE-FINISHED` (a stop leaves the announcement in the history
    still naming a future time), or the time itself passing. Target Scheduler
    re-announces a wait it re-plans, so the newest is the live one.

    It names no reason. Darkness, a target's altitude, moon separation and a
    meridian window all arrive as the same event, so nothing above this can say
    why the rig is waiting.
    """
    wait = _newest(events, {_SCHEDULER_WAIT_STARTED}, generation)
    if wait is None or wait.wait_end is None or wait.wait_end <= now:
        return None
    ended = _newest(events, _WAIT_ENDED_BY, generation)
    # Strictly after: the announcement and the event that ends it never share a
    # timestamp, and a wait that ended itself would be a contradiction.
    if ended is not None and ended.time > wait.time:
        return None
    return wait.wait_end


def latest_stack(events: Iterable[NinaEvent],
                 generation: str | None) -> StackState | None:
    """The stack `STACK-UPDATED` last reported, or None if none has.

    Generation-filtered like the fold, so a stack from the previous N.I.N.A.
    process is not offered as the current one — the plugin's stacks do not
    survive a restart.

    A payload missing `Target` or `Filter` yields None rather than a pair with
    an empty half: both are path segments, and `/livestack/image//O` is a route
    that does not exist.
    """
    newest = _newest(events, {_STACK_UPDATED}, generation)
    if newest is None:
        return None
    target = newest.data.get("Target")
    filter_name = newest.data.get("Filter")
    if not isinstance(target, str) or not isinstance(filter_name, str):
        return None
    if not target or not filter_name:
        return None
    return StackState(
        target=target, filter_name=filter_name, updated=newest.time
    )


_RECENT_FRAMES_LIMIT = 20
"""Comfortably covers a dashboard card's thumbnail strip; nowhere near a
Target Scheduler night's frame count, so this stays cheap every tick."""


def recent_frames(frames: Iterable[Frame], generation: str | None) -> tuple[Frame, ...]:
    """The newest frames this process saved, of any type, newest first,
    bounded — what a dashboard's thumbnail strip and ADU histogram need.

    `heapq.nlargest`, not a full sort: a Target Scheduler night's frame count
    only has to be walked once, not ordered end to end for 20 of them.
    """
    kept = (f for f in frames if f.generation == generation)
    return tuple(heapq.nlargest(_RECENT_FRAMES_LIMIT, kept, key=_identity))


def newest_frame(frames: Iterable[Frame], generation: str | None) -> Frame | None:
    """The newest frame this process saved, of any type — what `image.last_frame`
    renders.

    Deliberately outside the session window that `fold` applies: the rig's
    image history does not roll over at local noon, so the frame the route
    renders at 13:00 is still last night's. The single-frame case of
    `recent_frames` — one ordering rule, not two.
    """
    newest = recent_frames(frames, generation)
    return newest[0] if newest else None


def latest_target(events: Iterable[NinaEvent],
                  generation: str | None) -> str | None:
    """The target the newest `TS-*TARGETSTART` named, or None if none has.

    Target Scheduler only: a plain N.I.N.A. sequence emits no such event and
    names its target in the `/sequence/json` tree instead (`sequence.py`).
    """
    start = _newest(events, _TARGET_STARTED, generation)
    if start is None:
        return None
    name = start.data.get("TargetName")
    return name if isinstance(name, str) and name else None

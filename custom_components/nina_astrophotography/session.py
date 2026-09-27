"""The session fold: pure, stateless and idempotent, so push, poll and
/event-history replay give the same result in any order.

Frame identity is `(Date, Filename)`. `Date` is the save time, after the
exposure and download, so when a frame was taken is `Date - ExposureTime`.

Aggregates are computed from a sorted iteration, never accumulated: float sums
depend on order. A N.I.N.A. restart is handled by filtering on the generation
tag, never by clearing.
"""

from collections.abc import Callable, Container, Iterable, Sequence
from datetime import datetime, timedelta
import heapq
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
# NEWTARGETSTART fires on a change, TARGETSTART once per exposure; both name it.
_TARGET_STARTED = frozenset({"TS-TARGETSTART", "TS-NEWTARGETSTART"})

# There is no TS-WAITSTOP. SEQUENCE-FINISHED fires on a manual stop too.
_WAIT_ENDED_BY = _TARGET_STARTED | {"SEQUENCE-FINISHED"}

# Not GUIDER-DITHER, which N.I.N.A. raises even for a dither it skipped.
_GUIDER_STARTED = "GUIDER-START"
_GUIDER_STOPPED = "GUIDER-STOP"
_GUIDER_STARTED_OR_STOPPED = frozenset({_GUIDER_STARTED, _GUIDER_STOPPED})

# Used only until the profile's `AutoFocusTimeoutSeconds` is read.
DEFAULT_AUTOFOCUS_TIMEOUT = 300.0

# Events that end a running autofocus without it reporting; also any
# `-DISCONNECTED`, and SAFETY-CHANGED to unsafe. `MOUNT-PARKED` is from the
# spec, unconfirmed on the wire. Signals only, never counted: IMAGE-SAVE can
# appear twice, once pushed and once replayed.
_INTERRUPTIONS = frozenset({"SEQUENCE-FINISHED", "MOUNT-PARKED", "IMAGE-SAVE"})

_RECENT_LIGHTS_LIMIT = 60
"""A dashboard sparkline's width."""

_NOTHING = SessionStats(
    session_start=None,
    image_count=0,
    light_count=0,
    integration_seconds=0.0,
    hfr_mean=None,
    hfr_best=None,
    hfr_worst=None,
    star_count_mean=None,
    last_frame=None,
    recent_lights=(),
    by_target=(),
    by_filter=(),
    autofocus=AutoFocusState(last_finished_at=None, running_since=None, failed=False),
)


def _identity(frame: Frame) -> tuple[datetime, str]:
    return (frame.date, frame.filename)


def _mean(values: Iterable[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return fmean(present) if present else None


def _integration(frames: Sequence[Frame]) -> float:
    return fsum(f.exposure_time for f in frames if f.exposure_time is not None)


def _breakdown(
    lights: Sequence[Frame], key: Callable[[Frame], str | None]
) -> tuple[TargetBreakdown, ...]:
    """One row per named group, sorted by name; unnamed lights get none."""
    groups: dict[str, list[Frame]] = {}
    for frame in lights:
        name = key(frame)
        if name is not None:
            groups.setdefault(name, []).append(frame)
    return tuple(
        TargetBreakdown(
            name=name,
            count=len(members),
            integration_seconds=_integration(members),
            hfr_mean=_mean(f.hfr for f in members),
        )
        for name, members in sorted(groups.items())
    )


def _interrupts(event: NinaEvent) -> bool:
    if event.name == "SAFETY-CHANGED":
        return event.data.get("IsSafe") is False
    return event.name in _INTERRUPTIONS or event.name.endswith("-DISCONNECTED")


def _autofocus(
    events: Iterable[NinaEvent], moment: datetime, timeout_seconds: float
) -> AutoFocusState:
    """A failed autofocus is a start unanswered past the timeout; there is no
    failure event.

    An interruption inside the timeout aborts the run, which is no failure.
    One after it clears `running_since`, but the verdict stands.
    """
    events = list(events)
    finished = max(
        (e.time for e in events if e.name == _AUTOFOCUS_FINISHED), default=None
    )
    started = max(
        (e.time for e in events if e.name == _AUTOFOCUS_STARTING), default=None
    )
    if started is None or (finished is not None and started <= finished):
        return AutoFocusState(
            last_finished_at=finished, running_since=None, failed=False
        )

    deadline = started + timedelta(seconds=timeout_seconds)
    interruptions = [e.time for e in events if e.time > started and _interrupts(e)]
    if any(t <= deadline for t in interruptions):
        return AutoFocusState(
            last_finished_at=finished, running_since=None, failed=False
        )
    return AutoFocusState(
        last_finished_at=finished,
        running_since=None if interruptions else started,
        failed=moment > deadline,
    )


def fold(
    frames: Iterable[Frame],
    events: Iterable[NinaEvent],
    generation: str | None,
    *,
    autofocus_timeout_seconds: float = DEFAULT_AUTOFOCUS_TIMEOUT,
    now: datetime | None = None,
    rollover_hour: int = 12,
) -> SessionStats:
    """Frames and events in, one session snapshot out.

    `now` defaults to the newest thing observed, which keeps the fold a pure
    function of its arguments; `autofocus.failed` needs a real clock, since a
    hung run produces nothing newer.

    The generation filter runs before the dedupe, or a stale pre-restart copy
    of a frame could win and then be filtered out.
    """
    kept_frames = list(
        {_identity(f): f for f in frames if f.generation == generation}.values()
    )
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
        recent_lights=tuple(lights[-_RECENT_LIGHTS_LIMIT:]),
        by_target=_breakdown(lights, lambda f: f.target_name),
        by_filter=_breakdown(lights, lambda f: f.filter_name),
        autofocus=_autofocus(
            (e for e in kept_events if e.time >= start),
            moment,
            autofocus_timeout_seconds,
        ),
    )


def _newest(
    events: Iterable[NinaEvent], names: Container[str], generation: str | None
) -> NinaEvent | None:
    """The newest event this generation named, or None if it named none."""
    matching = [
        event
        for event in events
        if event.name in names and event.generation == generation
    ]
    return max(matching, key=lambda event: event.time, default=None)


def scheduler_wait(
    events: Iterable[NinaEvent], generation: str | None, *, now: datetime
) -> datetime | None:
    """When Target Scheduler's current wait ends, or None if it is not waiting.

    `TS-WAITSTART` names its end time and has no stop event, so a target
    start, a `SEQUENCE-FINISHED`, or the time passing ends it. A re-planned
    wait is re-announced, so the newest is live. The event names no reason.
    """
    wait = _newest(events, {_SCHEDULER_WAIT_STARTED}, generation)
    if wait is None or wait.wait_end is None or wait.wait_end <= now:
        return None
    ended = _newest(events, _WAIT_ENDED_BY, generation)
    if ended is not None and ended.time > wait.time:
        return None
    return wait.wait_end


def latest_stack(
    events: Iterable[NinaEvent], generation: str | None
) -> StackState | None:
    """The stack `STACK-UPDATED` last reported, or None if none has.

    Stacks do not survive a N.I.N.A. restart, hence the generation filter.
    `Target` and `Filter` are both path segments, so neither may be empty.
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
    return StackState(target=target, filter_name=filter_name, updated=newest.time)


_RECENT_FRAMES_LIMIT = 20
"""Covers a card's thumbnail strip."""


def recent_frames(frames: Iterable[Frame], generation: str | None) -> tuple[Frame, ...]:
    """The newest frames this process saved, of any type, newest first."""
    kept = (f for f in frames if f.generation == generation)
    return tuple(heapq.nlargest(_RECENT_FRAMES_LIMIT, kept, key=_identity))


def newest_frame(frames: Iterable[Frame], generation: str | None) -> Frame | None:
    """The newest frame this process saved, of any type.

    Outside the session window: the image history does not roll over.
    """
    newest = recent_frames(frames, generation)
    return newest[0] if newest else None


def latest_target(events: Iterable[NinaEvent], generation: str | None) -> str | None:
    """The target the newest `TS-*TARGETSTART` named, or None if none has.

    Target Scheduler only; a plain sequence names its target in
    `/sequence/json` (`sequence.py`).
    """
    start = _newest(events, _TARGET_STARTED, generation)
    if start is None:
        return None
    name = start.data.get("TargetName")
    return name if isinstance(name, str) and name else None


def pending_guider_stop(
    events: Iterable[NinaEvent], generation: str | None
) -> datetime | None:
    """When the newest `GUIDER-STOP` was, if no `GUIDER-START` has followed it.

    A stop that interrupts a guide exposure can leave `GuiderInfo.State` at
    `LostLock` until the next start (PHD2 clears its lock position after
    reporting looping stopped), which reads like a guider hunting for its
    star. The time identifies the stop to `polling.GuiderStopLatch`.
    """
    newest = _newest(events, _GUIDER_STARTED_OR_STOPPED, generation)
    return (
        newest.time if newest is not None and newest.name == _GUIDER_STOPPED else None
    )

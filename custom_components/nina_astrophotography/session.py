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

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from math import fsum
from statistics import fmean

from .api.models import AutoFocusState, Frame, NinaEvent, SessionStats, TargetBreakdown
from .derive import session_start

_LIGHT = "LIGHT"
_AUTOFOCUS_STARTING = "AUTOFOCUS-STARTING"
_AUTOFOCUS_FINISHED = "AUTOFOCUS-FINISHED"
# Events that cancel a running autofocus without it reporting: the sequence
# ending, a park, any device dropping, or the sequencer moving on to the next
# exposure. SAFETY-CHANGED counts only when it reports unsafe.
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
         generation: str | None, *, autofocus_timeout_seconds: float = 300.0,
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

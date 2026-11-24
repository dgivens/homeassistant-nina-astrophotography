"""The polling decisions, as state machines with no I/O, clock or Home
Assistant; the coordinator composes them.

Nothing here clears anything: a N.I.N.A. restart is a generation change, which
the fold filters on.
"""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
import time
from typing import Literal

from .api.models import (
    EquipmentSnapshot,
    FlatDeviceModel,
    Frame,
    NinaEvent,
    SequenceWait,
    SequenceWaitKind,
    WeatherModel,
)
from .session import CoverMove


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


# What N.I.N.A. reports a cover moving, or stuck, as; and a driver's fault.
_COVER_FAULTS = frozenset({"NeitherOpenNorClosed", "Error"})


class CoverClosedLatch:
    """Whether the newest frame is a light saved behind the flat panel's
    closed cover.

    "A sequence running with the cover closed" is no test: flats and darks run
    that way. What gives a light away is arriving after the cover was seen
    closed, so the latch keeps the newest frame at the moment a connected
    panel first reads `Closed`, and flags a newer one.

    It clears on a connected reading other than `Closed`, or once N.I.N.A.
    reports the cover opened after it latched. A disconnect clears nothing:
    a panel powered off once its cover has moved leaves it where it was, so a
    cover that jammed shut, or an open N.I.N.A. never reported, keeps
    flagging every light. An open N.I.N.A. reported before the cover was seen
    closed means the cover was closed outside N.I.N.A., and the latch holds.

    Arriving later is not enough on its own. N.I.N.A. saves in the
    background, so the next instruction — closing the cover for flats — can
    run before the last light's `IMAGE-SAVE`. A light whose exposure began
    before N.I.N.A. reported the close is therefore not flagged. Both times
    are the rig's; without a reported close, arrival order decides.

    Pushed events publish with the last poll's snapshot, so a reading is
    acted on when it changes, not each time it is seen: a stale `Closed`
    after a reported open would otherwise latch again.
    """

    def __init__(self) -> None:
        self._reading: str | None = None
        self._closed = False
        self._before: tuple[datetime, str] | None = None
        self._latched_with: CoverMove | None = None

    def update(
        self,
        flat: FlatDeviceModel | None,
        newest: Frame | None,
        move: CoverMove | None,
    ) -> bool:
        """`move`: the newest cover move N.I.N.A. reported, `None` if none."""
        if flat is not None and flat.connected:
            if flat.cover_state != "Closed":
                self._closed = False
            elif self._reading != "Closed" and not self._closed:
                self._closed = True
                self._before = None if newest is None else newest.identity
                self._latched_with = move
            self._reading = flat.cover_state
        else:
            # A reconnect reading `Closed` is a fresh sighting.
            self._reading = None
        if (
            self._closed
            and move is not None
            and not move.closed
            and move != self._latched_with
        ):
            self._closed = False
        if (
            not self._closed
            or newest is None
            or newest.image_type != "LIGHT"
            or newest.identity == self._before
        ):
            return False
        if move is None or not move.closed:
            return True
        # `date` is the save time, so this start is late by the download and
        # the save: a light shorter than those can still be flagged.
        started = newest.date - timedelta(seconds=newest.exposure_time or 0)
        return started >= move.time


class CoverFaultHold:
    """A disconnected flat panel's last cover reading, while that reading was
    a fault — part-way or `Error` — that N.I.N.A. has not resolved since.

    A panel powered off after a move leaves its cover where it was, and a
    disconnected panel reads nothing, so without this a cover left part-way
    or in error would vanish with the panel. What resolves it is a cover
    move N.I.N.A. reported after the cover was last seen at rest: N.I.N.A.
    raises `FLAT-COVER-OPENED` and `-CLOSED` only once the move has finished.

    The baseline is taken when the cover is first seen at rest, or while the
    panel is down and holds nothing, since nothing moves a disconnected
    cover; never when it is first seen part-way: a poll can still read a
    cover part-way after N.I.N.A. has reported it open, and a baseline taken
    then would hold the finished move as a fault.
    """

    def __init__(self) -> None:
        self._read = False
        self._reading: str | None = None
        self._since: CoverMove | None = None

    def update(
        self, flat: FlatDeviceModel | None, move: CoverMove | None
    ) -> str | None:
        """The held fault reading, or `None`: always while connected."""
        if flat is not None and flat.connected:
            reading = flat.cover_state
            if not self._read or (
                reading not in _COVER_FAULTS and reading != self._reading
            ):
                self._since = move
            self._read = True
            self._reading = reading
            return None
        # `move` reads `None` again after a N.I.N.A. restart, which moved nothing.
        if self._reading in _COVER_FAULTS and (move is None or move == self._since):
            return self._reading
        self._read, self._reading, self._since = True, None, move
        return None


# Channels a working station's readings drift in, minute to minute. The rest
# can legitimately hold all night: no rain, no wind, a clear sky, 0 lx.
DRIFTING_CHANNELS = frozenset(
    {"temperature", "humidity", "dew_point", "pressure", "sky_temperature"}
)
# N.I.N.A.'s own web sources, by the `Name` each gives itself. Each refreshes
# every ten minutes at best, from a gridded model or a provider's cache.
_WEB_SOURCES = frozenset(
    {"OpenMeteo", "OpenWeatherMap", "TheWeatherCompany", "Weather Underground"}
)
# Brighter than this with the sun below `_NIGHT_ALTITUDE` is no night sky: a
# full moon gives about 0.25 lx.
_NIGHT_SKY_LUX = 10.0
_NIGHT_ALTITUDE = -12.0


@dataclass(frozen=True, slots=True)
class FreezeWindows:
    """How long every reading may hold before the source counts as frozen."""

    station: timedelta
    web: timedelta
    """For `_WEB_SOURCES`, which refresh less often than hardware."""
    lit_night: timedelta
    """For a sky brighter than `_NIGHT_SKY_LUX` after astronomical dusk,
    which is a daytime reading held into the night."""


class WeatherFreeze:
    """Since when a connected weather source's readings have stood still.

    N.I.N.A. reports no age for a reading: `WeatherData` carries no update
    time, and ASCOM's `TimeSinceLastUpdate` is not read. A driver that stops
    updating, or throws on every read so that N.I.N.A. serves its last good
    value, keeps `Connected: true` and its last values. What gives it away is
    every channel holding bit-identical across polls.

    Every channel has to hold, so a source that mixes sensors is flagged only
    when all of them stop: fewer false alarms, at the cost of missing one
    stuck sensor beside a working one. A source reporting none of
    `DRIFTING_CHANNELS` is never judged, since its channels can all hold for
    hours on a still, clear night.

    Nothing resets the baseline but a change of readings: a source that
    reconnects, or a N.I.N.A. restart that reconnects it, serving the values
    it froze on is still frozen, and the time it was down counts. The first
    poll after it comes back is not judged: a source N.I.N.A. queries in the
    background, such as The Weather Company, serves the readings it had
    before the disconnect until its first answer. Measured between the polls
    that read the source, not against the clock.
    """

    def __init__(self, windows: FreezeWindows) -> None:
        self._windows = windows
        self._readings: Mapping[str, float | None] | None = None
        self._since: datetime | None = None
        self._last: datetime | None = None
        self._window: timedelta | None = None
        self._settled = False

    def observe(
        self,
        weather: WeatherModel | None,
        read_at: datetime,
        sun_altitude: float | None,
    ) -> None:
        """Take one poll's reading: `read_at` is when it was read, and
        `sun_altitude` the sun's at the site then, `None` with no site.
        """
        if (
            weather is None
            or not weather.connected
            or not any(
                weather.channels.get(channel) is not None
                for channel in DRIFTING_CHANNELS
            )
        ):
            self._window = None
            return
        self._settled = self._window is not None or self._readings is None
        if weather.channels != self._readings:
            self._readings, self._since = dict(weather.channels), read_at
        self._last = read_at
        windows = self._windows
        self._window = (
            windows.web if weather.meta.name in _WEB_SOURCES else windows.station
        )
        sky = weather.channels.get("sky_brightness")
        dark = sun_altitude is not None and sun_altitude < _NIGHT_ALTITUDE
        if dark and sky is not None and sky > _NIGHT_SKY_LUX:
            self._window = min(self._window, windows.lit_night)

    @property
    def frozen_since(self) -> datetime | None:
        """The first poll that read the held readings, once they have held
        for the source's window; `None` before that, and while the source is
        not judged.
        """
        if (
            not self._settled
            or self._window is None
            or self._since is None
            or self._last is None
        ):
            return None
        return self._since if self._last - self._since >= self._window else None


@dataclass
class RestartDetector:
    """Detects a N.I.N.A. restart.

    `/application-start` changing is authoritative; the frame count going
    backwards also reports one, which covers an `/application-start` that
    reads null. A first read has no baseline, so it is never a restart.
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


class OutageGrace:
    """Whether a failed poll may keep the last data rather than fail.

    A remote link drops a poll routinely while the rig images on. Failing at
    once turns every entity `unavailable` for a tick, which the recorder keeps
    and an automation on `unavailable` fires on.

    Measured from the first failure, not the last answer: at a slow poll
    interval plus a request timeout, the first failure already lands more than
    the period after the last answer.
    """

    def __init__(self, period: float) -> None:
        self._period = period
        self._failing_since: float | None = None

    def answered(self) -> None:
        """Record that N.I.N.A. answered, which a refusal also is."""
        self._failing_since = None

    def failed(self, now: float | None = None) -> bool:
        """Record a failure; whether the outage is still inside the grace."""
        moment = time.monotonic() if now is None else now
        if self._failing_since is None:
            self._failing_since = moment
        return moment - self._failing_since < self._period


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


WaitKind = Literal["scheduler"] | SequenceWaitKind


@dataclass(frozen=True, slots=True)
class Wait:
    """A wait the rig is in: Target Scheduler's, or an instruction of the
    sequence's own.
    """

    kind: WaitKind
    started: datetime
    """When a read first showed it, which lags its real start by up to a poll."""
    ends: datetime | None
    """Named by Target Scheduler and Wait for Time, and estimated by N.I.N.A.
    for an altitude wait; a span names none."""
    span_seconds: float | None
    """A Wait for Time Span's length; `None` on the other waits."""


@dataclass(frozen=True, slots=True)
class EndedWait:
    """A wait that is over."""

    kind: WaitKind
    started: datetime
    ended: datetime
    """Its named end where it had one, else the read that found it over. An
    altitude wait's estimate is not a named end."""
    span_seconds: float | None


_RECENT_WAITS = 10
"""Enough to keep a long wait behind the short settles that follow it."""

_SPAN_GRACE = timedelta(seconds=TierSchedule.SEQUENCE_IDLE)
"""A span is first seen up to one slow poll after it starts."""

_UNPLACED_WAIT = timedelta(hours=12)
"""How long a wait with no end to hold it to may run, and the least an
altitude wait with an estimate may."""

_ALTITUDE_OVERRUN = timedelta(hours=1)
"""How far past its estimate an altitude wait may run, where twelve hours
from its first read is sooner."""

_DAY_LATER = timedelta(hours=12)
"""An estimate this much later than the one held is the same minute placed a
day on, once the wait has run past it. N.I.N.A.'s own re-estimates move by
minutes, about ten at a time on a custom horizon."""


class WaitLedger:
    """The wait in progress, and the ones that have ended, across reads.

    A read only shows that a wait was running, so a short one is caught on
    some reads and missed on others. A wait still shown running past the
    point it can have ended is over: a Wait for Time at its end, a span its
    `Delay` and one slow poll after it was first seen, an altitude wait an
    hour past its estimate, or twelve hours after it was first seen where
    that is later or it has none. A status carried in from a loaded sequence
    file can show a wait running that never will, and this bounds it.

    Reads cannot tell one pass of a loop from the next at the same path. A
    span still shown past its length is taken as the next pass, so a loop of
    long spans stays waiting; a Wait for Time or an altitude wait that expires
    stays over until a read shows a different wait.
    """

    def __init__(self) -> None:
        self._current: Wait | None = None
        self._key: tuple | None = None
        self._expired: tuple | None = None
        self._ended: deque[EndedWait] = deque(maxlen=_RECENT_WAITS)

    @property
    def current(self) -> Wait | None:
        return self._current

    @property
    def ended(self) -> tuple[EndedWait, ...]:
        """Newest first."""
        return tuple(reversed(self._ended))

    def observe(
        self,
        scheduled_end: datetime | None,
        step: tuple[tuple[int, ...], SequenceWait] | None,
        *,
        now: datetime,
    ) -> None:
        """One read: Target Scheduler's wait end, and the running wait
        instruction with its path in the tree. Target Scheduler's wins: its
        own steps are not on the wire.
        """
        seen: tuple[tuple, WaitKind, datetime | None, float | None] | None = None
        if scheduled_end is not None:
            seen = (("scheduler",), "scheduler", scheduled_end, None)
        elif step is not None:
            path, wait = step
            seen = (("step", path), wait.kind, wait.ends, wait.span_seconds)
        key = None if seen is None else seen[0]
        if key != self._key:
            self._end(now)
            self._key = key
            self._expired = None
        if seen is None or key == self._expired:
            return
        _, kind, ends, span = seen
        held = None if self._current is None else self._current.ends
        if kind == "altitude" and held is not None:
            # A dateless estimate the wait has overrun reads as tomorrow's,
            # and one read with none (`--`) is not the wait's last word.
            if ends is None or ends - held > _DAY_LATER:
                ends = held
        started = now if self._current is None else self._current.started
        self._current = Wait(kind, started, ends, span)
        if self._expiry(self._current) <= now:
            self._end(now)
            if span is None:
                self._expired = key
            else:
                self._current = Wait(kind, now, ends, span)

    def _expiry(self, wait: Wait) -> datetime:
        if wait.kind == "altitude":
            unplaced = wait.started + _UNPLACED_WAIT
            if wait.ends is None:
                return unplaced
            return max(unplaced, wait.ends + _ALTITUDE_OVERRUN)
        if wait.ends is not None:
            return wait.ends
        if wait.span_seconds is not None:
            return wait.started + timedelta(seconds=wait.span_seconds) + _SPAN_GRACE
        return wait.started + _UNPLACED_WAIT

    def _end(self, now: datetime) -> None:
        wait = self._current
        if wait is None:
            return
        # An altitude wait's estimate is not when it ended.
        named = None if wait.kind == "altitude" else wait.ends
        ended = now if named is None else min(named, now)
        self._ended.append(EndedWait(wait.kind, wait.started, ended, wait.span_seconds))
        self._current = None

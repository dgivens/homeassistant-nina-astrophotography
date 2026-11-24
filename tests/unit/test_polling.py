"""The pure polling decisions: restart detection, the reseed guard, the tiers.

Home-Assistant-free by design — the coordinator composes these, so they can be
tested as functions of their arguments rather than through a config entry.
"""

from dataclasses import fields, replace
from datetime import datetime, timedelta, timezone

from nina_astrophotography.api.models import (
    EquipmentSnapshot,
    FlatDeviceModel,
    Frame,
    NinaEvent,
    SequenceWait,
    SequenceWaitKind,
    WeatherModel,
)
from nina_astrophotography.api.v2.mapper import map_equipment_info, map_frame
from nina_astrophotography.polling import (
    DRIFTING_CHANNELS,
    CoverClosedLatch,
    CoverFaultHold,
    EventLedger,
    FreezeWindows,
    GuiderStopLatch,
    ReseedGuard,
    RestartDetector,
    TierSchedule,
    WaitLedger,
    WeatherFreeze,
    imaging,
)
from nina_astrophotography.session import CoverMove
import pytest

from helpers import load_fixture as load

# A next-evening restart emits 21:00 events against an 05:30 mark.
T1 = "2026-09-03T21:00:00-05:00"
T2 = "2026-09-04T05:30:00-05:00"


@pytest.mark.parametrize(
    ("before", "after", "restarted"),
    [
        # /application-start is authoritative.
        (("2026-09-04T10:58:59", 122), ("2026-09-04T13:54:50.907", 0), True),
        # A monotonic counter going backwards corroborates on the same tier.
        (("2026-09-04T10:58:59", 122), ("2026-09-04T10:58:59", 3), True),
        # Steady state.
        (("2026-09-04T10:58:59", 122), ("2026-09-04T10:58:59", 123), False),
        # First read: no baseline exists, so this is not a restart.
        ((None, 0), ("2026-09-04T10:58:59", 122), False),
        # An unreadable /application-start is still corroborated by the counter,
        # which is on the same tier.
        (("2026-09-04T10:58:59", 122), (None, 0), True),
    ],
    ids=[
        "application-start moved",
        "count fell",
        "steady",
        "first read",
        "application-start unreadable",
    ],
)
def test_the_restart_signals(before, after, restarted) -> None:
    detector = RestartDetector()
    detector.update(*before)
    assert detector.observe(*after) is restarted


def test_an_unreadable_application_start_does_not_erase_the_baseline() -> None:
    """Missing information, not a new process. Erasing it would leave the next
    tick with no baseline, and so blind to the restart that tick reports.
    """
    detector = RestartDetector()
    detector.update("2026-09-04T10:58:59", 122)
    detector.update(None, 122)
    assert detector.observe("2026-09-04T13:54:50.907", 122) is True


@pytest.mark.parametrize(
    ("observations", "fires"),
    [
        ([(122, 122)], [False]),
        ([(122, 123)], [False]),
        ([(122, 123), (122, 123)], [False, True]),
        ([(122, 123), (122, 122), (122, 123)], [False, False, False]),
        ([(122, 123)] * 4, [False, True, False, True]),
    ],
    ids=["invariant holds", "one tick", "two ticks", "a match resets", "firing rearms"],
)
def test_the_reseed_guard_needs_the_mismatch_twice(observations, fires) -> None:
    """A frame saved between the ?count=true read and the history read fails
    the invariant transiently, and an immediate reseed answers that with a
    62 KB refetch every time it happens.
    """
    guard = ReseedGuard()
    assert [guard.check(*observation) for observation in observations] == fires


def test_a_mismatch_that_survives_a_reseed_latches_until_the_count_moves() -> None:
    """A structural difference — an item the mapper skips, two the fold merges
    — no refetch can close, so it must stop asking for one.
    """
    guard = ReseedGuard()
    assert [guard.check(122, 123), guard.check(122, 123)] == [False, True]
    assert guard.settle(122, 123) is True
    assert [guard.check(122, 123) for _ in range(3)] == [False, False, False]
    assert [guard.check(122, 124), guard.check(122, 124)] == [False, True]


def test_a_reseed_that_closes_the_gap_leaves_the_guard_armed() -> None:
    guard = ReseedGuard()
    assert guard.settle(122, 122) is False
    assert [guard.check(122, 123), guard.check(122, 123)] == [False, True]


def test_a_tier_is_due_when_it_has_never_run_and_not_again_until_its_interval() -> None:
    schedule = TierSchedule()
    assert schedule.due("sequence", 1000.0) is True
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1000.0 + TierSchedule.SEQUENCE_IDLE - 1) is False
    assert schedule.due("sequence", 1000.0 + TierSchedule.SEQUENCE_IDLE) is True


def test_an_unknown_tier_is_an_error_rather_than_a_default_cadence() -> None:
    with pytest.raises(KeyError):
        TierSchedule().due("frobnicate", 1000.0)


def test_a_sequence_refetch_is_debounced() -> None:
    """TS-TARGETSTART fires once per exposure — 27 in 3.8 h — and its payload
    already carries everything a refetch would fetch.
    """
    schedule = TierSchedule()
    assert schedule.request_sequence_refetch(1000.0) is True
    assert (
        schedule.request_sequence_refetch(1000.0 + TierSchedule.SEQUENCE_DEBOUNCE - 1)
        is False
    )
    assert (
        schedule.request_sequence_refetch(1000.0 + TierSchedule.SEQUENCE_DEBOUNCE)
        is True
    )


def test_a_refused_refetch_an_event_asked_for_stays_queued() -> None:
    """The debounce is a rate limit, not a veto. Dropping the request loses the
    event's ask until the five-minute floor comes round.
    """
    schedule = TierSchedule()
    assert schedule.request_sequence_refetch(1000.0, requeue="/sequence/json") is True
    assert schedule.request_sequence_refetch(1001.0, requeue="/sequence/json") is False
    assert schedule.take_pending() == {"/sequence/json"}


def test_events_queue_endpoints_once_and_taking_them_drains_the_queue() -> None:
    """Two events naming the same endpoint are one refetch, and the tick that
    performs it must clear the queue or it re-reads on every tick after.
    """
    schedule = TierSchedule()
    schedule.add_pending("/profile/show")
    schedule.add_pending("/profile/show")
    assert schedule.take_pending() == {"/profile/show"}
    assert schedule.take_pending() == set()


@pytest.mark.parametrize(
    ("imaging", "elapsed", "due"),
    [
        (True, TierSchedule.SEQUENCE_IMAGING - 1, False),
        (True, TierSchedule.SEQUENCE_IMAGING, True),
        (False, TierSchedule.SEQUENCE_IMAGING, False),
        (False, TierSchedule.SEQUENCE_IDLE, True),
    ],
    ids=["imaging, early", "imaging, 30 s", "idle, 30 s", "idle, 5 min"],
)
def test_the_sequence_cadence_follows_the_imaging_flag(imaging, elapsed, due) -> None:
    schedule = TierSchedule()
    schedule.set_imaging(imaging)
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1000.0 + elapsed) is due


def test_sequence_finished_drops_the_cadence_without_waiting_for_the_heuristic() -> (
    None
):
    """SEQUENCE-FINISHED fires once at session end; the activity heuristic
    would keep the tier at 30 s for another five minutes after the last frame.
    """
    schedule = TierSchedule()
    schedule.set_imaging(True)
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1040.0) is True
    schedule.sequence_finished()
    assert schedule.due("sequence", 1040.0) is False


def test_set_imaging_cannot_undo_sequence_finished_until_activity_returns() -> None:
    """The heuristic is still the authority: a rising count after the event
    puts the tier back at 30 s, so the drop is a cadence change and not a latch.
    """
    schedule = TierSchedule()
    schedule.sequence_finished()
    schedule.set_imaging(True)
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1030.0) is True


@pytest.mark.parametrize(
    ("count", "last_count", "exposing", "since_save", "expected"),
    [
        (28, 27, False, 9999.0, True),
        (27, 27, True, 9999.0, True),
        (27, 27, False, 299.0, True),
        (27, 27, False, 300.0, False),
        (27, 27, None, 9999.0, False),
    ],
    ids=[
        "count rose",
        "camera exposing",
        "a recent IMAGE-SAVE",
        "the last save aged out",
        "nothing happening",
    ],
)
def test_imaging_is_inferred_from_activity(
    count, last_count, exposing, since_save, expected
) -> None:
    """Never from /sequence/json node status: three nodes read RUNNING on the
    idle rig with zero frames captured, which would pin the tier at 30 s.
    """
    snapshot = _snapshot_with_camera(is_exposing=exposing)
    assert imaging(snapshot, count, last_count, since_save) is expected


def test_imaging_survives_a_camera_that_has_never_been_observed() -> None:
    """Every device slot is None until it has carried a DeviceId, and the
    heuristic runs on the first tick.
    """
    snapshot = EquipmentSnapshot(*[None] * len(fields(EquipmentSnapshot)))
    assert imaging(snapshot, 28, 27, 9999.0) is True
    assert imaging(snapshot, 27, 27, 9999.0) is False


def _snapshot_with_camera(*, is_exposing: bool | None) -> EquipmentSnapshot:
    """The captured snapshot with one field varied — the corpus holds the
    camera exposing, and no capture can hold both branches.
    """
    camera = map_equipment_info(load("imaging_guiding_equipment_info.json")).camera
    assert camera is not None
    blanks = {f.name: None for f in fields(EquipmentSnapshot)}
    return EquipmentSnapshot(
        **{**blanks, "camera": replace(camera, is_exposing=is_exposing)}
    )


@pytest.mark.parametrize(
    ("marked", "asked", "seen"),
    [
        (("IMAGE-SAVE", T1, "g1"), ("IMAGE-SAVE", T1, "g1"), True),
        (("IMAGE-SAVE", T1, "g1"), ("IMAGE-SAVE", T2, "g1"), False),
        (("IMAGE-SAVE", T1, "g1"), ("AUTOFOCUS-FINISHED", T1, "g1"), False),
        # The mark is scoped to the generation: a restart emits fresh
        # timestamps that can be EARLIER than a retained one, and a global mark
        # would filter a whole evening's replay away as already-seen.
        (("IMAGE-SAVE", T2, "g1"), ("IMAGE-SAVE", T1, "g2"), False),
    ],
    ids=["the same event", "another time", "another name", "another generation"],
)
def test_the_event_ledger_identifies_an_event_by_generation_name_and_time(
    marked, asked, seen
) -> None:
    ledger = EventLedger()
    ledger.mark(_event(*marked))
    assert ledger.seen(_event(*asked)) is seen


def _event(name: str, time: str, generation: str) -> NinaEvent:
    return NinaEvent(
        name=name, time=datetime.fromisoformat(time), data={}, generation=generation
    )


# A stop tonight and the one before it; only identity matters, never order.
STOP = datetime.fromisoformat("2026-09-18T21:50:19-05:00")
EARLIER_STOP = datetime.fromisoformat("2026-09-18T19:02:00-05:00")


@pytest.mark.parametrize(
    ("polled", "stop", "stopped"),
    [
        ([], STOP, True),
        ([("LostLock", STOP), ("Stopped", STOP)], STOP, True),
        ([("LostLock", STOP), ("Looping", STOP)], STOP, False),
        ([("Guiding", STOP)], STOP, True),
        ([("LostLock", STOP), ("Calibrating", STOP), ("LostLock", STOP)], STOP, False),
        ([("LostLock", EARLIER_STOP), ("Guiding", EARLIER_STOP)], STOP, True),
        ([("LostLock", STOP), ("Looping", STOP)], STOP + timedelta(seconds=2), False),
        (
            [("LostLock", STOP), ("Looping", STOP), ("Guiding", None)],
            STOP + timedelta(seconds=40),
            True,
        ),
        ([], None, False),
    ],
    ids=[
        "never polled",
        "only stopped states polled",
        "polled looping after the stop",
        "running on the stop's first poll",
        "a lock lost after running again",
        "ran past an earlier stop",
        "the replayed copy of the passed stop",
        "a new stop after a start, inside the tolerance",
        "no stop pending",
    ],
)
def test_a_stop_holds_until_a_later_poll_sees_the_guider_running_past_it(
    polled: list[tuple[str, datetime | None]], stop: datetime | None, stopped: bool
) -> None:
    """A restart's GUIDER-START waits for the settle; a poll seeing the guider
    running is what releases the stop before it — but not the first poll to
    find it, whose snapshot may predate N.I.N.A.'s cache catching up.
    """
    latch = GuiderStopLatch()
    for state, pending in polled:
        latch.observe(state, pending)
    assert latch.stopped(stop) is stopped


_DAWN = [map_frame(f, "g") for f in load("dawn_image_history_with_flats.json")]
_LIGHTS = [f for f in _DAWN if f.image_type == "LIGHT"]
# The night's last four lights, then the first flat after them.
_EARLIER, _EARLY, _LIGHT, _LAST_LIGHT = _LIGHTS[-4:]
_FLAT = next(f for f in _DAWN if f.image_type == "FLAT" and f.date > _LAST_LIGHT.date)
_LAST_START = _LAST_LIGHT.date - timedelta(seconds=_LAST_LIGHT.exposure_time or 0)

_PANEL = map_equipment_info(load("dawn_equipment_info.json")).flat_device
# Captured down: a panel the sequence disconnects once its cover has opened.
_DOWN = map_equipment_info(load("imaging_guiding_equipment_info.json")).flat_device
_OPENED = CoverMove(closed=False, time=datetime.fromisoformat(T1))
_CLOSED = CoverMove(closed=True, time=datetime.fromisoformat(T2))


def _panel(cover_state: str | None) -> FlatDeviceModel | None:
    """The dawn panel reading `cover_state`; the captured down panel for None."""
    assert _PANEL is not None
    return _DOWN if cover_state is None else replace(_PANEL, cover_state=cover_state)


@pytest.mark.parametrize(
    ("polled", "flagged"),
    [
        ([("Closed", _LIGHT), ("Closed", _LAST_LIGHT)], True),
        ([("Closed", None), ("Closed", _LIGHT)], True),
        # The night's close, after its last light.
        ([("Open", _LIGHT), ("Closed", _LAST_LIGHT)], False),
        ([("Closed", _LAST_LIGHT), ("Closed", _FLAT)], False),
        ([("Open", _LIGHT), ("Open", _LAST_LIGHT)], False),
        ([("Closed", _LIGHT), ("Closed", _LAST_LIGHT), ("Open", _LAST_LIGHT)], False),
        (
            [("Closed", _LIGHT), ("Unknown", _LAST_LIGHT), ("Closed", _LAST_LIGHT)],
            False,
        ),
        ([("Closed", _EARLY), (None, _LIGHT), (None, _LAST_LIGHT)], True),
        ([("Closed", _EARLY), (None, _LIGHT), ("Closed", _LAST_LIGHT)], True),
        ([(None, _LIGHT), ("Closed", _LAST_LIGHT)], False),
    ],
    ids=[
        "light after the close",
        "first light after the close",
        "closed after the last light",
        "flat after the close",
        "cover open",
        "cover reopened",
        "connected panel reading unknown",
        "panel disconnected after the close",
        "panel reconnected still closed",
        "panel reconnected for the flats",
    ],
)
def test_a_light_counts_only_once_the_cover_was_seen_closed(
    polled: list[tuple[str | None, Frame | None]], flagged: bool
) -> None:
    latch = CoverClosedLatch()
    results = [latch.update(_panel(state), newest, None) for state, newest in polled]
    assert results[-1] is flagged


@pytest.mark.parametrize(
    ("polled", "flagged"),
    [
        ([("Closed", _LIGHT, None), (None, _LAST_LIGHT, _OPENED)], False),
        # A poll reading the cover before it moved, published again with the
        # event that it opened.
        (
            [
                ("Closed", _EARLIER, None),
                ("Closed", _EARLY, _OPENED),
                ("Closed", _LIGHT, _OPENED),
                ("Closed", _LAST_LIGHT, _OPENED),
            ],
            False,
        ),
        # Closed by hand after N.I.N.A. opened it.
        ([("Closed", _LIGHT, _OPENED), ("Closed", _LAST_LIGHT, _OPENED)], True),
    ],
    ids=[
        "opened, then disconnected",
        "stale closed after the open",
        "opened before the cover was seen closed",
    ],
)
def test_a_reported_open_after_the_cover_was_seen_closed_clears_it(
    polled: list[tuple[str | None, Frame | None, CoverMove | None]], flagged: bool
) -> None:
    latch = CoverClosedLatch()
    results = [
        latch.update(_panel(state), newest, move) for state, newest, move in polled
    ]
    assert results[-1] is flagged


@pytest.mark.parametrize(
    ("closed_at", "flagged"),
    [
        # Saved after the poll saw the cover closed, but exposed before.
        (_LAST_START + timedelta(seconds=1), False),
        (_LAST_START - timedelta(seconds=1), True),
    ],
    ids=["exposed before the reported close", "exposed after it"],
)
def test_a_light_exposed_before_the_reported_close_is_not_flagged(
    closed_at: datetime, flagged: bool
) -> None:
    latch = CoverClosedLatch()
    latch.update(_panel("Closed"), _LIGHT, None)
    move = CoverMove(closed=True, time=closed_at)
    assert latch.update(_panel("Closed"), _LAST_LIGHT, move) is flagged


_PART_WAY = "NeitherOpenNorClosed"


@pytest.mark.parametrize(
    ("polled", "held"),
    [
        # The captured order: connected, opened, disconnected within the second.
        ([("Closed", None), (_PART_WAY, None), (None, _OPENED)], None),
        ([("Closed", None), (_PART_WAY, _OPENED), (None, _OPENED)], None),
        ([(_PART_WAY, None), (None, _OPENED)], None),
        ([("Closed", None), (_PART_WAY, None), (None, None)], _PART_WAY),
        ([("Closed", None), ("Error", None), (None, None)], "Error"),
        ([("Open", _OPENED), (_PART_WAY, _OPENED), (None, _OPENED)], _PART_WAY),
        ([("Closed", _CLOSED), (_PART_WAY, _CLOSED), (None, None)], _PART_WAY),
        ([("Closed", None), (_PART_WAY, None)], None),
        ([("Open", _OPENED), (None, _OPENED)], None),
        (
            [
                ("Open", _OPENED),
                (_PART_WAY, _CLOSED),
                (None, _CLOSED),
                (_PART_WAY, _CLOSED),
                (None, _CLOSED),
            ],
            _PART_WAY,
        ),
        ([(None, _OPENED), (_PART_WAY, _CLOSED), (None, _CLOSED)], None),
    ],
    ids=[
        "opened, then disconnected",
        "read part-way after the open",
        "first read part-way",
        "left part-way",
        "left in error",
        "jammed on a later move",
        "N.I.N.A. restarted",
        "still connected",
        "left at rest",
        "jammed on a move first read part-way",
        "first read after a restart lags the close",
    ],
)
def test_a_disconnect_holds_a_cover_fault_no_move_has_resolved(
    polled: list[tuple[str | None, CoverMove | None]], held: str | None
) -> None:
    hold = CoverFaultHold()
    results = [hold.update(_panel(state), move) for state, move in polled]
    assert results[-1] == held


_EVENING = datetime(2026, 11, 11, 18, 0, tzinfo=timezone(timedelta(hours=-6)))


def _at(minutes: float) -> datetime:
    return _EVENING + timedelta(minutes=minutes)


Step = tuple[tuple[int, ...], SequenceWait]


def _step(
    kind: SequenceWaitKind = "time_span",
    *,
    ends: datetime | None = None,
    span: float | None = 60.0,
    path: tuple[int, ...] = (1, 2),
) -> Step:
    return path, SequenceWait(kind=kind, ends=ends, span_seconds=span)


def _ledger(*reads: tuple[float, Step | None]) -> WaitLedger:
    """`(minute, step or None)` reads, in order, with no Target Scheduler wait."""
    ledger = WaitLedger()
    for minute, step in reads:
        ledger.observe(None, step, now=_at(minute))
    return ledger


def test_a_wait_dates_from_the_read_that_first_shows_it() -> None:
    ledger = _ledger((0, _step(span=600)), (5, _step(span=600)))
    assert ledger.current is not None
    assert ledger.current.started == _at(0)


def test_a_wait_the_read_no_longer_shows_ends_at_that_read() -> None:
    ledger = _ledger((0, _step()), (1, None))
    assert ledger.current is None
    assert ledger.ended[0].ended == _at(1)


@pytest.mark.parametrize(
    ("step", "late", "ended"),
    [
        (_step("time", ends=_at(10), span=None), 11, 10),
        (_step("altitude", span=None), 12 * 60 + 1, 12 * 60 + 1),
        (_step("altitude", ends=_at(60), span=None), 12 * 60 + 1, 12 * 60 + 1),
        (_step("altitude", ends=_at(16 * 60), span=None), 17 * 60 + 1, 17 * 60 + 1),
    ],
    ids=[
        "Wait for Time, at its named end",
        "an altitude wait, after twelve hours",
        "an altitude wait expected in an hour, after twelve hours",
        "an altitude wait expected in sixteen hours, an hour past that",
    ],
)
def test_a_wait_still_shown_running_past_its_possible_end_is_over(
    step: Step, late: float, ended: float
) -> None:
    """A status carried in from a loaded sequence file can show a wait running
    that never will, and would hold a stall alert mute all night.
    """
    ledger = _ledger((0, step), (late, step))
    assert ledger.current is None
    assert ledger.ended[0].ended == _at(ended)


def test_an_expired_wait_stays_over_while_the_read_still_shows_it() -> None:
    late = _step("time", ends=_at(10), span=None)
    ledger = _ledger((0, late), (11, late), (12, late))
    assert (ledger.current, len(ledger.ended)) == (None, 1)


_ESTIMATED = _step("altitude", ends=_at(10), span=None)


@pytest.mark.parametrize(
    ("step", "late"),
    [
        (_ESTIMATED, 15),
        (_step("altitude", ends=_at(16 * 60), span=None), 12 * 60 + 1),
    ],
    ids=["past its estimate", "dawn to a summer dusk, past twelve hours"],
)
def test_an_altitude_wait_runs_on(step: Step, late: float) -> None:
    """N.I.N.A.'s estimate is printed to the minute, and a sun or moon wait
    can end after it.
    """
    ledger = _ledger((0, step), (late, step))
    assert ledger.current is not None


@pytest.mark.parametrize(
    ("later", "held"),
    [(_at(10) + timedelta(days=1), _at(10)), (_at(4), _at(4)), (None, _at(10))],
    ids=[
        "the same minute a day on",
        "a re-estimate minutes earlier",
        "a read with no estimate",
    ],
)
def test_an_altitude_wait_keeps_its_end_but_for_a_re_estimate(
    later: datetime | None, held: datetime
) -> None:
    """The mapper places a dateless estimate the wait has overrun by more than
    six hours on the next day.
    """
    rolled = _step("altitude", ends=later, span=None)
    ledger = _ledger((0, _ESTIMATED), (75, rolled))
    assert ledger.current is not None
    assert ledger.current.ends == held


def test_an_altitude_wait_ends_at_the_read_that_finds_it_over() -> None:
    ledger = _ledger((0, _ESTIMATED), (15, None))
    assert ledger.ended[0].ended == _at(15)


def test_a_span_still_shown_past_its_length_is_the_loops_next_pass() -> None:
    """Reads five minutes apart catch a loop of half-hour spans on nearly every
    pass, and a rig waiting on purpose must keep reading as waiting.
    """
    span = _step(span=1800.0)
    ledger = _ledger(*[(minute, span) for minute in range(0, 45, 5)])
    assert ledger.current is not None
    assert (ledger.current.started, ledger.ended[0].ended) == (_at(35), _at(35))


def test_a_wait_a_loop_runs_again_counts_again() -> None:
    ledger = _ledger((0, _step()), (2, None), (4, _step()))
    assert ledger.current is not None
    assert ledger.current.started == _at(4)


def test_a_different_wait_ends_the_one_before() -> None:
    """Dusk's Wait for Time, then the five-second settle after it: the dusk
    wait must stay in the history for a settle period to run from.
    """
    dusk = _step("time", ends=_at(6), span=None, path=(1, 1))
    settle = _step(span=5.0, path=(1, 9))
    ledger = _ledger((0, dusk), (6.5, settle))
    assert [wait.kind for wait in ledger.ended] == ["time"]
    assert ledger.ended[0].ended == _at(6)


def test_target_schedulers_wait_is_the_one_reported() -> None:
    """Its own steps are not on the wire, so a step beside it is not its."""
    ledger = WaitLedger()
    ledger.observe(_at(30), _step(), now=_at(0))
    assert ledger.current is not None
    assert (ledger.current.kind, ledger.current.ends) == ("scheduler", _at(30))


def test_the_history_keeps_the_ten_newest_newest_first() -> None:
    reads = [(minute, _step() if minute % 2 == 0 else None) for minute in range(24)]
    ended = _ledger(*reads).ended
    assert (len(ended), ended[0].ended) == (10, _at(23))


# The station as N.I.N.A. served it two nights running: a midday reading,
# 80123 lx, `Connected: true`.
_FROZEN = map_equipment_info(
    load("scheduler_waiting_lost_lock_equipment_info.json")
).weather
_OPEN_METEO = map_equipment_info(load("weather_source_openmeteo.json")).weather
_WINDOWS = FreezeWindows(
    station=timedelta(hours=1), web=timedelta(hours=2), lit_night=timedelta(minutes=15)
)
_DAY = 50.0
_NIGHT = -20.0


def _station(**readings: float | None) -> WeatherModel:
    assert _FROZEN is not None
    return replace(_FROZEN, channels={**_FROZEN.channels, **readings})


def _freeze(
    *reads: tuple[float, WeatherModel | None], sun: float | None = _DAY
) -> WeatherFreeze:
    """Each read is (minutes after the first, the weather polled then)."""
    freeze = WeatherFreeze(_WINDOWS)
    for minutes, weather in reads:
        freeze.observe(weather, _at(minutes), sun)
    return freeze


def test_readings_held_for_the_window_are_frozen_since_they_were_first_read() -> None:
    assert _freeze(
        (0, _station()), (30, _station()), (60, _station())
    ).frozen_since == _at(0)


def test_readings_held_for_less_than_the_window_are_not_frozen() -> None:
    assert _freeze((0, _station()), (59, _station())).frozen_since is None


@pytest.mark.parametrize(
    ("minutes", "frozen"), [(119, False), (120, True)], ids=["inside", "past"]
)
def test_a_web_source_has_the_longer_window(minutes: int, frozen: bool) -> None:
    freeze = _freeze((0, _OPEN_METEO), (minutes, _OPEN_METEO))
    assert (freeze.frozen_since is not None) == frozen


@pytest.mark.parametrize(
    ("sun", "frozen"),
    [(_NIGHT, True), (-6.0, False), (None, False)],
    ids=["after dusk", "twilight", "no site"],
)
def test_a_daytime_sky_held_after_dusk_is_frozen_within_minutes(
    sun: float | None, frozen: bool
) -> None:
    freeze = _freeze((0, _station()), (15, _station()), sun=sun)
    assert (freeze.frozen_since is not None) == frozen


@pytest.mark.synthetic
def test_a_dark_sky_after_dusk_keeps_the_station_window() -> None:
    dark = _station(sky_brightness=0.0)
    assert _freeze((0, dark), (15, dark), sun=_NIGHT).frozen_since is None


@pytest.mark.synthetic
@pytest.mark.parametrize(
    "moved",
    [{"temperature": 37.5}, {"wind_speed": 2.8}, {"cloud_cover": 10.0}],
    ids=["drifting channel", "wind", "a channel that was NaN"],
)
def test_any_channel_moving_restarts_the_window(moved: dict[str, float]) -> None:
    freeze = _freeze((0, _station()), (30, _station(**moved)), (75, _station(**moved)))
    assert freeze.frozen_since is None


@pytest.mark.synthetic
def test_a_source_with_no_drifting_channel_is_never_frozen() -> None:
    """Rain 0, calm and 0 lx can hold all night; nothing else is reported."""
    quiet = _station(**dict.fromkeys(DRIFTING_CHANNELS))
    assert _freeze((0, quiet), (120, quiet)).frozen_since is None


@pytest.mark.synthetic
@pytest.mark.parametrize(
    "gap",
    [None, replace(_station(), connected=False)],
    ids=["never observed", "disconnected"],
)
def test_a_source_back_on_the_readings_it_froze_on_is_still_frozen(
    gap: WeatherModel | None,
) -> None:
    """A reconnect fixes nothing upstream of a dead feed."""
    freeze = _freeze((0, _station()), (30, gap), (60, _station()), (61, _station()))
    assert freeze.frozen_since == _at(0)


@pytest.mark.synthetic
def test_the_first_poll_after_a_reconnect_is_not_judged() -> None:
    """A source queried in the background serves its pre-disconnect readings
    until its first answer.
    """
    down = replace(_station(), connected=False)
    assert _freeze((0, _station()), (30, down), (60, _station())).frozen_since is None


@pytest.mark.synthetic
def test_a_source_down_is_not_judged() -> None:
    freeze = _freeze((0, _station()), (90, replace(_station(), connected=False)))
    assert freeze.frozen_since is None


def test_every_drifting_channel_is_one_the_mapper_produces() -> None:
    """A misspelt name would never be read, and drop out of the judgement."""
    assert _FROZEN is not None
    assert set(_FROZEN.channels) >= DRIFTING_CHANNELS

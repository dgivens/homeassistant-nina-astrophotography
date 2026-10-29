"""The session fold and the event-derived readings beside it: `latest_*`,
`scheduler_wait`, `meridian_flip` and `pending_guider_stop`.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from nina_astrophotography.api.models import (
    AutoFocusState,
    FlipReading,
    Frame,
    MeridianFlip,
    NinaEvent,
)
from nina_astrophotography.api.v2.mapper import map_event, map_frame
from nina_astrophotography.session import (
    fold,
    latest_stack,
    latest_target,
    meridian_flip,
    pending_guider_stop,
    recent_frames,
    scheduler_wait,
)
import pytest

from helpers import load_fixture

# Noon the day after the dawn corpus: every one of its frames is by then in
# the previous session.
_AFTER_THE_ROLLOVER = datetime.fromisoformat("2026-09-05T13:00:00-05:00")

# The rig's own offset; every N.I.N.A. timestamp is local to its clock.
RIG = timezone(timedelta(hours=-5))
_START = datetime.fromisoformat("2026-09-03T23:00:00-05:00")


@pytest.fixture
def night() -> list:
    return [
        map_frame(f, generation="g1")
        for f in load_fixture("dawn_image_history_with_flats.json")
    ]


@pytest.fixture
def night_events() -> list:
    return [map_event(e, "g1") for e in load_fixture("dawn_event_history.json")]


def _light(**overrides) -> Frame:
    """One LIGHT frame, defaulted so a test names only the field it is about."""
    fields = {
        "date": datetime.fromisoformat("2026-09-03T23:00:00-05:00"),
        "filename": "frame_0001.fits",
        "target_name": "NGC 281",
        "filter_name": "L",
        "image_type": "LIGHT",
        "exposure_time": 300.0,
        "hfr": 1.5,
        "stars": 4158,
        "mean": 548.6,
        "median": 540.0,
        "std_dev": 30.0,
        "min": 300.0,
        "max": 60000.0,
        "rms_arcsec": 0.29,
        "temperature": -10.0,
        "gain": 100,
        "offset": 50,
        "focal_length": 1000.0,
        "generation": "g1",
    }
    return Frame(**{**fields, **overrides})


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        # Lights sum to 6.2000 h and all 122 frames to 6.2301 h. The tolerance
        # is tight deliberately: at abs=0.02 an all-frames implementation passes,
        # and integration time is light-frame time.
        ("integration_seconds", pytest.approx(6.2000 * 3600, abs=0.001 * 3600)),
        # 67 of the 122 frames are flats reporting HFR 0.
        ("hfr_mean", pytest.approx(1.513, abs=0.01)),
        # image_count is every frame; the aggregates are lights only.
        ("image_count", 122),
        ("light_count", 55),
    ],
)
def test_the_captured_night_folds_to_its_aggregates(night, field, expected) -> None:
    assert getattr(fold(night, [], generation="g1"), field) == expected


def test_the_last_frame_is_the_last_light_not_the_last_flat(night) -> None:
    """The night ends in dawn flats, whose mean ADU says nothing about the sky."""
    stats = fold(night, [], generation="g1")
    assert stats.last_frame is not None
    assert stats.last_frame.image_type == "LIGHT"


def test_recent_lights_are_every_light_oldest_first(night) -> None:
    """The night ends in 67 flats; the series a sparkline draws must still end
    on the last light, not be flushed by them.
    """
    stats = fold(night, [], generation="g1")
    assert len(stats.recent_lights) == 55
    assert stats.recent_lights[-1] == stats.last_frame
    assert [f.date for f in stats.recent_lights] == sorted(
        f.date for f in stats.recent_lights
    )


@pytest.mark.synthetic
def test_recent_lights_keep_only_the_newest_sixty() -> None:
    """Fabricates 61 lights a minute apart; the oldest is the one dropped."""
    start = datetime.fromisoformat("2026-09-03T21:00:00-05:00")
    lights = [
        _light(date=start + timedelta(minutes=i), filename=f"f{i}.fits")
        for i in range(61)
    ]
    recent = fold(lights, [], generation="g1").recent_lights
    assert [f.filename for f in recent] == [f"f{i}.fits" for i in range(1, 61)]


def test_frames_from_a_previous_generation_are_filtered_not_cleared(night) -> None:
    """A restart is a generation change; clearing races a concurrent poll."""
    stats = fold(night, [], generation="g2")
    assert stats.image_count == 0


@pytest.mark.parametrize(
    ("field", "rows"),
    [
        ("by_target", 4),
        # All 122 frames carry six filters; the 55 lights carry five, since the
        # flats add G. A per-filter row for a G flat with no G lights is noise.
        ("by_filter", 5),
    ],
)
def test_the_breakdown_covers_what_the_lights_imaged(night, field, rows) -> None:
    assert len(getattr(fold(night, [], generation="g1"), field)) == rows


def _autofocus_start(*after: tuple[str, int, dict]) -> list[NinaEvent]:
    """`AUTOFOCUS-STARTING` at `_START`, then each `(name, seconds, data)`."""
    return [
        NinaEvent("AUTOFOCUS-STARTING", _START, {}, "g1"),
        *(
            NinaEvent(name, _START + timedelta(seconds=seconds), data, "g1")
            for name, seconds, data in after
        ),
    ]


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("events", "timeout", "elapsed", "running", "failed"),
    [
        # A start nothing answers within the PROFILE's timeout has hung. It is
        # `FocuserSettings.AutoFocusTimeoutSeconds`, 600 on the captured rig, so
        # a 300 s constant would call a seven-minute run failed. The corpus has
        # no hung night (its one unanswered start was aborted), so it is built.
        (_autofocus_start(), 300, 301, True, True),
        (_autofocus_start(), 600, 301, True, False),
        (_autofocus_start(), 600, 601, True, True),
        # Only IsSafe false interrupts; SAFETY-CHANGED fires for both.
        (
            _autofocus_start(("SAFETY-CHANGED", 37, {"IsSafe": True})),
            300,
            60,
            True,
            False,
        ),
        # An exposure saved only after the timeout shows the sequence carried
        # on past a hung autofocus: it clears the run without excusing it.
        (_autofocus_start(("IMAGE-SAVE", 400, {})), 300, 500, False, True),
        (_autofocus_start(("AUTOFOCUS-FINISHED", 200, {})), 300, 201, False, False),
        # Unsafe conditions, the sequence ending, a park, a disconnect or the
        # sequencer moving on to the next exposure all cancel a running
        # autofocus; none of them is the focuser failing to find focus.
        *(
            (_autofocus_start((name, 37, data)), 300, 600, False, False)
            for name, data in [
                ("SAFETY-CHANGED", {"IsSafe": False}),
                ("SEQUENCE-FINISHED", {}),
                ("MOUNT-PARKED", {}),
                ("CAMERA-DISCONNECTED", {}),
                ("IMAGE-SAVE", {}),
            ]
        ),
    ],
    ids=[
        "past the 300 s timeout",
        "inside the 600 s timeout",
        "past the 600 s timeout",
        "a safe reading",
        "saved after the timeout",
        "finished",
        "unsafe",
        "sequence finished",
        "mount parked",
        "camera disconnected",
        "next exposure saved",
    ],
)
def test_an_autofocus_start_is_running_hung_or_aborted_by_what_follows_it(
    events, timeout, elapsed, running, failed
) -> None:
    stats = fold(
        [],
        events,
        generation="g1",
        autofocus_timeout_seconds=timeout,
        now=_START + timedelta(seconds=elapsed),
    )
    assert (stats.autofocus.running_since is not None, stats.autofocus.failed) == (
        running,
        failed,
    )


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        # Before the first frame there is no clock to derive a session from.
        ("session_start", None),
        ("image_count", 0),
        ("light_count", 0),
        ("integration_seconds", 0.0),
        ("hfr_mean", None),
        ("hfr_best", None),
        ("hfr_worst", None),
        ("star_count_mean", None),
        ("last_frame", None),
        ("by_target", ()),
        ("by_filter", ()),
    ],
)
def test_a_fold_of_nothing_reports_empty_aggregates(field, expected) -> None:
    assert getattr(fold([], [], generation="g1"), field) == expected


@pytest.mark.parametrize("reversed_arrival", [False, True])
def test_a_stale_copy_of_a_refetched_frame_never_wins_the_dedupe(
    night, reversed_arrival
) -> None:
    """A restart leaves the pre-restart and refetched copies of one frame in the
    store. Deduplicating before filtering would let the stale copy win and then
    be discarded, so the frame would vanish.
    """
    light = next(f for f in night if f.image_type == "LIGHT")
    both = [replace(light, generation="g2"), replace(light, generation="g1")]
    stats = fold(both[::-1] if reversed_arrival else both, [], generation="g2")
    assert stats.last_frame is not None
    assert (stats.image_count, stats.last_frame.generation) == (1, "g2")


def test_an_untagged_frame_folds_under_an_untagged_generation() -> None:
    """Frames received before `/application-start` answered carry no tag."""
    assert fold([_light(generation=None)], [], generation=None).image_count == 1


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("integration_seconds", 0.0),
        ("hfr_mean", None),
        ("hfr_best", None),
        ("hfr_worst", None),
        ("star_count_mean", None),
    ],
)
def test_a_light_with_no_readings_fakes_no_aggregate(field, expected) -> None:
    """`None` is "no reading" — it must not read as a zero."""
    bare = _light(exposure_time=None, hfr=None, stars=None)
    assert getattr(fold([bare], [], generation="g1"), field) == expected


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("image_count", 1),
        ("light_count", 0),
        ("integration_seconds", 0.0),
        ("by_target", ()),
        ("last_frame", None),
    ],
)
def test_an_unclassified_frame_is_counted_but_never_aggregated(field, expected) -> None:
    """A frame with no ImageType is neither calibration nor light; it is counted
    because it exists, and aggregated nowhere because nothing says it is a sub.
    """
    unclassified = _light(image_type=None)
    assert getattr(fold([unclassified], [], generation="g1"), field) == expected


def test_a_breakdown_row_with_no_measured_hfr_reports_none() -> None:
    (row,) = fold([_light(hfr=None)], [], generation="g1").by_target
    assert row.hfr_mean is None


@pytest.mark.parametrize("field", ["by_target", "by_filter"])
def test_an_unnamed_group_gets_no_breakdown_row(field) -> None:
    """A row headed by nothing is noise on a dashboard."""
    unnamed = _light(target_name=None, filter_name=None)
    assert getattr(fold([unnamed], [], generation="g1"), field) == ()


def test_a_session_of_only_calibration_frames_has_no_last_frame(night) -> None:
    flats = [f for f in night if f.image_type != "LIGHT"]
    assert fold(flats, [], generation="g1").last_frame is None


def test_the_hfr_extremes_are_the_best_and_worst_light(night) -> None:
    """Best is the tightest star, so the smallest HFR."""
    stats = fold(night, [], generation="g1")
    assert (stats.hfr_best, stats.hfr_worst) == pytest.approx(
        (1.42873, 1.89118), abs=1e-5
    )


def test_frames_before_the_noon_rollover_are_outside_the_session(night) -> None:
    """A session runs noon to noon, so last night's frames are last night's."""
    assert fold(night, [], generation="g1", now=_AFTER_THE_ROLLOVER).image_count == 0


def test_the_last_autofocus_to_finish_is_reported(night_events) -> None:
    """A FINISHED is the report, not a verdict; whether it found focus is a
    question for /last-af.
    """
    stats = fold([], night_events, generation="g1")
    assert stats.autofocus.last_finished_at == datetime.fromisoformat(
        "2026-09-04T03:21:11.414439-05:00"
    )


def test_the_nights_unanswered_start_was_an_abort_not_a_failure(night_events) -> None:
    """The eighth AUTOFOCUS-STARTING (04:26:09) was followed 37 s later by
    SAFETY-CHANGED IsSafe false — the sky closed on it. Read at 07:30 rig time,
    long past any timeout, it is neither running nor failed.
    """
    stats = fold(
        [],
        night_events,
        generation="g1",
        now=datetime.fromisoformat("2026-09-04T07:30:00-05:00"),
    )
    assert (stats.autofocus.running_since, stats.autofocus.failed) == (None, False)


def test_events_from_a_previous_session_do_not_report_an_autofocus(
    night_events,
) -> None:
    tomorrow = max(e.time for e in night_events) + timedelta(days=1)
    stats = fold([], night_events, generation="g1", now=tomorrow)
    assert stats.autofocus == AutoFocusState(None, None, False)


def test_the_recent_frames_ignore_the_session_window(night) -> None:
    """The rig's image history does not roll over at local noon, so what
    `image.last_frame` renders long after the rollover is still last night's
    frame.
    """
    assert recent_frames(night, "g1")[0].date == max(f.date for f in night)


def test_the_recent_frames_of_another_process_are_not_offered(night) -> None:
    assert recent_frames(night, "g2") == ()


def test_the_stack_is_the_pair_the_newest_update_named(night_events) -> None:
    stack = latest_stack(night_events, "g1")
    assert stack is not None
    assert (stack.target, stack.filter_name) == ("NGC 281", "S")


@pytest.mark.parametrize("half", ["Target", "Filter"])
@pytest.mark.parametrize("how", ["absent", "empty"], ids=["absent", "empty"])
def test_a_stack_update_missing_half_its_pair_names_nothing(
    half: str, how: str
) -> None:
    """Both halves are path segments, and `/livestack/image//O` is not a route
    — so an empty string has to be refused as firmly as a missing key.
    """
    payload = {
        "Event": "STACK-UPDATED",
        "Time": "2026-09-04T04:25:58-05:00",
        "Target": "NGC 281",
        "Filter": "S",
    }
    if how == "absent":
        del payload[half]
    else:
        payload[half] = ""
    assert latest_stack([map_event(payload, "g1")], "g1") is None


def test_no_stack_update_is_no_stack(night_events) -> None:
    assert (
        latest_stack([e for e in night_events if e.name != "STACK-UPDATED"], "g1")
        is None
    )


def test_the_target_is_the_one_the_newest_start_announced(night_events) -> None:
    """TS-TARGETSTART fires once per exposure, so the newest is the current
    target, not the first of the night.
    """
    assert latest_target(night_events, "g1") == "NGC 281"


def test_a_rig_without_target_scheduler_announces_no_target(night_events) -> None:
    """A plain N.I.N.A. sequence emits no TS-* event; its target is in the tree."""
    assert (
        latest_target([e for e in night_events if not e.name.startswith("TS-")], "g1")
        is None
    )


@pytest.mark.parametrize(
    ("capture", "expected"),
    [
        ("scheduler_waiting_lost_lock", True),
        ("imaging_guiding", False),
        ("scheduler_waiting", False),
    ],
    ids=["stopped for a scheduler wait", "guiding", "only a GUIDER-CONNECTED logged"],
)
def test_a_stop_is_pending_when_it_is_the_newest_start_or_stop(
    capture: str, expected: bool
) -> None:
    """The newest start or stop decides; a history with neither is not a stop."""
    events = [map_event(e, "g1") for e in load_fixture(f"{capture}_event_history.json")]
    assert (pending_guider_stop(events, "g1") is not None) is expected


@pytest.mark.parametrize(
    ("logged", "expected"),
    [
        ([("GUIDER-STOP", "g1"), ("GUIDER-DITHER", "g1")], True),
        ([("GUIDER-START", "g1"), ("GUIDER-STOP", "g0")], False),
    ],
    ids=["a dither after the stop", "the stop was the previous process's"],
)
@pytest.mark.synthetic
def test_neither_a_dither_nor_a_previous_process_moves_the_verdict(
    logged: list[tuple[str, str]], expected: bool
) -> None:
    """N.I.N.A. raises GUIDER-DITHER even for a dither it skipped, so it is
    not a start; a stop from before a N.I.N.A. restart says nothing.
    """
    events = [
        NinaEvent(
            name=name,
            time=datetime(2026, 9, 18, 21, minute, tzinfo=RIG),
            data={},
            generation=generation,
        )
        for minute, (name, generation) in enumerate(logged)
    ]
    assert (pending_guider_stop(events, "g1") is not None) is expected


WAIT_END = datetime(2026, 9, 15, 21, 5, 40, tzinfo=RIG)
WAITING_AT = datetime(2026, 9, 15, 20, 45, tzinfo=RIG)


def _waiting_events(
    *ending: str, at: int = 40, wait_end: datetime | None = WAIT_END
) -> list[NinaEvent]:
    """`TS-WAITSTART` at 20:33 announcing 21:05, plus whatever ends it."""
    return [
        NinaEvent(
            name="TS-WAITSTART",
            time=datetime(2026, 9, 15, 20, 33, tzinfo=RIG),
            data={},
            generation="g1",
            wait_end=wait_end,
        ),
        *(
            NinaEvent(
                name=name,
                time=datetime(2026, 9, 15, 20, at, tzinfo=RIG),
                data={},
                generation="g1",
            )
            for name in ending
        ),
    ]


@pytest.mark.parametrize(
    ("events", "now", "expected"),
    [
        (_waiting_events(), WAITING_AT, WAIT_END),
        (_waiting_events("TS-TARGETSTART"), WAITING_AT, None),
        (_waiting_events("SEQUENCE-FINISHED"), WAITING_AT, None),
        (_waiting_events(), datetime(2026, 9, 15, 21, 30, tzinfo=RIG), None),
        ([], WAITING_AT, None),
        (_waiting_events("TS-TARGETSTART", at=30), WAITING_AT, WAIT_END),
        (_waiting_events(wait_end=None), WAITING_AT, None),
    ],
    ids=[
        "waiting",
        "a target started",
        "the sequence was stopped",
        "the wait end has passed",
        "no wait announced",
        "the target start came BEFORE the wait",
        "the rig clock was unknown",
    ],
)
@pytest.mark.synthetic
def test_a_wait_ends_at_its_time_or_when_something_supersedes_it(
    events: list[NinaEvent], now: datetime, expected: datetime | None
) -> None:
    """There is no TS-WAITSTOP, and a stop leaves the announcement in the
    history still naming a future time — so a wait has to be ended by what
    follows it rather than waited out. `TS-TARGETSTART` fires once per
    exposure, so the previous target's starts are always in the buffer and only
    a LATER one can end a wait.

    An unknown rig clock reports not-waiting rather than guessing, which is the
    conservative way round for the dashboard and the alarming way round for a
    stall rule built on it.
    """
    assert scheduler_wait(events, "g1", now=now) == expected


FLIP_STARTED = datetime(2026, 9, 4, 3, 52, 34, tzinfo=RIG)
GUIDER_STOPPED = FLIP_STARTED + timedelta(seconds=1)
# Read ten seconds before the flip began, half an hour short of meridian + Max.
TRACKED = FlipReading(hours=0.5, read_at=FLIP_STARTED - timedelta(seconds=10))


def _flip_events(*logged: tuple[str, timedelta], generation: str = "g1") -> list:
    """`MOUNT-BEFORE-FLIP` at 03:52:34, then each event that long after it."""
    return [
        NinaEvent(
            name="MOUNT-BEFORE-FLIP", time=FLIP_STARTED, data={}, generation=generation
        ),
        *(
            NinaEvent(name=name, time=FLIP_STARTED + after, data={}, generation="g1")
            for name, after in logged
        ),
    ]


@pytest.mark.parametrize(
    ("cut_after", "expected"),
    [("MOUNT-BEFORE-FLIP", True), ("MOUNT-AFTER-FLIP", False)],
    ids=["mid-flip", "flipped"],
)
def test_the_captured_flip_runs_from_its_before_event_to_its_after(
    night_events: list[NinaEvent], cut_after: str, expected: bool
) -> None:
    cut = next(i for i, e in enumerate(night_events) if e.name == cut_after)
    events = night_events[: cut + 1]
    flip = meridian_flip(
        events,
        "g1",
        reading=None,
        window_minutes=None,
        now=events[-1].time + timedelta(minutes=1),
    )
    assert (flip is not None) is expected


@pytest.mark.parametrize(
    "ending",
    [
        "SEQUENCE-FINISHED",
        "MOUNT-PARKED",
        "MOUNT-HOMED",
        "MOUNT-DISCONNECTED",
    ],
)
@pytest.mark.synthetic
def test_a_flip_ends_when_the_mount_is_put_away_before_its_after_event(
    ending: str,
) -> None:
    """These end a flip whose AFTER-FLIP never came."""
    events = _flip_events((ending, timedelta(minutes=2)))
    flip = meridian_flip(
        events,
        "g1",
        reading=None,
        window_minutes=None,
        now=FLIP_STARTED + timedelta(minutes=3),
    )
    assert flip is None


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        (_flip_events(("MOUNT-AFTER-FLIP", -timedelta(minutes=30))), True),
        (_flip_events(generation="g0"), False),
    ],
    ids=["the end was an earlier flip's", "the start was the previous process's"],
)
@pytest.mark.synthetic
def test_only_a_later_end_this_process_logged_counts(
    events: list[NinaEvent], expected: bool
) -> None:
    flip = meridian_flip(
        events,
        "g1",
        reading=None,
        window_minutes=None,
        now=FLIP_STARTED + timedelta(minutes=1),
    )
    assert (flip is not None) is expected


@pytest.mark.parametrize(
    ("events", "reading", "window", "slews_at"),
    [
        (
            _flip_events(("GUIDER-STOP", timedelta(seconds=1))),
            TRACKED,
            10.0,
            # 30 min less the 10 s since the reading, less the 10 min window.
            GUIDER_STOPPED + timedelta(minutes=20, seconds=-10),
        ),
        (
            _flip_events(),
            TRACKED,
            10.0,
            FLIP_STARTED + timedelta(minutes=20, seconds=-10),
        ),
        (
            _flip_events(("GUIDER-STOP", timedelta(seconds=1))),
            replace(TRACKED, hours=0.1),
            10.0,
            GUIDER_STOPPED,
        ),
        (
            _flip_events(("GUIDER-STOP", timedelta(seconds=1))),
            replace(TRACKED, hours=3.0),
            10.0,
            GUIDER_STOPPED,
        ),
        (
            _flip_events(),
            replace(TRACKED, read_at=FLIP_STARTED - timedelta(minutes=10)),
            10.0,
            None,
        ),
        (_flip_events(), TRACKED, None, None),
        (_flip_events(), None, 10.0, None),
    ],
    ids=[
        "counted from the guider stop",
        "no guider: counted from the start",
        "already inside the window: no wait",
        "a wait over two hours is skipped",
        "the reading is stale",
        "the profile is unread",
        "no tracked reading",
    ],
)
@pytest.mark.synthetic
def test_the_slew_comes_when_the_last_tracked_countdown_reaches_the_window(
    events: list[NinaEvent],
    reading: FlipReading | None,
    window: float | None,
    slews_at: datetime | None,
) -> None:
    """N.I.N.A. waits `TimeToMeridianFlip − (Max − Min)` with tracking off,
    counted once the guider has stopped, so the countdown read before the
    flip places the slew; the wait itself reads the 24 h sentinel.
    """
    flip = meridian_flip(
        events, "g1", reading=reading, window_minutes=window, now=FLIP_STARTED
    )
    assert flip == MeridianFlip(started=FLIP_STARTED, slews_at=slews_at)


@pytest.mark.parametrize(
    ("reading", "now", "expected"),
    [
        (TRACKED, FLIP_STARTED + timedelta(hours=1, minutes=19), True),
        (TRACKED, FLIP_STARTED + timedelta(hours=1, minutes=21), False),
        (None, FLIP_STARTED + timedelta(hours=2, minutes=59), True),
        (None, FLIP_STARTED + timedelta(hours=3, minutes=1), False),
    ],
    ids=[
        "an hour after the slew",
        "past an hour after the slew",
        "inside the longest wait and an hour",
        "past the longest wait and an hour",
    ],
)
@pytest.mark.synthetic
def test_a_flip_that_never_reports_its_end_lapses(
    reading: FlipReading | None, now: datetime, expected: bool
) -> None:
    flip = meridian_flip(
        _flip_events(), "g1", reading=reading, window_minutes=10.0, now=now
    )
    assert (flip is not None) is expected

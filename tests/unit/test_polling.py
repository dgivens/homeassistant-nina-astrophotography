"""The pure polling decisions: restart detection, the reseed guard, the tiers.

Home-Assistant-free by design — the coordinator composes these, so they can be
tested as functions of their arguments rather than through a config entry.
"""
from __future__ import annotations

from dataclasses import fields, replace

import pytest
from helpers import load_fixture as load

from nina_astrophotography.api.models import EquipmentSnapshot
from nina_astrophotography.api.v2.mapper import map_equipment_info
from nina_astrophotography.polling import (
    ReseedGuard,
    RestartDetector,
    TierSchedule,
    imaging,
)


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
    ],
    ids=["application-start moved", "count fell", "steady", "first read"],
)
def test_the_restart_signals(before, after, restarted) -> None:
    detector = RestartDetector()
    detector.update(*before)
    assert detector.observe(*after) is restarted


def test_a_generation_that_reads_null_is_corroborated_by_the_counter() -> None:
    """A tick whose /application-start is unreadable still reports the restart,
    because the counter is on the same tier."""
    detector = RestartDetector()
    detector.update("2026-09-04T10:58:59", 122)
    assert detector.observe(None, 0) is True


def test_an_unreadable_application_start_does_not_erase_the_baseline() -> None:
    """Missing information, not a new process. Erasing it would leave the next
    tick with no baseline, and so blind to the restart that tick reports."""
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
    ],
    ids=["invariant holds", "one tick", "two ticks", "a match resets"],
)
def test_the_reseed_guard_needs_the_mismatch_twice(observations, fires) -> None:
    """A frame saved between the ?count=true read and the history read fails
    the invariant transiently, and an immediate reseed answers that with a
    62 KB refetch every time it happens."""
    guard = ReseedGuard()
    assert [guard.check(*observation) for observation in observations] == fires


def test_a_reseed_guard_that_fired_starts_over() -> None:
    guard = ReseedGuard()
    assert [guard.check(122, 123) for _ in range(4)] == [False, True, False, True]


def test_a_mismatch_that_survives_a_reseed_latches_until_the_count_moves() -> None:
    """A structural difference — an item the mapper skips, two the fold merges
    — no refetch can close, so it must stop asking for one."""
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
    already carries everything a refetch would fetch."""
    schedule = TierSchedule()
    assert schedule.request_sequence_refetch(1000.0) is True
    assert schedule.request_sequence_refetch(1000.0 + TierSchedule.SEQUENCE_DEBOUNCE - 1) is False
    assert schedule.request_sequence_refetch(1000.0 + TierSchedule.SEQUENCE_DEBOUNCE) is True


def test_events_queue_endpoints_once_and_taking_them_drains_the_queue() -> None:
    """Two events naming the same endpoint are one refetch, and the tick that
    performs it must clear the queue or it re-reads on every tick after."""
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


def test_sequence_finished_drops_the_cadence_without_waiting_for_the_heuristic() -> None:
    """SEQUENCE-FINISHED fires once at session end; the activity heuristic
    would keep the tier at 30 s for another five minutes after the last frame."""
    schedule = TierSchedule()
    schedule.set_imaging(True)
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1040.0) is True
    schedule.sequence_finished()
    assert schedule.due("sequence", 1040.0) is False


def test_set_imaging_cannot_undo_sequence_finished_until_activity_returns() -> None:
    """The heuristic is still the authority: a rising count after the event
    puts the tier back at 30 s, so the drop is a cadence change and not a latch."""
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
    ids=["count rose", "camera exposing", "a recent IMAGE-SAVE",
         "the last save aged out", "nothing happening"],
)
def test_imaging_is_inferred_from_activity(
    count, last_count, exposing, since_save, expected
) -> None:
    """Never from /sequence/json node status: three nodes read RUNNING on the
    idle rig with zero frames captured, which would pin the tier at 30 s."""
    snapshot = _snapshot_with_camera(is_exposing=exposing)
    assert imaging(snapshot, count, last_count, since_save) is expected


def test_imaging_survives_a_camera_that_has_never_been_observed() -> None:
    """Every device slot is None until it has carried a DeviceId, and the
    heuristic runs on the first tick."""
    snapshot = EquipmentSnapshot(*[None] * len(fields(EquipmentSnapshot)))
    assert imaging(snapshot, 28, 27, 9999.0) is True
    assert imaging(snapshot, 27, 27, 9999.0) is False


def _snapshot_with_camera(*, is_exposing: bool | None) -> EquipmentSnapshot:
    """The captured snapshot with one field varied — the corpus holds the
    camera exposing, and no capture can hold both branches."""
    camera = map_equipment_info(load("imaging_guiding_equipment_info.json")).camera
    blanks = {f.name: None for f in fields(EquipmentSnapshot)}
    return EquipmentSnapshot(**{**blanks,
                                "camera": replace(camera, is_exposing=is_exposing)})

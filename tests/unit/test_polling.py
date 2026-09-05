"""The pure polling decisions: restart detection, the reseed guard, the tiers.

Home-Assistant-free by design — the coordinator composes these, so they can be
tested as functions of their arguments rather than through a config entry.
"""
from __future__ import annotations

import pytest

from nina_astrophotography.polling import ReseedGuard, RestartDetector, TierSchedule


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


def test_an_unreadable_application_start_falls_back_to_the_counter() -> None:
    """A build that does not serve /application-start still restarts, and the
    count going backwards is the only signal left."""
    detector = RestartDetector()
    detector.update(None, 122)
    assert detector.observe(None, 0) is False  # no baseline generation
    detector.update("2026-09-04T10:58:59", 122)
    assert detector.observe(None, 0) is True


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


def test_a_tier_is_due_when_it_has_never_run_and_not_again_until_its_interval() -> None:
    schedule = TierSchedule()
    assert schedule.due("sequence", 1000.0) is True
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1000.0 + TierSchedule.SEQUENCE_IDLE - 1) is False
    assert schedule.due("sequence", 1000.0 + TierSchedule.SEQUENCE_IDLE) is True


def test_the_sequence_interval_drops_back_to_idle_on_demand() -> None:
    """SEQUENCE-FINISHED fires once at session end, so the cadence can fall
    immediately rather than waiting for the activity heuristic to go quiet."""
    schedule = TierSchedule()
    schedule.sequence_interval = TierSchedule.SEQUENCE_IMAGING
    schedule.mark("sequence", 1000.0)
    assert schedule.due("sequence", 1040.0) is True
    schedule.drop_sequence_cadence()
    assert schedule.due("sequence", 1040.0) is False


def test_a_sequence_refetch_is_debounced() -> None:
    """TS-TARGETSTART fires once per exposure — 27 in 3.8 h — and its payload
    already carries everything a refetch would fetch."""
    schedule = TierSchedule()
    assert schedule.request_sequence_refetch(1000.0) is True
    assert schedule.request_sequence_refetch(1000.0 + TierSchedule.SEQUENCE_DEBOUNCE - 1) is False
    assert schedule.request_sequence_refetch(1000.0 + TierSchedule.SEQUENCE_DEBOUNCE) is True


def test_events_queue_endpoints_for_the_next_tick() -> None:
    schedule = TierSchedule()
    schedule.add_pending("/profile/show")
    schedule.add_pending("/profile/show")
    assert schedule.pending == {"/profile/show"}

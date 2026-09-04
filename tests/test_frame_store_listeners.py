"""Listener dispatch in the frame statistics store."""
from __future__ import annotations

import logging

import pytest

from nina_astrophotography.frame_statistics import NinaFrameStatisticsStore

FRAME = {"ImageStatistics": {"HFR": 2.5, "Stars": 3000, "ExposureTime": 600}}


@pytest.fixture
def store() -> NinaFrameStatisticsStore:
    return NinaFrameStatisticsStore()


def test_a_pushed_frame_notifies_each_listener_once(store):
    calls = []
    store.add_update_listener(lambda: calls.append("a"))
    store.add_update_listener(lambda: calls.append("b"))

    store.push_frame(FRAME)

    assert calls == ["a", "b"]


def test_a_removed_listener_stops_being_called(store):
    calls = []

    def listener():
        calls.append(1)

    store.add_update_listener(listener)
    store.remove_update_listener(listener)
    store.push_frame(FRAME)

    assert calls == []


def test_reset_notifies_listeners(store):
    """Entities have to hear about the clear, or they show the old session."""
    store.push_frame(FRAME)
    calls = []
    store.add_update_listener(lambda: calls.append(1))

    store.reset()

    assert calls == [1]


def test_reset_clears_the_session_counter(store):
    store.push_frame(FRAME)

    store.reset()

    assert store.session_frame_count == 0


def test_a_payload_without_statistics_notifies_nobody(store):
    """Malformed frames are the normal failure mode of a WebSocket feed."""
    calls = []
    store.add_update_listener(lambda: calls.append(1))

    store.push_frame({"Response": "OK"})

    assert calls == []
    assert store.session_frame_count == 0


def test_removing_a_listener_that_was_never_added_is_not_an_error(store):
    """Home Assistant can tear an entity down that never finished setting up."""
    store.remove_update_listener(lambda: None)


def dispatch(store, trigger):
    """Both paths notify, so every dispatch contract is checked on each."""
    if trigger == "push":
        store.push_frame(FRAME)
    else:
        store.reset()


@pytest.mark.parametrize("trigger", ["push", "reset"], ids=["push_frame", "reset"])
def test_one_failing_listener_does_not_stop_the_others(store, trigger, caplog):
    """A raising entity must not cost every other entity its update.

    Both loops must also log it, or a listener that breaks on only one of the
    two paths leaves no trace.
    """
    reached = []

    def boom():
        raise RuntimeError("listener exploded")

    store.add_update_listener(boom)
    store.add_update_listener(lambda: reached.append(1))

    dispatch(store, trigger)

    assert reached == [1]
    assert any(r.levelno == logging.ERROR and r.exc_info for r in caplog.records)


@pytest.mark.parametrize("trigger", ["push", "reset"], ids=["push_frame", "reset"])
def test_a_listener_that_deregisters_itself_does_not_skip_the_others(store, trigger):
    """Entity teardown can remove a listener mid-dispatch.

    Both loops iterate a copy for this reason; without it the removal shifts
    the list underneath the iteration and the next listener is skipped.
    """
    reached = []

    def self_removing():
        store.remove_update_listener(self_removing)

    store.add_update_listener(self_removing)
    store.add_update_listener(lambda: reached.append(1))

    dispatch(store, trigger)

    assert reached == [1]

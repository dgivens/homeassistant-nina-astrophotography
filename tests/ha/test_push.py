"""Push, poll and `/event-history` replay are one idempotent fold.

Asserted through `coordinator.data` and the light: phase B has no session
sensors yet, and `data` is the published snapshot every phase-C entity reads.
"""
from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from scenarios.fake_rig import FakeRig

from custom_components.nina_astrophotography.api.v2.mapper import map_event

LIGHT = "light.n_i_n_a_flat_panel_light"
AT = "2026-09-05T01:41:53.9-05:00"


@pytest.fixture(autouse=True)
def _inside_the_dawn_session(freezer):
    """07:30 on the rig — after its dawn flats, before its noon rollover — so
    the 122 captured frames and the pushed one are all the same session."""
    freezer.move_to("2026-09-04T12:30:00+00:00")


def _count(entry: MockConfigEntry) -> int:
    return entry.runtime_data.coordinator.data.session.image_count


def _reads(rig: FakeRig, path: str) -> int:
    return sum(1 for url, _ in rig.requests if url.endswith(path))


def _reseeds(rig: FakeRig) -> int:
    """How many times the rig has been asked for /image-history?all=true."""
    return sum(1 for _, params in rig.requests if params == {"all": "true"})


async def test_a_pushed_frame_is_published_without_waiting_for_the_poll(
    hass: HomeAssistant, loaded_entry, push, nina_responses
) -> None:
    """`async_set_updated_data`, not `async_request_refresh` — that single line
    is what makes the design push-first rather than socket-as-a-hint."""
    before = _count(loaded_entry)
    push(nina_responses("live_image_save_push.json"))
    await hass.async_block_till_done()
    assert _count(loaded_entry) == before + 1


async def test_the_same_frame_pushed_twice_is_folded_once(
    hass: HomeAssistant, loaded_entry, push, nina_responses
) -> None:
    """Frame identity is `(Date, Filename)`, identical on the push and poll
    paths, so a redelivery must not move the count."""
    before = _count(loaded_entry)
    for _ in range(2):
        push(nina_responses("live_image_save_push.json"))
        await hass.async_block_till_done()
    assert _count(loaded_entry) == before + 1


async def test_a_disconnect_event_refetches_the_snapshot_before_the_next_tick(
    hass: HomeAssistant, loaded_entry, push, rig: FakeRig
) -> None:
    """§6.4: a device dropping out must not sit until the next 10 s poll."""
    rig.requests.clear()
    rig.goto("equipment_disconnected")
    push({"Event": "FLAT-DISCONNECTED", "Time": AT})
    await hass.async_block_till_done()
    assert _reads(rig, "/equipment/info") == 1
    assert hass.states.get(LIGHT).state == "unavailable"


async def test_a_push_cannot_resurrect_a_failed_poll(
    hass: HomeAssistant, loaded_entry, push, advance, nina_responses
) -> None:
    """`async_set_updated_data` sets `last_update_success`, so an ungated push
    would report eleven devices available on a rig that is still unreachable.
    The fold still takes the frame — it appears once the rig answers again."""
    before = _count(loaded_entry)
    await advance("nina_unreachable")
    push(nina_responses("live_image_save_push.json"))
    await hass.async_block_till_done()
    assert hass.states.get(LIGHT).state == "unavailable"

    await advance("imaging")
    assert _count(loaded_entry) == before + 1


async def test_setup_replays_the_event_history(
    loaded_entry, nina_responses
) -> None:
    """What the socket could not deliver, because it was not connected yet: the
    entry knows about an autofocus that finished before Home Assistant started.
    """
    history = nina_responses("dawn_event_history.json")
    newest = max(map_event(event, None).time for event in history
                 if event["Event"] == "AUTOFOCUS-FINISHED")
    autofocus = loaded_entry.runtime_data.coordinator.data.session.autofocus
    assert autofocus.last_finished_at == newest


async def test_a_replayed_event_pushed_live_is_not_folded_again(
    hass: HomeAssistant, loaded_entry, push, nina_responses
) -> None:
    """One ledger covers both paths, so an event the replay already took is
    dropped rather than appended a second time.

    `is`, not `==`: a duplicate fold publishes an equal snapshot, so only the
    identity of the published object shows that nothing was folded at all.
    """
    coordinator = loaded_entry.runtime_data.coordinator
    history = nina_responses("dawn_event_history.json")
    replayed = next(event for event in reversed(history)
                    if event["Event"] == "AUTOFOCUS-FINISHED")

    before = coordinator.data
    push({"Event": "AUTOFOCUS-FINISHED", "Time": AT})   # not in the history
    await hass.async_block_till_done()
    published = coordinator.data
    push(replayed)
    await hass.async_block_till_done()

    assert published is not before            # the unseen event was folded
    assert coordinator.data is published      # the replayed one never reached it


async def test_only_a_socket_reconnect_reseeds_and_replays(
    hass: HomeAssistant, loaded_entry, rig: FakeRig
) -> None:
    """A reconnect needs both halves: `/event-history` carries `{Event, Time}`
    only, so the statistics a missed `IMAGE-SAVE` push held come back from
    `?all=true` and nowhere else. The FIRST connection needs neither — setup
    has just done both.

    `_set_connected` is the one private call: pytest-socket refuses the real
    connection and `start` is stubbed, so driving the transition by hand is the
    minimal seam. Everything it reaches is public.
    """
    connect = loaded_entry.runtime_data.events._set_connected
    rig.requests.clear()

    connect(True)
    await hass.async_block_till_done()
    first = (_reseeds(rig), _reads(rig, "/event-history"))
    connect(False)
    connect(True)
    await hass.async_block_till_done()

    assert (first, (_reseeds(rig), _reads(rig, "/event-history"))) == ((0, 0), (1, 1))

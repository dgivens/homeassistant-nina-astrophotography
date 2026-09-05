"""Push, poll and `/event-history` replay are one idempotent fold.

Asserted through `coordinator.data` and the light: phase B has no session
sensors yet, and `data` is the published snapshot every phase-C entity reads.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from scenarios.fake_rig import FakeRig

LIGHT = "light.n_i_n_a_flat_panel_light"
AT = "2026-09-05T01:41:53.9-05:00"

pytestmark = pytest.mark.usefixtures("inside_the_dawn_session")


def _count(entry: MockConfigEntry) -> int:
    return entry.runtime_data.coordinator.data.session.image_count


def _reseeds(rig: FakeRig) -> int:
    """How many times the rig has been asked for /image-history?all=true."""
    return rig.reads("/image-history", {"all": "true"})


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


@pytest.mark.synthetic
async def test_a_disconnect_event_refetches_the_snapshot_before_the_next_tick(
    hass: HomeAssistant, loaded_entry, push, rig: FakeRig
) -> None:
    """§6.4: a device dropping out must not sit until the next 10 s poll.

    No capture holds the flat panel down, so its disconnected block is derived
    by the rule the corpus does show."""
    rig.requests.clear()
    rig.goto("equipment_disconnected")
    push({"Event": "FLAT-DISCONNECTED", "Time": AT})
    await hass.async_block_till_done()
    assert rig.reads("/equipment/info") == 1
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
    autofocus = loaded_entry.runtime_data.coordinator.data.session.autofocus
    assert autofocus.last_finished_at == datetime.fromisoformat(
        # The newest AUTOFOCUS-FINISHED of the dawn history, to the microsecond
        # the mapper truncates the wire's 100 ns to.
        "2026-09-04T03:21:11.414439-05:00"
    )


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
    first = (_reseeds(rig), rig.reads("/event-history"))
    connect(False)
    connect(True)
    await hass.async_block_till_done()

    assert (first, (_reseeds(rig), rig.reads("/event-history"))) == ((0, 0), (1, 1))


async def test_a_restart_replays_the_new_processs_event_history(
    loaded_entry, advance, rig: FakeRig
) -> None:
    """A restart resets `/event-history`, so the once-per-entry replay latch is
    scoped to the process it replayed."""
    rig.requests.clear()
    await advance("nina_restarted")
    assert rig.reads("/event-history") == 1


async def test_an_event_history_this_build_does_not_serve_is_replayed_once(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig: FakeRig, monkeypatch
) -> None:
    """A 404 cannot start working, and the setup replay would otherwise ask
    again on every 10 s tick.

    Injected rather than served from a rig state: every state serves
    `/event-history`, and dropping the route from one would rewrite a catalogue
    entry other tests read.
    """
    from custom_components.nina_astrophotography.api.errors import NinaEndpointError
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    asked = 0

    async def not_served(self, generation=None):
        nonlocal asked
        asked += 1
        raise NinaEndpointError("no /event-history")

    monkeypatch.setattr(NinaClientV2, "get_events", not_served)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert asked == 1


async def test_the_rigs_own_autofocus_timeout_bounds_a_running_run(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig: FakeRig, push, freezer
) -> None:
    """`FocuserSettings.AutoFocusTimeoutSeconds` is polled from /profile/show
    and reads 600 on this rig, so folding against the 300 s fallback would
    report a run eight minutes in as failed.

    `imaging_guiding` is the one state that serves the profile, and its clock
    is its own: 02:30 rig-local, eight minutes after the pushed start.
    """
    freezer.move_to("2026-09-05T07:30:00+00:00")
    rig.goto("imaging_guiding")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    push({"Event": "AUTOFOCUS-STARTING", "Time": "2026-09-05T02:22:00-05:00"})
    await hass.async_block_till_done()
    autofocus = config_entry.runtime_data.coordinator.data.session.autofocus
    assert autofocus.failed is False

"""Six tiers behind one 10 s tick — through public state and the rig's log.

`rig.requests` is the wire, not a coordinator internal: it records what left the
integration, which is exactly what the tiering exists to reduce.

Every fixture here takes `freezer` BEFORE the entry is set up. Home Assistant's
timers and `TierSchedule` both read `time.monotonic`, and freezing after setup
moves that clock by decades in one step — every tier reads as overdue, and the
first tick fires twice.
"""
from __future__ import annotations

import logging

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from helpers import load_fixture
from pytest_homeassistant_custom_component.common import async_fire_time_changed
from scenarios.fake_rig import FakeRig

from custom_components.nina_astrophotography.const import DOMAIN
from custom_components.nina_astrophotography.polling import TierSchedule

LIGHT = "light.n_i_n_a_flat_panel_light"

# What the dawn states leave unregistered, so the build answers 404 for them.
NOT_SERVED = ("/livestack/status", "/profile/show", "/equipment/focuser/last-af")
AT = "2026-09-05T01:41:53.9-05:00"


def captured(name: str) -> dict:
    """The first `name` event of the dawn history, as the socket sends it.

    Restamped: setup replays `/event-history`, so a payload carrying its
    captured time is one the fold has already taken. A live event is by
    definition one the history did not hold.
    """
    event = next(event for event in load_fixture("dawn_event_history.json")
                 if event["Event"] == name)
    return {**event, "Time": AT}


def reads(rig: FakeRig, path: str) -> int:
    return sum(1 for url, _ in rig.requests if url.endswith(path))


# DataUpdateCoordinator schedules its next refresh at a random microsecond
# within the second, so advancing by exactly the interval fires or does not by
# luck. One second of margin is well inside every cadence here.
_MARGIN = 1.0


async def tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory,
               seconds: float) -> None:
    """Advance the clock past `seconds` and let the coordinator's timer fire."""
    freezer.tick(seconds + _MARGIN)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


@pytest.fixture
async def tiers(hass, freezer, rig, config_entry):
    """A loaded entry on a named rig state, its setup traffic cleared away."""
    async def _load(state: str = "imaging", *, clear: bool = True) -> FakeRig:
        rig.goto(state)
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        if clear:
            rig.requests.clear()
        return rig

    return _load


@pytest.fixture
async def push_to(tiers, config_entry):
    """`tiers`, plus the socket-push callable bound to the same entry."""
    async def _load(state: str = "imaging", *, clear: bool = True):
        rig = await tiers(state, clear=clear)
        runtime = config_entry.runtime_data

        def _push(payload: dict) -> None:
            runtime.events._dispatch(payload, runtime.coordinator.generation)

        return rig, _push

    return _load


async def test_the_fast_tier_runs_on_every_tick(hass, tiers, freezer) -> None:
    rig = await tiers()
    for _ in range(3):
        await tick(hass, freezer, TierSchedule.FAST)
    assert reads(rig, "/equipment/info") == 3


async def test_the_sequence_tier_waits_out_its_cadence_on_an_idle_rig(
    hass, tiers, freezer
) -> None:
    """Three nodes read RUNNING on an idle rig with nothing happening, so the
    cadence follows activity and never node status — gating on the tree would
    hold /sequence/json at 30 s indefinitely, ~24 MB/day."""
    rig = await tiers()
    await tick(hass, freezer, TierSchedule.SEQUENCE_IMAGING)
    assert reads(rig, "/sequence/json") == 0
    await tick(hass, freezer, TierSchedule.SEQUENCE_IDLE)
    assert reads(rig, "/sequence/json") == 1


async def test_the_floor_backstops_the_flat_wizard(hass, tiers, freezer) -> None:
    """/flats/status has no event at all — the FLAT-* events are panel
    hardware, not the wizard — so only the floor ever reads it."""
    rig = await tiers()
    await tick(hass, freezer, TierSchedule.FAST)
    assert reads(rig, "/flats/status") == 0
    await tick(hass, freezer, TierSchedule.FLOOR)
    assert reads(rig, "/flats/status") == 1


async def test_an_endpoint_this_build_does_not_serve_is_asked_once(
    hass, tiers, freezer
) -> None:
    """A 404 cannot start working, and the floor would otherwise ask three
    times an hour for the life of the entry. `/equipment/focuser/last-af` is
    asked for zero times: it has no model until phase C.

    The setup traffic is counted here — that is the one request each is
    allowed."""
    rig = await tiers(clear=False)
    for _ in range(3):
        await tick(hass, freezer, TierSchedule.FLOOR)
    assert [reads(rig, path) for path in NOT_SERVED] == [1, 1, 0]


async def test_a_safety_event_refetches_without_waiting_for_a_tier(
    hass, push_to
) -> None:
    """§6.4: nothing safety-related waits for a tier."""
    rig, push = await push_to()
    push({"Event": "SAFETY-CHANGED", "Time": AT})
    await hass.async_block_till_done()
    assert reads(rig, "/equipment/info") == 1


async def test_ts_targetstart_never_refetches_the_sequence(
    hass, push_to, freezer
) -> None:
    """It fires once per exposure — 27 in 3.8 h — and its payload already
    carries TargetName, ProjectName, Rotation and TargetEndTime. Four ticks
    outlast the debounce, so a queued refetch would have been served."""
    rig, push = await push_to()
    for _ in range(10):
        push({"Event": "TS-TARGETSTART", "Time": "2026-09-05T06:41:53.9"})
    for _ in range(4):
        await tick(hass, freezer, TierSchedule.FAST)
    assert reads(rig, "/sequence/json") == 0


async def test_a_stack_status_event_reads_the_livestack_status_back(
    hass, push_to, config_entry
) -> None:
    """The event announces THAT the status changed; the status is read back from
    the endpoint rather than taken from the push.

    Polled by hand rather than by the clock: this state's flat panel is
    disconnected, so no entity exists to hold a listener and the coordinator
    schedules no tick of its own.
    """
    rig, push = await push_to("imaging_guiding")
    push(captured("STACK-STATUS"))
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert reads(rig, "/livestack/status") == 1


async def test_an_event_cannot_re_arm_an_endpoint_the_build_does_not_serve(
    hass, push_to, freezer
) -> None:
    """The latch outranks the event queue. Without that, every STACK-STATUS on
    a build with no livestack plugin buys another 404."""
    rig, push = await push_to(clear=False)
    assert reads(rig, "/livestack/status") == 1          # the setup attempt
    push(captured("STACK-STATUS"))
    await tick(hass, freezer, TierSchedule.FAST)
    assert reads(rig, "/livestack/status") == 1


async def test_sequence_finished_drops_the_cadence_to_idle(
    hass, push_to, freezer
) -> None:
    """A recent IMAGE-SAVE holds the tier at 30 s for five minutes after the
    last frame; SEQUENCE-FINISHED is the signal that ends the session, so it
    must not have to wait those five minutes out."""
    rig, push = await push_to()
    push({"Event": "IMAGE-SAVE", "Time": AT})
    await tick(hass, freezer, TierSchedule.SEQUENCE_IMAGING)
    assert reads(rig, "/sequence/json") == 1
    push({"Event": "SEQUENCE-FINISHED", "Time": AT})
    await tick(hass, freezer, TierSchedule.SEQUENCE_IMAGING)
    assert reads(rig, "/sequence/json") == 1


async def test_an_event_driven_read_that_fails_transiently_is_asked_again(
    hass, push_to, freezer, monkeypatch
) -> None:
    """A queued endpoint dropped on a timeout would wait out the five-minute
    floor — the event's whole point was not to."""
    from custom_components.nina_astrophotography.api.errors import NinaConnectionError
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    rig, push = await push_to("imaging_guiding")
    coordinator = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.coordinator

    async def timing_out(self):
        raise NinaConnectionError("timeout")

    # Restored by hand, not with monkeypatch.undo(): the same monkeypatch
    # instance installed the fake transport, and undo() would take that too.
    working = NinaClientV2.get_livestack
    monkeypatch.setattr(NinaClientV2, "get_livestack", timing_out)
    push(captured("STACK-STATUS"))
    await coordinator.async_refresh()
    monkeypatch.setattr(NinaClientV2, "get_livestack", working)
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert reads(rig, "/livestack/status") == 1


@pytest.mark.synthetic
async def test_a_tier_read_that_raises_anything_does_not_fail_the_poll(
    hass, tiers, freezer, monkeypatch, caplog
) -> None:
    """The tiers run outside the fast tier's own guard, so one unanticipated
    wire shape would otherwise take eleven devices unavailable over a
    five-minute endpoint — and say so once per poll while it did.

    Injected rather than served from a rig state: every mapper is
    scalar-defensive, so no captured or malformed `/sequence/json` document can
    produce the raise this guards against.
    """
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    async def get_sequence(self):
        raise TypeError("a shape no mapper anticipated")

    await tiers()
    monkeypatch.setattr(NinaClientV2, "get_sequence", get_sequence)
    with caplog.at_level(logging.WARNING):
        for _ in range(2):
            await tick(hass, freezer, TierSchedule.SEQUENCE_IDLE)
    warnings = [r for r in caplog.records
                if r.levelno == logging.WARNING
                and r.name.startswith("custom_components.nina_astrophotography")]
    assert hass.states.get(LIGHT).state != "unavailable"
    assert len(warnings) == 1


async def test_a_rig_that_serves_every_endpoint_publishes_all_four_models(
    hass, tiers, config_entry
) -> None:
    """The floor tier's three reads and the sequence tier's one, mapped and
    published together — the livestack status included, which arrives as a
    bare string rather than the object the spec documents."""
    await tiers("imaging_guiding")
    data = config_entry.runtime_data.coordinator.data
    assert data.livestack.running is True
    assert data.profile.max_minutes_after_meridian == 15.0
    # An idle flat wizard reports -1 iterations; that is not a count.
    assert data.flats.total_iterations is None
    assert data.sequence is not None

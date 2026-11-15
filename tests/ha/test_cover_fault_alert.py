"""The flat cover fault blueprint, run against the integration's own sensor."""

from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

COVER_STATE = "sensor.n_i_n_a_flat_panel_cover_state"
INPUTS = {"cover_state": COVER_STATE, "notify_target": ["notify.phone"]}


@pytest.fixture
def notified(hass: HomeAssistant):
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
def held(hass: HomeAssistant, freezer):
    async def _held(seconds: float) -> None:
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    return _held


async def test_a_cover_part_way_within_its_travel_does_not_alert(
    installed, set_up_with_flat_device, notified, held
) -> None:
    await installed("cover_fault_alert.yaml", INPUTS)
    await set_up_with_flat_device(cover_state="NeitherOpenNorClosed")

    await held(59)

    assert notified == []


@pytest.mark.parametrize(
    ("cover_state", "held_for", "says"),
    [("Error", 0, "reports an error"), ("NeitherOpenNorClosed", 61, "stuck part-way")],
)
async def test_the_alert_names_the_fault(
    installed,
    set_up_with_flat_device,
    notified,
    held,
    cover_state: str,
    held_for: float,
    says: str,
) -> None:
    await installed("cover_fault_alert.yaml", INPUTS)
    await set_up_with_flat_device(cover_state=cover_state)

    await held(held_for)

    assert [says in call.data["message"] for call in notified] == [True]


async def test_a_cover_part_way_when_home_assistant_starts_alerts(
    hass: HomeAssistant, installed, set_up_with_flat_device, notified, held
) -> None:
    """Already part-way when the automation arms, the cover makes no state
    change for a state trigger to see.
    """
    await set_up_with_flat_device(cover_state="NeitherOpenNorClosed")
    await installed("cover_fault_alert.yaml", INPUTS)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)

    await held(61)

    assert len(notified) == 1


@pytest.mark.parametrize(
    ("moved_to", "alerts"), [("NeitherOpenNorClosed", 0), ("Error", 1)]
)
async def test_a_cover_changing_while_a_start_waits_is_judged_when_the_wait_ends(
    hass: HomeAssistant,
    installed,
    set_up_with_flat_device,
    flat_device_changes,
    notified,
    held,
    freezer,
    moved_to: str,
    alerts: int,
) -> None:
    """A cover that begins a normal move late in the wait has not been part-way
    long enough, and an error during it would otherwise be dropped by the run
    already under way.
    """
    await set_up_with_flat_device(cover_state="Open")
    await installed("cover_fault_alert.yaml", INPUTS)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    # Not `held`: the start's run is in its delay, which settling would await.
    freezer.tick(timedelta(seconds=50))
    async_fire_time_changed(hass)
    await flat_device_changes(cover_state=moved_to)

    await held(11)

    assert len(notified) == alerts


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("pushed", "alerts"),
    [(["FLAT-COVER-OPENED"], 0), ([], 1)],
    ids=["opened, then disconnected", "left part-way"],
)
async def test_a_panel_disconnected_mid_move_alerts_unless_the_move_finished(
    hass: HomeAssistant,
    installed,
    set_up_with_flat_device,
    flat_device_changes,
    flat_panel_disconnects,
    push,
    notified,
    held,
    pushed: list[str],
    alerts: int,
) -> None:
    """The rig's own order: a poll reads the cover mid-move, N.I.N.A. reports
    it opened, and the sequence disconnects the panel within the second.
    """
    await installed("cover_fault_alert.yaml", INPUTS)
    await set_up_with_flat_device()
    await flat_device_changes(cover_state="NeitherOpenNorClosed")
    for name in pushed:
        push({"Event": name})
    await flat_panel_disconnects()

    await held(61)

    assert len(notified) == alerts


@pytest.mark.parametrize(
    ("readings", "alerts"),
    [(["Closed", "NeitherOpenNorClosed"], 1), (["NeitherOpenNorClosed"], 0)],
    ids=["part-way after a move", "first read part-way"],
)
async def test_only_after_a_move_ignores_a_cover_first_read_part_way(
    installed,
    set_up_with_flat_device,
    flat_device_changes,
    notified,
    held,
    readings: list[str],
    alerts: int,
) -> None:
    """An unhomed cover can read part-way from power-up while idle."""
    await installed("cover_fault_alert.yaml", INPUTS | {"after_move_only": True})
    await set_up_with_flat_device(cover_state=readings[0])
    for reading in readings[1:]:
        await flat_device_changes(cover_state=reading)

    await held(61)

    assert len(notified) == alerts

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


@pytest.mark.parametrize(("seconds", "alerts"), [(59, 0), (61, 1)])
async def test_a_cover_part_way_alerts_once_held_past_its_travel(
    installed, set_up_with_flat_device, notified, held, seconds: float, alerts: int
) -> None:
    await installed("cover_fault_alert.yaml", INPUTS)
    await set_up_with_flat_device(cover_state="NeitherOpenNorClosed")

    await held(seconds)

    assert len(notified) == alerts


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

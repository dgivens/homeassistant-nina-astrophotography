"""The flat panel lit with cover open blueprint, run against the integration's
own light and cover sensor.
"""

import asyncio
from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

BLUEPRINT = "flat_panel_lit_open_alert.yaml"
INPUTS = {
    "flat_panel_light": "light.n_i_n_a_flat_panel_light",
    "cover_state": "sensor.n_i_n_a_flat_panel_cover_state",
    "notify_target": ["notify.phone"],
}
LIT = {"brightness": 2048.0, "light_on": True}
DARK = {"brightness": 0.0, "light_on": False}


@pytest.fixture
def notified(hass: HomeAssistant):
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
def held(hass: HomeAssistant, freezer):
    """Move the clock on and let the run take its next steps.

    Not `async_block_till_done`: a start's run in its delay is a task it would
    wait on.
    """

    async def _held(seconds: float) -> None:
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        for _ in range(20):
            await asyncio.sleep(0)

    return _held


@pytest.fixture
async def armed(installed, set_up_with_flat_device, freezer):
    """The panel closed and dark at setup, under the blueprint.

    After `freezer`, so the count is scheduled on the frozen clock.
    """
    await set_up_with_flat_device()
    await installed(BLUEPRINT, INPUTS)


@pytest.mark.usefixtures("armed")
@pytest.mark.parametrize(
    ("cover_state", "seconds", "alerts"),
    [("Open", 19, 0), ("Open", 21, 1), ("NeitherOpenNorClosed", 21, 1)],
)
async def test_a_lit_panel_uncovered_past_the_hold_alerts(
    flat_device_changes, notified, held, cover_state: str, seconds: float, alerts: int
) -> None:
    await flat_device_changes(**LIT, cover_state=cover_state)

    await held(seconds)

    assert len(notified) == alerts


@pytest.mark.usefixtures("armed")
@pytest.mark.parametrize(
    "panel",
    [
        {**LIT, "cover_state": "Closed"},
        {**LIT, "cover_state": "Unknown"},
        {**LIT, "cover_state": "Error"},
        {**LIT, "cover_state": "NotPresent"},
        {**DARK, "cover_state": "Open"},
    ],
    ids=["closed", "unknown", "error", "no cover", "dark"],
)
async def test_only_a_lit_panel_reading_open_or_part_way_alerts(
    flat_device_changes, notified, held, panel: dict
) -> None:
    await flat_device_changes(**panel)

    await held(60)

    assert notified == []


@pytest.mark.usefixtures("armed")
async def test_a_single_lit_and_open_reading_stays_quiet(
    flat_device_changes, notified, held
) -> None:
    await flat_device_changes(**LIT, cover_state="Open")
    await held(10)
    await flat_device_changes(**DARK, cover_state="Open")

    await held(60)

    assert notified == []


@pytest.mark.usefixtures("armed")
async def test_a_lit_cover_opening_is_counted_from_leaving_closed(
    flat_device_changes, notified, held
) -> None:
    await flat_device_changes(**LIT, cover_state="NeitherOpenNorClosed")
    await held(15)
    await flat_device_changes(**LIT, cover_state="Open")

    await held(6)

    assert len(notified) == 1


@pytest.mark.parametrize(
    "panel",
    [{**LIT, "cover_state": "Open"}, {}],
    ids=["already at start", "during the start's wait"],
)
async def test_a_panel_lit_and_open_around_a_start_alerts_once(
    hass: HomeAssistant,
    installed,
    set_up_with_flat_device,
    flat_device_changes,
    notified,
    held,
    panel: dict,
) -> None:
    await set_up_with_flat_device(**panel)
    await installed(BLUEPRINT, INPUTS)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await held(5)
    await flat_device_changes(**LIT, cover_state="Open")

    await held(60)

    assert len(notified) == 1


@pytest.mark.usefixtures("armed")
@pytest.mark.parametrize(
    ("cover_state", "says"),
    [("Open", "cover open"), ("NeitherOpenNorClosed", "cover part-way")],
)
async def test_the_alert_says_where_the_cover_is(
    flat_device_changes, notified, held, cover_state: str, says: str
) -> None:
    await flat_device_changes(**LIT, cover_state=cover_state)

    await held(21)

    assert [says in call.data["message"] for call in notified] == [True]

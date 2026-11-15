"""The flat panel left lit blueprint, run against the integration's own light."""

import asyncio
from datetime import datetime, timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from helpers import image_saved

BLUEPRINT = "flat_panel_left_lit_alert.yaml"
INPUTS = {
    "flat_panel_light": "light.n_i_n_a_flat_panel_light",
    "notify_target": ["notify.phone"],
}
LIT = {"brightness": 2048.0, "light_on": True}
SAVED_FROM = datetime.fromisoformat("2026-09-04T05:00:00-05:00")


@pytest.fixture
def notified(hass: HomeAssistant):
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
def later(hass: HomeAssistant, freezer):
    """Move the clock on and let the run take its next steps.

    Not `async_block_till_done`: a run counting down is a task it would wait on.
    """

    async def _later(minutes: float) -> None:
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass)
        for _ in range(20):
            await asyncio.sleep(0)

    return _later


@pytest.fixture
async def switched_on(installed, set_up_with_flat_device, flat_device_changes, freezer):
    """The panel off at setup, then switched on under the blueprint.

    After `freezer`, so the countdown is scheduled on the frozen clock.
    """
    await set_up_with_flat_device()
    await installed(BLUEPRINT, INPUTS)
    await flat_device_changes(**LIT)


@pytest.mark.usefixtures("switched_on")
@pytest.mark.parametrize(("minutes", "alerts"), [(29, 0), (31, 1)])
async def test_a_panel_lit_with_no_flat_alerts_past_the_threshold(
    notified, later, minutes: float, alerts: int
) -> None:
    await later(minutes)

    assert len(notified) == alerts


@pytest.mark.synthetic
@pytest.mark.usefixtures("switched_on")
@pytest.mark.parametrize(("image_type", "alerts"), [("FLAT", 0), ("DARK", 1)])
async def test_only_flats_saved_under_the_panel_keep_it_quiet(
    push, notified, later, image_type: str, alerts: int
) -> None:
    for minute in range(10, 70, 10):
        await later(10)
        push(
            image_saved(
                image_type,
                Filename=f"frame_{minute:04d}.fits",
                Date=(SAVED_FROM + timedelta(minutes=minute)).isoformat(),
            )
        )

    await later(10)

    assert len(notified) == alerts


@pytest.mark.usefixtures("switched_on")
@pytest.mark.parametrize(
    "change",
    [{}, {"connected": False, "light_on": None, "brightness_range": None}],
    ids=["switched off", "disconnected"],
)
async def test_a_panel_that_stops_reading_lit_before_the_threshold_stays_quiet(
    flat_device_changes, notified, later, change: dict
) -> None:
    await later(20)
    await flat_device_changes(**change)

    await later(20)

    assert len(notified) == 0


async def test_a_panel_lit_when_home_assistant_starts_alerts(
    hass: HomeAssistant, installed, set_up_with_flat_device, notified, later
) -> None:
    await set_up_with_flat_device(**LIT)
    await installed(BLUEPRINT, INPUTS)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)

    await later(31)

    assert len(notified) == 1

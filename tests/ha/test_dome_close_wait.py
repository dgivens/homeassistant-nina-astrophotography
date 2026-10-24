"""Both closing blueprints wait for the shutter to report closed, run rather
than schema-checked.

A close is answered before the roof moves and raises no event when it has
closed (`docs/v2.0-design.md`, the dated dome section), so the polled shutter
status is the only confirmation, and a roof stuck open has to say so.
"""

import asyncio
from datetime import timedelta

from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.nina_astrophotography.const import DOMAIN

SHUTTER = "sensor.rig_dome_shutter_status"
PARKED = "binary_sensor.rig_mount_at_park"
TIMEOUT_MINUTES = 5
ALARM = "🚨 Roof did not close"

INPUTS = {
    "session_shutdown.yaml": {
        "nina_rig": "device-id",
        "sequence_running": "binary_sensor.rig_sequencer_running",
        "mount_parked": PARKED,
        "only_if_sequence_stopped": False,
    },
    "weather_abort.yaml": {
        "nina_rig": "device-id",
        "safety_unsafe": "binary_sensor.rig_safety_monitor_unsafe",
        "safety_connected": "binary_sensor.rig_safety_monitor_connected",
        "mount_parked": PARKED,
    },
}


@pytest.fixture
async def closing(hass: HomeAssistant, installed):
    """Run `blueprint` up to its wait for the shutter, over a parked mount and
    an open shutter. Returns the notify calls.

    Not `async_block_till_done` while the run waits: the run is a task it
    waits on, and it would wait out the timeout with it.
    """

    async def _run(blueprint: str):
        closed = None
        for service in ("sequence_stop", "mount_park", "dome_close", "camera_warm"):
            calls = async_mock_service(hass, DOMAIN, service)
            if service == "dome_close":
                closed = calls
        sent = async_mock_service(hass, "notify", "send_message")
        hass.states.async_set(PARKED, "on")
        hass.states.async_set(SHUTTER, "open")
        await installed(
            blueprint,
            INPUTS[blueprint]
            | {
                "close_dome": True,
                "dome_shutter": [SHUTTER],
                "close_timeout_minutes": TIMEOUT_MINUTES,
                "notify_target": ["notify.phone"],
            },
        )
        (automation,) = hass.states.async_entity_ids(AUTOMATION_DOMAIN)
        await hass.services.async_call(
            AUTOMATION_DOMAIN,
            "trigger",
            {"entity_id": automation, "skip_condition": True},
        )
        for _ in range(100):
            if closed:
                break
            await asyncio.sleep(0)
        assert closed, "the run never closed the dome"
        await asyncio.sleep(0)
        return sent

    return _run


async def _minutes_later(hass: HomeAssistant, minutes: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    for _ in range(20):
        await asyncio.sleep(0)


async def _titles(hass: HomeAssistant, sent) -> list[str]:
    """Every notification, once the run has ended: past the camera warming,
    whose delay starts only after the steps before it have run.
    """
    for _ in range(3):
        await _minutes_later(hass, 120)
    await hass.async_block_till_done()
    return [call.data["title"] for call in sent]


@pytest.mark.parametrize("blueprint", INPUTS)
async def test_a_roof_that_closes_raises_no_alarm(
    hass: HomeAssistant, closing, blueprint: str
) -> None:
    sent = await closing(blueprint)
    hass.states.async_set(SHUTTER, "closed")
    assert ALARM not in await _titles(hass, sent)


@pytest.mark.parametrize("blueprint", INPUTS)
async def test_a_roof_still_open_after_the_timeout_raises_the_alarm(
    hass: HomeAssistant, closing, blueprint: str
) -> None:
    sent = await closing(blueprint)
    await _minutes_later(hass, TIMEOUT_MINUTES + 0.1)
    assert ALARM in await _titles(hass, sent)

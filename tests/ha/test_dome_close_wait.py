"""Both closing blueprints wait for the shutter to report closed, run rather
than schema-checked.

A close is answered before the roof moves, and not every close raises an
event (`docs/v2.0-design.md`, the dated dome sections), so the polled shutter
status is the only confirmation, and a roof stuck open has to say so.
"""

import asyncio
from datetime import timedelta
from typing import NamedTuple

from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall
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
RETRYING = "⚠️ Roof not closed yet"

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


class Run(NamedTuple):
    """What a run sent: the closes, and the notifications."""

    closes: list[ServiceCall]
    notified: list[ServiceCall]


async def _settle() -> None:
    """Let the run take its next steps.

    Not `async_block_till_done` while the run waits: the run is a task it
    waits on, and it would wait out the timeout with it.
    """
    for _ in range(20):
        await asyncio.sleep(0)


async def _minutes_later(hass: HomeAssistant, minutes: float) -> None:
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
    await _settle()


@pytest.fixture
async def closing(hass: HomeAssistant, installed):
    """Run `blueprint` up to its wait for the shutter, over a parked mount and
    an open shutter.
    """

    async def _run(blueprint: str, shutter: tuple[str, ...] = (SHUTTER,)) -> Run:
        for service in ("sequence_stop", "mount_park", "camera_warm"):
            async_mock_service(hass, DOMAIN, service)
        run = Run(
            async_mock_service(hass, DOMAIN, "dome_close"),
            async_mock_service(hass, "notify", "send_message"),
        )
        hass.states.async_set(PARKED, "on")
        hass.states.async_set(SHUTTER, "open")
        await installed(
            blueprint,
            INPUTS[blueprint]
            | {
                "close_dome": True,
                "dome_shutter": list(shutter),
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
            if run.closes:
                break
            await asyncio.sleep(0)
        assert run.closes, "the run never closed the dome"
        await _settle()
        return run

    return _run


async def _finished(hass: HomeAssistant, run: Run) -> tuple[int, list[str]]:
    """How many closes, and every notification's title, once the run has ended:
    past both waits and the camera warming, whose delays each start only after
    the steps before them.
    """
    for _ in range(4):
        await _minutes_later(hass, 120)
    await hass.async_block_till_done()
    return len(run.closes), [call.data["title"] for call in run.notified]


def _alarm(run: Run) -> str:
    (call,) = [c for c in run.notified if c.data["title"] == ALARM]
    return " ".join(call.data["message"].split())


@pytest.mark.parametrize("blueprint", INPUTS)
async def test_a_roof_that_closes_is_closed_once_and_raises_no_alarm(
    hass: HomeAssistant, closing, blueprint: str
) -> None:
    run = await closing(blueprint)
    hass.states.async_set(SHUTTER, "closed")
    closes, titles = await _finished(hass, run)
    assert (closes, ALARM in titles) == (1, False)


@pytest.mark.parametrize("blueprint", INPUTS)
async def test_a_shutter_error_is_closed_again_at_once(
    hass: HomeAssistant, closing, blueprint: str
) -> None:
    """An error ends the first wait without its timeout; the second close
    clears it here.
    """
    run = await closing(blueprint)
    hass.states.async_set(SHUTTER, "error")
    await _settle()
    assert len(run.closes) == 2
    hass.states.async_set(SHUTTER, "closed")
    closes, titles = await _finished(hass, run)
    assert (closes, ALARM in titles) == (2, False)


@pytest.mark.parametrize(
    ("shutter", "says"),
    [
        ("open", "its shutter reads open"),
        ("error", "its shutter reads error"),
        ("unavailable", "lost contact with the dome"),
    ],
)
@pytest.mark.parametrize("blueprint", INPUTS)
async def test_a_roof_that_will_not_close_raises_the_alarm(
    hass: HomeAssistant, closing, blueprint: str, shutter: str, says: str
) -> None:
    """Closed twice, then the alarm, saying what the shutter last read."""
    run = await closing(blueprint)
    hass.states.async_set(SHUTTER, shutter)
    closes, titles = await _finished(hass, run)
    assert (closes, ALARM in titles) == (2, True)
    assert says in _alarm(run)


@pytest.mark.parametrize("blueprint", INPUTS)
async def test_each_wait_is_the_configured_timeout(
    hass: HomeAssistant, closing, blueprint: str
) -> None:
    """A warning and the second close at the first timeout, the alarm at the
    second: in rain the first warning is the one that matters.
    """
    run = await closing(blueprint)

    def titles() -> list[str]:
        return [call.data["title"] for call in run.notified]

    await _minutes_later(hass, TIMEOUT_MINUTES - 0.5)
    assert (len(run.closes), RETRYING in titles()) == (1, False)
    await _minutes_later(hass, TIMEOUT_MINUTES + 0.1)
    assert (len(run.closes), RETRYING in titles()) == (2, True)
    await _minutes_later(hass, TIMEOUT_MINUTES - 0.5)
    assert ALARM not in titles()
    await _minutes_later(hass, TIMEOUT_MINUTES + 0.1)
    assert ALARM in titles()


@pytest.mark.parametrize("blueprint", INPUTS)
async def test_without_a_shutter_status_the_dome_is_closed_once(
    hass: HomeAssistant, closing, blueprint: str
) -> None:
    """The default, which every upgraded automation has: no wait, no alarm."""
    run = await closing(blueprint, shutter=())
    closes, titles = await _finished(hass, run)
    assert (closes, ALARM in titles) == (1, False)

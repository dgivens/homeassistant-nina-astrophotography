"""The stall alert's gates and clocks, run rather than schema-checked.

`test_blueprints.py` proves Home Assistant ACCEPTS this blueprint. It cannot
prove the config does anything, and two defects here were valid YAML that suite
was happy with: gates written inside a `choose` branch, where a failing
condition aborts only the branch and the parent sequence alerts anyway, and
clocks that started before the sequence did. Both made the blueprint alert
every minute of every night while the suite stayed green.

So these tests fire the triggers and read the notification that comes out.
"""
import asyncio
from datetime import timedelta

import pytest
from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from tests.ha.test_blueprints import OPTIONAL, REQUIRED, installed  # noqa: F401

BLUEPRINT = "imaging_stall_alert.yaml"
T0 = dt_util.parse_datetime("2026-09-17T01:00:00+00:00")

# The thresholds this input set configures, which the clocks below are chosen
# against: quiet for 30 min, or no frame for 300 s + 45 min.
QUIET_MINUTES = OPTIONAL[BLUEPRINT]["imaging_quiet_minutes"]

# A rig mid-night with nothing arriving. `last_frame_at` holds LAST night's
# frame: N.I.N.A. reports the newest frame it knows of, which survives across
# nights while it stays up, so this is what a real 20:00 start looks like.
RIG = {
    "binary_sensor.rig_sequencer_running": "off",
    "binary_sensor.rig_imaging": "off",
    "binary_sensor.rig_scheduler_waiting": "off",
    "binary_sensor.rig_safety_monitor_unsafe": "off",
    "binary_sensor.rig_mount_at_park": "off",
    "sensor.rig_last_frame_at": "2026-09-16T10:00:00+00:00",
    "sensor.rig_camera_state": "Idle",
    "sensor.rig_last_image_target": "M31",
    "sensor.rig_sequence_target": "M31",
    "sensor.rig_camera_temperature": "-10.0",
    "sensor.rig_camera_cooler_power": "42",
    "sensor.rig_guider_status": "Lost lock",
}


def alert(hass: HomeAssistant) -> dict | None:
    """The blueprint's persistent notification, or None.

    Persistent notifications are not entities — `hass.states` never shows them.
    """
    raised = hass.data.get("persistent_notification") or {}
    return next(iter(raised.values()), None)


async def tick(hass: HomeAssistant, when) -> None:
    """Fire the quiet arm's minute tick and let the run finish.

    Zero-delay yields, never `asyncio.sleep(d)`: under `freezer` the event
    loop's monotonic clock is frozen too, so a real sleep never wakes.
    `async_block_till_done` is no good either — on a tick that DOES alert, the
    run parks in `wait_for_trigger` and never returns.
    """
    async_fire_time_changed(hass, when)
    for _ in range(2000):
        await asyncio.sleep(0)
        if alert(hass):
            return


@pytest.fixture
async def rig(hass: HomeAssistant, installed, freezer):  # noqa: F811
    """The blueprint watching a rig whose sequencer is not running yet."""
    freezer.move_to(T0)
    hass.states.async_set("sun.sun", "below_horizon")
    for entity, state in RIG.items():
        hass.states.async_set(entity, state)
    assert await async_setup_component(hass, "persistent_notification", {})
    assert await async_setup_component(hass, "notify", {})
    assert await async_setup_component(hass, AUTOMATION_DOMAIN, {
        AUTOMATION_DOMAIN: {"use_blueprint": {
            "path": f"nina_astrophotography/{BLUEPRINT}",
            "input": REQUIRED[BLUEPRINT] | OPTIONAL[BLUEPRINT]}}})
    await hass.async_block_till_done()
    return freezer


async def start_sequence(hass: HomeAssistant, freezer, when) -> None:
    """Start the sequencer at `when`, which is where every clock is floored."""
    freezer.move_to(when)
    hass.states.async_set("binary_sensor.rig_sequencer_running", "on")
    await hass.async_block_till_done()


async def test_a_quiet_rig_is_reported(hass: HomeAssistant, rig) -> None:
    """The positive control: without it every silence below proves nothing."""
    await start_sequence(hass, rig, T0)

    rig.move_to(T0 + timedelta(minutes=QUIET_MINUTES + 5))
    await tick(hass, T0 + timedelta(minutes=QUIET_MINUTES + 5))

    assert alert(hass) is not None


@pytest.mark.parametrize(("entity", "state"), [
    ("binary_sensor.rig_scheduler_waiting", "on"),
    ("binary_sensor.rig_safety_monitor_unsafe", "on"),
], ids=["scheduler is waiting", "conditions are unsafe"])
async def test_a_gate_suppresses_the_alert(
    hass: HomeAssistant, rig, entity: str, state: str
) -> None:
    """A target-window wait is hours of nothing, and a safety hold belongs to
    the abort blueprint. Both must silence a rig that would otherwise alert.

    These fail if the gates move back inside a `choose` branch, where a failing
    condition aborts the branch and the run alerts regardless.
    """
    await start_sequence(hass, rig, T0)
    hass.states.async_set(entity, state)

    rig.move_to(T0 + timedelta(minutes=QUIET_MINUTES + 5))
    await tick(hass, T0 + timedelta(minutes=QUIET_MINUTES + 5))

    assert alert(hass) is None


async def test_a_just_started_sequence_is_silent(
    hass: HomeAssistant, rig
) -> None:
    """No clock may start before the sequencer does.

    `imaging` has been off all day and `last_frame_at` holds last night's
    frame, so both thresholds read "hours quiet" the instant a sequence starts
    — during cool-down, slew, plate-solve and the first autofocus, before a
    frame is physically possible.
    """
    start = T0 + timedelta(hours=1)
    await start_sequence(hass, rig, start)

    rig.move_to(start + timedelta(minutes=QUIET_MINUTES - 1))
    await tick(hass, start + timedelta(minutes=QUIET_MINUTES - 1))

    assert alert(hass) is None


async def test_an_unreachable_rig_reports_only_what_it_knows(
    hass: HomeAssistant, rig
) -> None:
    """Every entity is unavailable, so the field list would be a row of the
    same word — and a park state nothing can read must not be reported as
    "not parked", which a reader could act on at 3am."""
    await start_sequence(hass, rig, T0)
    rig.move_to(T0 + timedelta(minutes=10))
    for entity in RIG:
        hass.states.async_set(entity, "unavailable")
    await hass.async_block_till_done()

    rig.move_to(T0 + timedelta(minutes=13))
    await tick(hass, T0 + timedelta(minutes=13))

    assert "parked" not in alert(hass)["message"]

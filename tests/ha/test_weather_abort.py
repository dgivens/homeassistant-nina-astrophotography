"""The abort blueprint's unreachable-rig arm and its resume, run rather than
schema-checked.

`test_blueprints.py` proves Home Assistant accepts this blueprint; these fire
its triggers and read what comes out.
"""

import asyncio
from datetime import timedelta

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.nina_astrophotography.const import DOMAIN

CONNECTED = "binary_sensor.rig_safety_monitor_connected"
UNSAFE = "binary_sensor.rig_safety_monitor_unsafe"
PARKED = "binary_sensor.rig_mount_at_park"
FROZEN = "binary_sensor.rig_weather_readings_frozen"
REACHABLE = "binary_sensor.rig_reachable"
UNREACHABLE = "⚠️ N.I.N.A. unreachable"

INPUTS = {
    "nina_rig": "device-id",
    "safety_unsafe": UNSAFE,
    "safety_connected": CONNECTED,
    "mount_parked": PARKED,
    "notify_target": ["notify.phone"],
}


@pytest.fixture
async def watching(hass: HomeAssistant, installed):
    """The blueprint over a connected monitor whose entry is in `entry_state`,
    watching the rig's Reachable sensor if `reachable`.

    Returns the notify calls.
    """

    async def _set_up(entry_state: ConfigEntryState, *, reachable: bool = False):
        entry = MockConfigEntry(domain=DOMAIN, state=entry_state)
        entry.add_to_hass(hass)
        rows = {"safety_connected": CONNECTED, "reachable": REACHABLE}
        for key, entity_id in rows.items():
            er.async_get(hass).async_get_or_create(
                "binary_sensor",
                DOMAIN,
                key,
                suggested_object_id=entity_id.split(".", 1)[1],
                config_entry=entry,
            )
            hass.states.async_set(entity_id, "on")
        sent = async_mock_service(hass, "notify", "send_message")
        inputs = INPUTS | ({"rig_reachable": [REACHABLE]} if reachable else {})
        await installed("weather_abort.yaml", inputs)
        return sent

    return _set_up


@pytest.mark.parametrize(
    ("entry_state", "attributes", "notified"),
    [
        (ConfigEntryState.LOADED, {}, True),
        (ConfigEntryState.LOADED, {"restored": True}, False),
        (ConfigEntryState.SETUP_RETRY, {"restored": True}, True),
    ],
    ids=["link lost", "monitor not reported yet", "entry failed to load"],
)
async def test_an_unavailable_monitor_row(
    hass: HomeAssistant,
    watching,
    entry_state: ConfigEntryState,
    attributes: dict,
    notified: bool,
) -> None:
    """Only a rig N.I.N.A. is not answering for is reported unreachable.

    A monitor the rig has not reported since the entry loaded is a restored
    registry row — `unavailable`, like a lost link — while N.I.N.A. answers.
    Restored under an entry that could not load, it is the rig itself.
    """
    sent = await watching(entry_state)

    await _hold(hass, {CONNECTED: ("unavailable", attributes)})

    expected = [UNREACHABLE] if notified else []
    assert [call.data["title"] for call in sent] == expected


@pytest.mark.parametrize(
    ("entry_state", "rows", "notified"),
    [
        (ConfigEntryState.LOADED, {REACHABLE: ("off", {})}, 1),
        (
            ConfigEntryState.LOADED,
            {REACHABLE: ("off", {}), CONNECTED: ("unavailable", {})},
            1,
        ),
        (ConfigEntryState.LOADED, {CONNECTED: ("unavailable", {})}, 0),
        (
            ConfigEntryState.SETUP_RETRY,
            {REACHABLE: ("unavailable", {"restored": True})},
            1,
        ),
    ],
    ids=["missed polls", "grace run out too", "monitor row alone", "entry failed"],
)
async def test_a_rig_with_a_reachable_sensor_is_reported_through_it(
    hass: HomeAssistant,
    watching,
    entry_state: ConfigEntryState,
    rows: dict,
    notified: int,
) -> None:
    """Once, however many rows go: the monitor's row going `unavailable` is
    the same outage, reported late.
    """
    sent = await watching(entry_state, reachable=True)

    await _hold(hass, rows)

    assert [call.data["title"] for call in sent] == [UNREACHABLE] * notified


@pytest.fixture
async def aborted(hass: HomeAssistant, freezer, installed):
    """An abort under auto-resume, over frozen weather readings, with conditions
    then safe for the resume delay. Returns the `sequence_start` calls.
    """
    for entity_id, state in {
        UNSAFE: "off",
        CONNECTED: "on",
        PARKED: "on",
        FROZEN: "on",
    }.items():
        hass.states.async_set(entity_id, state)
    for service in ("sequence_stop", "mount_park", "camera_warm"):
        async_mock_service(hass, DOMAIN, service)
    started = async_mock_service(hass, DOMAIN, "sequence_start")
    async_mock_service(hass, "notify", "send_message")
    await installed(
        "weather_abort.yaml",
        INPUTS | {"auto_resume": True, "weather_frozen": [FROZEN]},
    )
    # Not `async_block_till_done`: the run waiting to resume is a task it
    # would wait on.
    hass.states.async_set(UNSAFE, "on")
    await _settle()
    hass.states.async_set(UNSAFE, "off")
    await _settle()
    await _later(hass, freezer, minutes=16)
    return started


async def test_frozen_weather_readings_hold_the_resume(aborted) -> None:
    """A monitor fed by a frozen station reads safe whatever the sky."""
    assert not aborted


async def test_the_resume_follows_once_the_readings_move_and_stay_safe(
    hass: HomeAssistant, freezer, aborted
) -> None:
    hass.states.async_set(FROZEN, "off")
    await _settle()
    await _later(hass, freezer, minutes=16)
    assert aborted


async def _later(hass: HomeAssistant, freezer, minutes: float) -> None:
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await _settle()


async def _settle() -> None:
    for _ in range(50):
        await asyncio.sleep(0)


async def _hold(hass: HomeAssistant, rows: dict) -> None:
    """Set `rows` to their (state, attributes) and hold them past the arm's wait."""
    for entity_id, (state, attributes) in rows.items():
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2, seconds=1))
    await hass.async_block_till_done()

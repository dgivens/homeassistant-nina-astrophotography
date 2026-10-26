"""The abort blueprint's unreachable-rig arm, run rather than schema-checked.

`test_blueprints.py` proves Home Assistant accepts this blueprint; these fire
the `rig_unreachable` trigger and read which notification comes out.
"""

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
REACHABLE = "binary_sensor.rig_reachable"

INPUTS = {
    "nina_rig": "device-id",
    "safety_unsafe": "binary_sensor.rig_safety_monitor_unsafe",
    "safety_connected": CONNECTED,
    "mount_parked": "binary_sensor.rig_mount_at_park",
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


UNREACHABLE = "⚠️ N.I.N.A. unreachable"


async def _hold(hass: HomeAssistant, rows: dict) -> None:
    """Set `rows` to their (state, attributes) and hold them past the arm's wait."""
    for entity_id, (state, attributes) in rows.items():
        hass.states.async_set(entity_id, state, attributes)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2, seconds=1))
    await hass.async_block_till_done()

"""The abort blueprint's unreachable-rig arm, run rather than schema-checked.

`test_blueprints.py` proves Home Assistant accepts this blueprint; these fire
the `rig_unreachable` trigger and read which notification comes out.
"""

from datetime import timedelta

from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.nina_astrophotography.const import DOMAIN

CONNECTED = "binary_sensor.rig_safety_monitor_connected"

INPUTS = {
    "nina_rig": "device-id",
    "safety_unsafe": "binary_sensor.rig_safety_monitor_unsafe",
    "safety_connected": CONNECTED,
    "mount_parked": "binary_sensor.rig_mount_at_park",
    "notify_target": ["notify.phone"],
}


@pytest.fixture
async def watching(hass: HomeAssistant, installed):
    """The blueprint over a connected monitor whose entry is in `entry_state`.

    Returns the notify calls.
    """

    async def _set_up(entry_state: ConfigEntryState):
        entry = MockConfigEntry(domain=DOMAIN, state=entry_state)
        entry.add_to_hass(hass)
        er.async_get(hass).async_get_or_create(
            "binary_sensor",
            DOMAIN,
            "safety_connected",
            suggested_object_id="rig_safety_monitor_connected",
            config_entry=entry,
        )
        hass.states.async_set(CONNECTED, "on")
        sent = async_mock_service(hass, "notify", "send_message")
        assert await async_setup_component(
            hass,
            AUTOMATION_DOMAIN,
            {
                AUTOMATION_DOMAIN: {
                    "use_blueprint": {
                        "path": "nina_astrophotography/weather_abort.yaml",
                        "input": INPUTS,
                    }
                }
            },
        )
        await hass.async_block_till_done()
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

    hass.states.async_set(CONNECTED, "unavailable", attributes)
    await hass.async_block_till_done()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2, seconds=1))
    await hass.async_block_till_done()

    expected = ["⚠️ N.I.N.A. unreachable"] if notified else []
    assert [call.data["title"] for call in sent] == expected

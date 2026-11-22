"""A weather source whose readings stop changing while it reports connected.

`scheduler_waiting_lost_lock` is such a capture: the station served a midday
reading, 80123 lx and 37.6 °C, through two nights.
"""

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import WEATHER_FREEZE
from helpers import state_of

FROZEN = "binary_sensor.n_i_n_a_weather_readings_frozen"


@pytest.fixture
async def frozen(
    hass: HomeAssistant, freezer, config_entry: MockConfigEntry, rig, set_up_at
) -> MockConfigEntry:
    """The station polled again a freeze window after setup, unchanged."""
    await set_up_at(hass, config_entry, rig, "scheduler_waiting_lost_lock")
    freezer.tick(WEATHER_FREEZE)
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    return config_entry


async def test_readings_unchanged_for_the_window_read_frozen(
    hass: HomeAssistant, frozen: MockConfigEntry
) -> None:
    assert state_of(hass, FROZEN).state == "on"


async def test_frozen_since_is_when_the_held_readings_were_first_read(
    hass: HomeAssistant, frozen: MockConfigEntry
) -> None:
    state = state_of(hass, FROZEN)
    assert state.attributes["frozen_since"] == state.last_changed - WEATHER_FREEZE


async def test_readings_unchanged_for_less_than_the_window_do_not(
    hass: HomeAssistant, freezer, config_entry: MockConfigEntry, rig, set_up_at
) -> None:
    await set_up_at(hass, config_entry, rig, "scheduler_waiting_lost_lock")
    freezer.tick(WEATHER_FREEZE / 2)
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, FROZEN).state == "off"


async def test_a_frozen_station_clears_when_its_readings_move(
    hass: HomeAssistant, frozen: MockConfigEntry, rig
) -> None:
    rig.goto("scheduler_waiting")
    await frozen.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, FROZEN).state == "off"

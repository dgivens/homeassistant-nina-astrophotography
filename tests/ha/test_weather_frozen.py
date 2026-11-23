"""A weather source whose readings stop changing while it reports connected.

`scheduler_waiting_lost_lock` is such a capture: the station served a midday
reading, 80123 lx and 37.6 °C, through two nights. The test instance stands in
San Diego, and no capture names a site, so the sun is placed there.
"""

from datetime import timedelta

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import (
    WEATHER_FREEZE_LIT_NIGHT,
    WEATHER_FREEZE_STATION,
)
from helpers import state_of

FROZEN = "binary_sensor.n_i_n_a_weather_readings_frozen"


@pytest.fixture
def at_noon(freezer):
    """Midday in San Diego, where an 80123 lx sky is daylight."""
    freezer.move_to("2026-09-18T19:00:00+00:00")


@pytest.fixture
def poll_after(hass: HomeAssistant, freezer, config_entry: MockConfigEntry):
    """Poll the rig again, `delay` on, as it stands."""

    async def _poll(delay: timedelta) -> None:
        freezer.tick(delay)
        await config_entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    return _poll


@pytest.fixture
async def frozen(
    hass: HomeAssistant,
    at_noon,
    config_entry: MockConfigEntry,
    rig,
    set_up_at,
    poll_after,
) -> MockConfigEntry:
    """The station polled again a freeze window after setup, unchanged."""
    await set_up_at(hass, config_entry, rig, "scheduler_waiting_lost_lock")
    await poll_after(WEATHER_FREEZE_STATION)
    return config_entry


async def test_readings_unchanged_for_the_window_read_frozen(
    hass: HomeAssistant, frozen: MockConfigEntry
) -> None:
    assert state_of(hass, FROZEN).state == "on"


async def test_frozen_since_is_when_the_held_readings_were_first_read(
    hass: HomeAssistant, frozen: MockConfigEntry
) -> None:
    state = state_of(hass, FROZEN)
    assert (
        state.attributes["frozen_since"] == state.last_changed - WEATHER_FREEZE_STATION
    )


async def test_readings_unchanged_for_less_than_the_window_do_not(
    hass: HomeAssistant,
    at_noon,
    config_entry: MockConfigEntry,
    rig,
    set_up_at,
    poll_after,
) -> None:
    await set_up_at(hass, config_entry, rig, "scheduler_waiting_lost_lock")
    await poll_after(WEATHER_FREEZE_STATION / 2)
    assert state_of(hass, FROZEN).state == "off"


async def test_a_frozen_station_clears_when_its_readings_move(
    hass: HomeAssistant, frozen: MockConfigEntry, rig
) -> None:
    rig.goto("scheduler_waiting")
    await frozen.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, FROZEN).state == "off"


async def test_a_daylight_reading_held_after_dusk_reads_frozen_within_minutes(
    hass: HomeAssistant,
    on_the_frozen_station_night,
    config_entry: MockConfigEntry,
    rig,
    set_up_at,
    poll_after,
) -> None:
    await set_up_at(hass, config_entry, rig, "scheduler_waiting_lost_lock")
    await poll_after(WEATHER_FREEZE_LIT_NIGHT)
    assert state_of(hass, FROZEN).state == "on"


async def test_a_web_source_is_given_longer_than_a_station(
    hass: HomeAssistant,
    at_noon,
    config_entry: MockConfigEntry,
    rig,
    set_up_at,
    poll_after,
) -> None:
    """Open-Meteo refreshes every ten minutes from a gridded model."""
    await set_up_at(hass, config_entry, rig, "weather_openmeteo")
    await poll_after(WEATHER_FREEZE_STATION)
    assert state_of(hass, FROZEN).state == "off"


@pytest.mark.synthetic
async def test_the_sun_is_placed_at_the_rigs_own_site(
    hass: HomeAssistant,
    on_the_frozen_station_night,
    config_entry: MockConfigEntry,
    rig,
    set_up_at,
    poll_after,
) -> None:
    """Night over Home Assistant, afternoon at the rig: a remote rig's daylight
    is no frozen night sky.
    """
    await set_up_at(hass, config_entry, rig, "frozen_station_sited_in_daylight")
    await poll_after(WEATHER_FREEZE_LIT_NIGHT)
    assert state_of(hass, FROZEN).state == "off"

"""The frozen-weather blueprint, run against the integration's own sensor."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)

from custom_components.nina_astrophotography.const import DEFAULT_WEATHER_FREEZE_STATION

FROZEN = "binary_sensor.n_i_n_a_weather_readings_frozen"


async def test_a_freeze_notifies_with_when_the_readings_were_first_read(
    hass: HomeAssistant,
    freezer,
    config_entry: MockConfigEntry,
    rig,
    set_up_at,
    installed,
) -> None:
    # Noon in the test instance's zone, US/Pacific, which the message uses.
    freezer.move_to("2026-09-18T19:00:00+00:00")
    await set_up_at(hass, config_entry, rig, "scheduler_waiting_lost_lock")
    sent = async_mock_service(hass, "notify", "send_message")
    await installed(
        "weather_frozen_alert.yaml",
        {"weather_frozen": FROZEN, "notify_target": ["notify.phone"]},
    )

    freezer.tick(timedelta(minutes=DEFAULT_WEATHER_FREEZE_STATION))
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    assert len(sent) == 1
    assert "since 12:00" in sent[0].data["message"]

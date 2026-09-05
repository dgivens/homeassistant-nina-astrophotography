"""Availability level 2 and `log-when-unavailable`.

Level 1 — `CoordinatorEntity.available` propagating `last_update_success` — is
Home Assistant's own and is not tested here (§8.2); it is pinned once, through
this integration's entity, by
`test_coordinator.test_an_unreachable_rig_makes_the_entities_unavailable`.

Level 3 — a sentinel reading as `unknown` rather than `unavailable` — is a
value concern of the sensor platforms and is pinned in phase C.
"""
import logging

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

LIGHT = "light.n_i_n_a_flat_panel_light"


async def test_a_disconnected_device_makes_its_entities_unavailable(
    hass: HomeAssistant, set_up_with_flat_device
) -> None:
    """Level 2 alone, isolated from the panel's own range condition.

    The mapper blanks every reading of a block reporting `Connected: false`, so
    a disconnected panel maps to a zero range and the platform's own condition
    accounts for it. The captured range is restored here deliberately: with
    `_span > 0` and `SupportsOnOff` true, nothing but `connected` can produce
    `unavailable`.
    """
    await set_up_with_flat_device(connected=False)
    assert hass.states.get(LIGHT).state == "unavailable"


async def test_an_outage_is_logged_once_and_the_recovery_once(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance, caplog
) -> None:
    caplog.set_level(logging.INFO)
    await advance("nina_unreachable")
    await advance("nina_unreachable")
    assert caplog.text.count("is unavailable") == 1

    await advance("imaging")
    assert caplog.text.count("is back online") == 1


async def test_a_device_disconnection_is_logged_once_and_the_reconnection_once(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance, caplog
) -> None:
    """Per device, under the label the device registry shows."""
    caplog.set_level(logging.INFO)
    await advance("equipment_disconnected")
    await advance("equipment_disconnected")
    assert caplog.text.count("Flat Panel disconnected") == 1

    await advance("imaging")
    assert caplog.text.count("Flat Panel reconnected") == 1


async def test_first_sight_of_a_device_is_not_a_reconnection(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, caplog
) -> None:
    """Equipment routinely connects long after Home Assistant starts. Only a
    slot that has been seen connected and gone down has anything to recover
    from, so a first connection is not a transition."""
    caplog.set_level(logging.INFO)
    rig.goto("partial_equipment_connection")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    rig.goto("imaging")
    await config_entry.runtime_data.coordinator.async_refresh()
    assert "reconnected" not in caplog.text

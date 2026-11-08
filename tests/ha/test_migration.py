"""Entries from earlier minor versions, brought up to date at setup."""

from datetime import timedelta

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import (
    CONF_INSTANCE_NAME,
    CONF_POLL_INTERVAL,
)
from ha.registry import get_device


@pytest.mark.parametrize(
    ("options", "chosen", "polled"),
    [({}, 30, 30), ({CONF_POLL_INTERVAL: 20}, 30, 20), ({}, 120, 120)],
    ids=["chosen-at-setup", "saved-in-configure", "above-the-form-range"],
)
async def test_an_upgraded_entry_polls_at_the_interval_in_effect(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    rig,
    options: dict,
    chosen: int,
    polled: int,
) -> None:
    """1.4.x allowed up to 300 s; an interval above the options form's 60 is
    carried over rather than clamped.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, CONF_POLL_INTERVAL: chosen},
        options=options,
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    # No entity exposes the poll cadence, so the coordinator is the only
    # surface that shows it.
    coordinator = config_entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(seconds=polled)


async def test_a_pre_2_0_entry_names_the_instance_from_its_title(
    hass: HomeAssistant, two_rigs
) -> None:
    """The second rig, whose title is not the default: an entry titled "N.I.N.A."
    cannot tell the title from the default apart.
    """
    assert get_device(hass, two_rigs.entries[1]).name == "Dome"


async def test_an_entry_that_already_has_an_instance_name_keeps_it(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_INSTANCE_NAME: "Rooftop"}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert get_device(hass, config_entry).name == "Rooftop"

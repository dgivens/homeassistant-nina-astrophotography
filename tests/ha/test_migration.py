"""Entries from earlier minor versions, brought up to date at setup."""

# pyright: reportTypedDictNotRequiredAccess=false

from datetime import timedelta

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import (
    CONF_HOST,
    CONF_INSTANCE_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    DOMAIN,
)
from ha.registry import get_device

ROTATOR_ROWS = {
    "binary_sensor.n_i_n_a_rotator_synced": "rotator_synced",
    "number.n_i_n_a_rotator_mechanical_position": "rotator_mechanical_position",
}


@pytest.mark.parametrize(
    ("data", "options"),
    [({CONF_POLL_INTERVAL: 30}, {}), ({}, {CONF_POLL_INTERVAL: 30})],
    ids=["in-data", "in-options"],
)
async def test_an_upgraded_entry_drops_its_poll_interval_and_polls_every_10_s(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    rig,
    data: dict,
    options: dict,
) -> None:
    """1.4.x and 2.x up to 2.5 stored an interval in `data`, and Configure in
    `options`.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, **data},
        options=options,
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert CONF_POLL_INTERVAL not in config_entry.data
    assert CONF_POLL_INTERVAL not in config_entry.options
    # No entity exposes the poll cadence, so the coordinator is the only
    # surface that shows it.
    coordinator = config_entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(seconds=10)


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


async def test_an_upgraded_entry_drops_its_address_as_unique_id(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    assert loaded_entry.unique_id is None


async def test_an_upgraded_entry_typed_in_capitals_still_blocks_a_duplicate(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig
) -> None:
    """Entries from before 2.0 stored the host as typed, and the duplicate
    guard compares it with the lower-cased host the flow stores.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_HOST: "NINA.local"}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


def _register_rotator_rows_disabled(
    entity_registry: er.EntityRegistry, entry: MockConfigEntry, user_disabled: str
) -> None:
    """As an earlier version left them, with one row the user disabled besides."""
    for entity_id, suffix in ROTATOR_ROWS.items():
        domain, object_id = entity_id.split(".")
        entity_registry.async_get_or_create(
            domain,
            DOMAIN,
            f"{entry.entry_id}_{suffix}",
            suggested_object_id=object_id,
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.USER
            if entity_id == user_disabled
            else er.RegistryEntryDisabler.INTEGRATION,
        )


def _enabled(entity_registry: er.EntityRegistry) -> set[str]:
    return {
        row.entity_id
        for row in entity_registry.entities.values()
        if row.entity_id in ROTATOR_ROWS and row.disabled_by is None
    }


async def test_an_upgrade_enables_the_rotator_rows_the_card_reads(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, entity_registry
) -> None:
    """A row the user disabled stays so."""
    config_entry.add_to_hass(hass)
    synced, mechanical = ROTATOR_ROWS
    _register_rotator_rows_disabled(entity_registry, config_entry, user_disabled=synced)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert _enabled(entity_registry) == {mechanical}


async def test_an_upgrade_honours_an_entry_that_disables_new_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, entity_registry
) -> None:
    """Home Assistant records that system option as `disabled_by` integration."""
    config_entry.add_to_hass(hass)
    _register_rotator_rows_disabled(entity_registry, config_entry, user_disabled="")
    hass.config_entries.async_update_entry(config_entry, pref_disable_new_entities=True)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert _enabled(entity_registry) == set()

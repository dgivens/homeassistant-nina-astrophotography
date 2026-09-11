"""Selects: options from the wire, and the index that goes back to it.

The tracking index is the one thing here that cannot be inferred from the
options list, and getting it wrong parks a mount on the wrong rate.
"""
from dataclasses import replace

import pytest
from homeassistant.components.select import (
    ATTR_OPTION,
    ATTR_OPTIONS,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import NinaCommandError
from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
from custom_components.nina_astrophotography.api.v2.mapper import map_equipment_info
from custom_components.nina_astrophotography.const import DOMAIN
from custom_components.nina_astrophotography.select import DESCRIPTIONS

FILTER = "select.n_i_n_a_filter_wheel_filter"
TRACKING = "select.n_i_n_a_mount_tracking_rate"


async def _select(hass: HomeAssistant, entity_id: str, option: str) -> None:
    await hass.services.async_call(
        SELECT_DOMAIN, SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: entity_id, ATTR_OPTION: option}, blocking=True,
    )


@pytest.fixture
def set_up_with_mount(hass, config_entry, nina_responses, monkeypatch):
    """Set the entry up against the dawn snapshot with its mount varied.

    Varies the mapped MODEL, not the captured wire JSON: the fixture rule bans
    hand-written wire documents, and a mount reporting a tracking mode this API
    cannot encode is one field away from the mount the rig actually reported.
    """
    async def _set_up(**changes) -> MockConfigEntry:
        snapshot = map_equipment_info(nina_responses("dawn_equipment_info.json"))
        snapshot = replace(snapshot, mount=replace(snapshot.mount, **changes))

        async def get_equipment(self):
            return snapshot

        monkeypatch.setattr(NinaClientV2, "get_equipment", get_equipment)
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        return config_entry

    return _set_up


async def test_the_tracking_options_come_from_the_mount(
    hass: HomeAssistant, loaded_entry
) -> None:
    """`TrackingModes` differs by mount — this one does not offer King — and a
    hardcoded list offers rates the mount does not have."""
    assert hass.states.get(TRACKING).attributes[ATTR_OPTIONS] == [
        "Sidereal", "Lunar", "Solar", "Stopped"
    ]


async def test_the_tracking_select_uses_the_wire_spelling(
    hass: HomeAssistant, advance
) -> None:
    """The spec's enum says 'Siderial'; the wire says 'Sidereal'."""
    await advance("imaging_guiding")
    assert hass.states.get(TRACKING).state == "Sidereal"


async def test_the_tracking_index_is_the_apis_enum_not_the_position_in_the_list(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """THE test on this entity. `mode` is the API's own enum — 3 is King — and
    this mount does not offer King, so 'Stopped' sits at position 3 in its
    options and is mode 4 on the wire. Indexing the list starts King tracking
    on a mount the user asked to stop.
    """
    await _select(hass, TRACKING, "Stopped")
    assert rig.sent == [("/equipment/mount/tracking", {"mode": 4})]


async def test_a_tracking_mode_the_api_cannot_encode_is_refused(
    hass: HomeAssistant, set_up_with_mount, rig
) -> None:
    """The options are the mount's, so a mount can offer a name this API has no
    index for; sending a guess would set some other rate."""
    await set_up_with_mount(tracking_modes=("Sidereal", "Ludicrous"))
    with pytest.raises(ServiceValidationError):
        await _select(hass, TRACKING, "Ludicrous")
    assert rig.sent == []


async def test_a_filter_not_in_this_wheel_is_refused(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    with pytest.raises(ServiceValidationError):
        await _select(hass, FILTER, "Ha")
    assert rig.sent == []


async def test_selecting_a_filter_sends_its_slot_and_does_not_read_it_back(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """No command on this API confirms anything (§3.5): the wheel still reads
    the polled R until it has actually moved."""
    await _select(hass, FILTER, "H")
    assert rig.sent == [("/equipment/filterwheel/change-filter", {"filterId": 4})]
    assert hass.states.get(FILTER).state == "R"


async def test_a_refused_command_surfaces_as_a_home_assistant_error(
    hass: HomeAssistant, loaded_entry, monkeypatch
) -> None:
    async def refuse(self, _index) -> None:
        raise NinaCommandError("Filter wheel not connected")

    monkeypatch.setattr(NinaClientV2, "change_filter", refuse)
    with pytest.raises(HomeAssistantError):
        await _select(hass, FILTER, "H")


@pytest.mark.parametrize(
    "suffix",
    # The 1.4.5 spellings: a survivor keeps its unique_id, so an upgraded
    # install keeps the registry row and the automations on it.
    ["filterwheel_select", "tracking_rate_select"],
)
async def test_the_kept_selects_keep_their_1_4_5_unique_id(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    assert entity_registry.async_get_entity_id(
        SELECT_DOMAIN, DOMAIN, f"{loaded_entry.entry_id}_{suffix}"
    ) is not None


def test_every_dome_descriptor_is_marked_unverified() -> None:
    """Dome ships untested; the marker is enforced, not documented (§5.3.1).
    No dome descriptor exists on this platform yet — the guard is for the one
    that is added next."""
    assert [d.key for d in DESCRIPTIONS if d.kind == "dome" and d.verified] == []

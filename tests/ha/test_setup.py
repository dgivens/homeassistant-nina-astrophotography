"""Setup and unload, through public interfaces only."""
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import (
    NinaConnectionError,
    NinaEndpointError,
)
from custom_components.nina_astrophotography.const import DOMAIN

CLIENT = "custom_components.nina_astrophotography.api.v2.client.NinaClientV2"


async def test_setup_stores_state_on_runtime_data_not_hass_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    """Bronze runtime-data: a module-level dict keyed by entry_id leaks."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator is not None
    assert DOMAIN not in hass.data


async def test_an_unreachable_rig_retries_rather_than_failing_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    with patch(f"{CLIENT}.get_versions", side_effect=NinaConnectionError("refused")):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_build_that_does_not_serve_the_api_fails_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A wrong path never becomes right — ConfigEntryError, not NotReady."""
    config_entry.add_to_hass(hass)
    with patch(f"{CLIENT}.get_versions", side_effect=NinaEndpointError("no /version")):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_the_services_still_reach_a_client_after_the_move_to_runtime_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    """Moving off hass.data[DOMAIN] empties what _get_client iterates.

    Without this test the 19 services fail silently from phase A until phase C.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with patch(
        "custom_components.nina_astrophotography.legacy_api.NinaApiClient.park_mount",
        new_callable=AsyncMock,
    ) as park:
        await hass.services.async_call(DOMAIN, "mount_park", {}, blocking=True)
    assert park.called


async def test_unload_leaves_no_state_behind(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    # The claim is that nothing survives the unload — not that HA's own unload
    # machinery works, which is Home Assistant's test to write.
    assert DOMAIN not in hass.data

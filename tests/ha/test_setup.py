"""Setup and unload, through public interfaces only."""
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_RESTORED, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaUnavailableError,
)
from custom_components.nina_astrophotography.const import CONF_POLL_INTERVAL, DOMAIN

CLIENT = "custom_components.nina_astrophotography.api.v2.client.NinaClientV2"
LIGHT = "light.n_i_n_a_flat_panel_light"


async def test_setup_stores_state_on_runtime_data_not_hass_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    """Bronze runtime-data: a module-level dict keyed by entry_id leaks."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator is not None
    assert DOMAIN not in hass.data


@pytest.mark.parametrize(
    "error",
    [NinaConnectionError("refused"), NinaUnavailableError("500"),
     NinaCommandError("Camera not connected")],
    ids=["unreachable", "unavailable", "refusing"],
)
async def test_a_rig_that_is_not_ready_retries_rather_than_failing_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, error
) -> None:
    """All three are transient at startup: N.I.N.A. may still be booting, or
    answering unhappily while its equipment connects."""
    config_entry.add_to_hass(hass)
    with patch(f"{CLIENT}.get_versions", side_effect=error):
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
    assert "API" in config_entry.reason


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
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """After unload the registry leaves only its restored placeholder for the
    light — unavailable, `restored: true` — not an entity of ours."""
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED
    state = hass.states.get(LIGHT)
    assert (state.state, state.attributes.get(ATTR_RESTORED)) == (STATE_UNAVAILABLE, True)


async def test_the_configured_poll_interval_drives_the_coordinator(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={CONF_POLL_INTERVAL: 15})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator.update_interval == timedelta(seconds=15)


async def test_an_options_update_reloads_the_entry(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The interval is read once at setup, so a new value needs a reload."""
    hass.config_entries.async_update_entry(loaded_entry, options={CONF_POLL_INTERVAL: 30})
    await hass.async_block_till_done()
    assert loaded_entry.runtime_data.coordinator.update_interval == timedelta(seconds=30)


async def test_home_assistant_started_before_nina_loads_once_the_rig_answers(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, freezer
) -> None:
    """The ordinary case on a hosted rig: Home Assistant is up continuously and
    the imaging PC boots at dusk. The retry must then find the whole session
    rather than an empty one.

    Through the rig states, not a patched client: the retry path has to survive
    a refused connection followed by a real one on the same transport.
    """
    freezer.move_to("2026-09-04T12:30:00+00:00")
    rig.goto("nina_unreachable")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY

    rig.goto("imaging")
    assert await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.coordinator.data.session.image_count == 122

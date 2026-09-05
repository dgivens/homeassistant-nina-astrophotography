"""The config and options flows, at 100% branch coverage (Bronze)."""
from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from custom_components.nina_astrophotography.api.models import VersionInfo
from custom_components.nina_astrophotography.const import (
    CONF_HOST,
    CONF_INSTANCE_NAME,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_ROLLOVER_HOUR,
    DOMAIN,
)

PROBE = "custom_components.nina_astrophotography.api.v2.client.NinaClientV2.get_versions"
SETUP = "custom_components.nina_astrophotography.async_setup_entry"

VERSIONS = VersionInfo(api_version="2.2.15.2", nina_version="3.2.0.9001")
ROOFTOP = {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"}


async def _submit(hass: HomeAssistant, user_input: dict, **probe) -> dict:
    """Open the user step and answer it once, with `get_versions` stubbed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with patch(PROBE, **probe), patch(SETUP, return_value=True):
        return await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )


async def test_a_valid_rig_creates_an_entry_titled_by_its_instance_name(
    hass: HomeAssistant,
) -> None:
    result = await _submit(hass, ROOFTOP, return_value=VERSIONS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Rooftop"
    assert result["data"][CONF_HOST] == "nina.local"


@pytest.mark.parametrize(
    ("raised", "shown"),
    [
        (NinaConnectionError("refused"), "cannot_connect"),
        (NinaUnavailableError("still starting"), "cannot_connect"),
        (NinaCommandError("refused"), "cannot_connect"),
        (NinaEndpointError("no /version"), "unsupported_api"),
        (NinaRequestError("malformed"), "unsupported_api"),
        (RuntimeError("boom"), "unknown"),
    ],
    ids=["unreachable", "unavailable", "refusing", "no-endpoint", "malformed", "other"],
)
async def test_a_failing_probe_shows_why(
    hass: HomeAssistant, raised: Exception, shown: str
) -> None:
    """Bronze test-before-configure: the probe decides, and says which way."""
    result = await _submit(hass, ROOFTOP, side_effect=raised)
    assert result["errors"] == {"base": shown}


async def test_the_form_recovers_after_an_error(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    with patch(PROBE, side_effect=NinaConnectionError("refused")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], ROOFTOP
        )
    with patch(PROBE, return_value=VERSIONS), patch(SETUP, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], ROOFTOP
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.fixture
def existing(hass: HomeAssistant) -> MockConfigEntry:
    """An instance already configured on nina.local:1888, not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="N.I.N.A.",
        data={CONF_HOST: "nina.local", CONF_PORT: 1888},
        unique_id="nina.local:1888",
    )
    entry.add_to_hass(hass)
    return entry


async def test_the_same_host_and_port_cannot_be_added_twice(
    hass: HomeAssistant, existing: MockConfigEntry
) -> None:
    result = await _submit(hass, ROOFTOP, return_value=VERSIONS)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_second_rig_on_a_different_host_is_allowed(
    hass: HomeAssistant, existing: MockConfigEntry
) -> None:
    """Two rigs must coexist — that is why the instance name exists."""
    result = await _submit(
        hass,
        {CONF_HOST: "other.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Dome"},
        return_value=VERSIONS,
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def _set_option(hass: HomeAssistant, entry: MockConfigEntry, **options) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    await hass.async_block_till_done()
    return result


async def test_the_options_flow_changes_the_poll_interval(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    result = await _set_option(hass, loaded_entry, **{CONF_POLL_INTERVAL: 30})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    coordinator = loaded_entry.runtime_data.coordinator
    assert coordinator.update_interval == timedelta(seconds=30)


async def test_the_options_flow_moves_the_session_rollover_hour(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """A rig on a UTC clock needs the boundary off local noon (§4.4)."""
    await _set_option(hass, loaded_entry, **{CONF_ROLLOVER_HOUR: 3})
    session = loaded_entry.runtime_data.coordinator.data.session
    assert session.session_start.hour == 3


async def test_a_pre_2_0_entry_names_the_instance_from_its_title(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """1.4.x entries carry no `instance_name`; the title is what they have."""
    assert CONF_INSTANCE_NAME not in loaded_entry.data
    hub = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, loaded_entry.entry_id), loaded_entry.entry_id
    )
    assert hub.name == "N.I.N.A."

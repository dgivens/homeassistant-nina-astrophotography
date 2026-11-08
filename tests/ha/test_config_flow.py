"""The config and options flows, at 100% branch coverage (Bronze)."""

# Every key but `type` and `flow_id` is NotRequired on `ConfigFlowResult`, and
# which ones a step returns depends on its type — which each test asserts first.
# pyright: reportTypedDictNotRequiredAccess=false

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntryDisabler,
    ConfigFlowResult,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

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
    CONF_OUTAGE_GRACE,
    CONF_POLL_INTERVAL,
    CONF_PORT,
    CONF_ROLLOVER_HOUR,
    DOMAIN,
)
from helpers import state_of

PROBE = (
    "custom_components.nina_astrophotography.api.v2.client.NinaClientV2.get_versions"
)
SETUP = "custom_components.nina_astrophotography.async_setup_entry"

VERSIONS = VersionInfo(api_version="2.2.15.2", nina_version="3.2.0.9001")
ROOFTOP = {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"}
ELSEWHERE = {CONF_HOST: "other.local", CONF_PORT: 1888}


@pytest.fixture
def probe() -> Generator[AsyncMock]:
    """`get_versions`, answering as a working rig until a test says otherwise."""
    with patch(PROBE, return_value=VERSIONS) as mock:
        yield mock


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    with patch(SETUP, return_value=True) as mock:
        yield mock


@pytest.fixture
def configured(hass: HomeAssistant, config_entry: MockConfigEntry) -> MockConfigEntry:
    """A rig already added, as a 1.4.x entry: titled, with no instance name."""
    config_entry.add_to_hass(hass)
    return config_entry


async def _user_step(hass: HomeAssistant) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )


async def _answer(
    hass: HomeAssistant, result: ConfigFlowResult, user_input: dict
) -> ConfigFlowResult:
    return await hass.config_entries.flow.async_configure(result["flow_id"], user_input)


async def test_a_valid_rig_creates_an_entry_titled_by_its_instance_name(
    hass: HomeAssistant, probe: AsyncMock, mock_setup_entry: AsyncMock
) -> None:
    result = await _user_step(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    result = await _answer(hass, result, ROOFTOP)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Rooftop"
    assert result["data"] == ROOFTOP
    assert result["result"].unique_id is None
    mock_setup_entry.assert_called_once()


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
async def test_a_failing_probe_shows_why_and_a_retry_succeeds(
    hass: HomeAssistant,
    probe: AsyncMock,
    mock_setup_entry: AsyncMock,
    raised: Exception,
    shown: str,
) -> None:
    """Bronze test-before-configure: the probe decides, and says which way."""
    probe.side_effect = raised
    result = await _answer(hass, await _user_step(hass), ROOFTOP)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": shown}

    probe.side_effect = None
    result = await _answer(hass, result, ROOFTOP)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_setup_entry.assert_called_once()


@pytest.mark.parametrize(
    "host", ["nina.local", "NINA.local", "  nina.local  ", "nina.local."]
)
async def test_the_same_host_and_port_cannot_be_added_twice(
    hass: HomeAssistant, configured: MockConfigEntry, probe: AsyncMock, host: str
) -> None:
    """Hostnames are case-insensitive and a trailing dot names the same host,
    so each names the configured rig. The probe never runs: a duplicate costs
    no HTTP call.
    """
    result = await _answer(hass, await _user_step(hass), ROOFTOP | {CONF_HOST: host})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    probe.assert_not_called()


async def test_a_disabled_rig_from_before_2_0_cannot_be_added_again(
    hass: HomeAssistant, probe: AsyncMock
) -> None:
    """A disabled entry is never set up, so never migrated: its host keeps the
    capitals it was typed with.
    """
    MockConfigEntry(
        domain=DOMAIN,
        title="N.I.N.A.",
        data={CONF_HOST: "NINA.local", CONF_PORT: 1888},
        disabled_by=ConfigEntryDisabler.USER,
    ).add_to_hass(hass)
    result = await _answer(hass, await _user_step(hass), ROOFTOP)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_second_rig_may_not_reuse_an_instance_name(
    hass: HomeAssistant,
    configured: MockConfigEntry,
    probe: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Two rigs called the same thing name their devices identically, and the
    second set collides into `_2` entity ids.
    """
    result = await _answer(
        hass, await _user_step(hass), ELSEWHERE | {CONF_INSTANCE_NAME: "N.I.N.A."}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {CONF_INSTANCE_NAME: "name_in_use"}

    result = await _answer(hass, result, ELSEWHERE | {CONF_INSTANCE_NAME: "Dome"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_second_rig_on_the_same_host_and_another_port_is_allowed(
    hass: HomeAssistant,
    configured: MockConfigEntry,
    probe: AsyncMock,
    mock_setup_entry: AsyncMock,
) -> None:
    """Both parts of the address decide: two N.I.N.A. instances may share a PC."""
    result = await _answer(
        hass,
        await _user_step(hass),
        {CONF_HOST: "nina.local", CONF_PORT: 1889, CONF_INSTANCE_NAME: "Dome"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("name", ["", "   "], ids=["empty", "blank"])
async def test_a_blank_instance_name_is_refused(
    hass: HomeAssistant, probe: AsyncMock, name: str
) -> None:
    """It would title the entry "" and name every device " Camera" — and a
    length check alone accepts a string of spaces.
    """
    result = await _user_step(hass)
    with pytest.raises(vol.Invalid):
        await _answer(hass, result, ROOFTOP | {CONF_INSTANCE_NAME: name})
    assert not hass.config_entries.async_entries(DOMAIN)


async def _set_option(
    hass: HomeAssistant, entry: MockConfigEntry, **options
) -> ConfigFlowResult:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], options
    )
    await hass.async_block_till_done()
    return result


async def test_the_options_form_offers_no_poll_interval(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """The interval is fixed (`appropriate-polling`); a user wanting another
    disables polling and calls `homeassistant.update_entity`.
    """
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"]
    assert schema is not None
    assert CONF_POLL_INTERVAL not in schema.schema


async def test_the_options_flow_moves_the_session_rollover_hour(
    hass: HomeAssistant, loaded_entry: MockConfigEntry
) -> None:
    """A rig on a UTC clock needs the boundary off local noon (§4.4)."""
    await _set_option(hass, loaded_entry, **{CONF_ROLLOVER_HOUR: 3})
    # Read from the model: `sensor.session_start` (§5.4) ships disabled, and
    # states the boundary in UTC, where the rig's 03:00 is not hour 3.
    session = loaded_entry.runtime_data.coordinator.data.session
    assert session.session_start.hour == 3


async def test_an_outage_grace_of_zero_fails_on_the_first_missed_poll(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    await _set_option(hass, loaded_entry, **{CONF_OUTAGE_GRACE: 0})
    await advance("nina_unreachable")
    assert state_of(hass, "light.n_i_n_a_flat_panel_light").state == "unavailable"

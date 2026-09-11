"""The N.I.N.A. switch device's channels, split across three platforms.

`SwitchChannelModel.binary` — `Maximum - Minimum == StepSize` — and `writable`
are the whole rule: a one-step writable channel is a `switch`, a wider writable
one a `number`, and a read-only one a `sensor`. Nothing else about a channel is
inspected, because nothing else is reported.

On this rig the switch device is a Home Assistant bridge exposing two mains
outlets, so the entities duplicate ones that exist natively — accepted, the
same device through two integrations is ordinary. The normal case is a real
ASCOM switch, a Pegasus Powerbox and its outlets, dew heaters and gauges, which
the enabled-by-default rule (§5.3.5) is written for.
"""
import pytest
from homeassistant.core import HomeAssistant

OUTLET = "switch.n_i_n_a_switch_flat_panel"
DEW_HEATER = "number.n_i_n_a_switch_dew_heater_a"
GAUGE = "sensor.n_i_n_a_switch_input_voltage"


@pytest.mark.synthetic
async def test_a_writable_range_wider_than_one_step_becomes_a_number(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """No rig in the corpus reports a dimmable channel; the state derives one."""
    await advance("switch_hub_with_a_dimmable_channel")
    assert hass.states.get(DEW_HEATER) is not None
    assert hass.states.get("switch.n_i_n_a_switch_dew_heater_a") is None


@pytest.mark.synthetic
async def test_a_read_only_channel_becomes_a_sensor(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """`ReadonlySwitches` is empty in every capture, so the gauge is derived."""
    await advance("switch_hub_with_a_readonly_channel")
    assert float(hass.states.get(GAUGE).state) == 12.1
    assert hass.states.get("number.n_i_n_a_switch_input_voltage") is None


@pytest.mark.synthetic
async def test_a_number_channel_offers_the_channels_own_range(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """Out-of-range input is silently clamped and answers `Success: true`, so
    the declared range is the only thing that refuses a typo."""
    await advance("switch_hub_with_a_dimmable_channel")
    attributes = hass.states.get(DEW_HEATER).attributes
    assert (attributes["min"], attributes["max"], attributes["step"]) == (0, 100, 1)


async def test_a_channel_reports_value_not_target_value(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """`TargetValue` is where the channel is going; `Value` is where it is."""
    await advance("switch_channel_commanded_not_yet_switched")
    assert hass.states.get(OUTLET).state == "off"


async def test_channels_ship_enabled(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """A Pegasus Powerbox's outlets are the reason to install this at all
    (§5.3.5); shipping them disabled would hide the useful case to spare this
    rig two duplicates."""
    assert entity_registry.async_get(OUTLET).disabled_by is None

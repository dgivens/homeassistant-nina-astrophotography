"""The N.I.N.A. switch device's channels, split across three platforms.

`SwitchChannelModel.binary` — `Maximum - Minimum == StepSize` — and `writable`
are the whole rule: a one-step writable channel is a `switch`, a wider writable
one a `number`, and a read-only one a `sensor`. Nothing else about a channel is
inspected, because nothing else is reported.

`Value` versus `TargetValue` is pinned in `test_switch.py`, which owns the
binary channel; this file owns the split itself.

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


async def test_channels_ship_enabled(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """A Pegasus Powerbox's outlets are the reason to install this at all
    (§5.3.5); shipping them disabled would hide the useful case to spare this
    rig two duplicates."""
    assert entity_registry.async_get(OUTLET).disabled_by is None


@pytest.mark.synthetic
async def test_a_writable_channel_with_no_range_is_reported_not_dropped(
    hass: HomeAssistant, loaded_entry, advance, caplog
) -> None:
    """The three shape filters have a hole. Falling through it silently leaves
    the operator a switch device with fewer channels than the driver reports
    and nothing to diagnose it with."""
    await advance("switch_hub_with_a_rangeless_channel")
    assert hass.states.get("switch.n_i_n_a_switch_aux_port") is None
    assert hass.states.get("number.n_i_n_a_switch_aux_port") is None
    assert "reports no usable range" in caplog.text


@pytest.mark.synthetic
async def test_a_zero_step_range_is_not_a_binary_channel(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """`Min 0 / Max 0 / Step 0` satisfies `Max - Min == Step` and is what a
    DISCONNECTED device reports. Without the guard it mints a switch whose on
    and off values are both 0 — permanently, since the ends are read once."""
    await advance("switch_hub_with_a_degenerate_channel")
    assert hass.states.get("switch.n_i_n_a_switch_stuck_outlet") is None


@pytest.mark.synthetic
async def test_a_channel_the_driver_stops_reporting_goes_unavailable(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """The switch DEVICE is still connected, so the entity would otherwise read
    `unknown` and stay clickable — and this API answers `Success: true` to a
    `set` for an index it no longer has."""
    assert hass.states.get(OUTLET).state == "on"
    await advance("switch_channel_no_longer_reported")
    assert hass.states.get(OUTLET).state == "unavailable"

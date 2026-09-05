"""Switches: the state is the actual value, never the command's own response.

No command on this API confirms anything (§3.5), so the command tests assert
what reached the wire — `rig.sent` — rather than reading a state back. The one
test that reads a state back after a command asserts it did **not** move.

`loaded_entry` serves the dawn state, where the guider has never been observed
and the flat panel has; `imaging_guiding` is the mirror image. Which state a
test starts from is therefore load-bearing, not incidental.
"""
import pytest
from homeassistant.components.switch import (
    DOMAIN as SWITCH_DOMAIN,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import NinaCommandError
from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
from custom_components.nina_astrophotography.const import DOMAIN
from custom_components.nina_astrophotography.switch import DESCRIPTIONS

GUIDER = "switch.n_i_n_a_guider"
COOLER = "switch.n_i_n_a_camera_cooler"
DEW_HEATER = "switch.n_i_n_a_camera_dew_heater"
COVER = "switch.n_i_n_a_flat_panel_cover"
REVERSE = "switch.n_i_n_a_rotator_reverse"
LIVESTACK = "switch.n_i_n_a_livestack"
# The switch device's channels are named by the driver, not by a translation
# key: the entity id carries the channel name after the device name.
OUTLET = "switch.n_i_n_a_switch_flat_panel"
DIMMABLE = "switch.n_i_n_a_switch_dew_heater_a"


async def _call(hass: HomeAssistant, service: str, entity_id: str) -> None:
    await hass.services.async_call(
        SWITCH_DOMAIN, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


async def _set_up_at(hass: HomeAssistant, entry: MockConfigEntry, rig, state: str):
    """Set the entry up with the rig already in `state`.

    A route that 404s is latched not-served for the coordinator's lifetime — a
    build without the livestack plugin cannot grow one — so a state that serves
    `/livestack/status` has to be in force before the entry loads.
    """
    rig.goto(state)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    """The entity id claiming this `unique_id` suffix, or None if nothing does."""
    return registry.async_get_entity_id(
        SWITCH_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("imaging_guiding", "on"),
        pytest.param("guider_lost_lock", "on", marks=pytest.mark.synthetic),
        pytest.param("guider_stopped", "off", marks=pytest.mark.synthetic),
    ],
)
async def test_the_guider_switch_is_on_whenever_the_guider_is_running(
    hass: HomeAssistant, advance, state: str, expected: str
) -> None:
    """`State == "Guiding"` reads OFF through LostLock and Calibrating, so a
    dashboard tap on a switch that looks off sends /equipment/guider/start and
    forces a re-settle mid-exposure. "Running" is the honest predicate."""
    await advance(state)
    assert hass.states.get(GUIDER).state == expected


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        (SERVICE_TURN_ON, ("/equipment/guider/start", {"calibrate": "false"})),
        (SERVICE_TURN_OFF, ("/equipment/guider/stop", None)),
    ],
)
async def test_the_guider_switch_never_forces_a_calibration(
    hass: HomeAssistant, advance, rig, service: str, expected: tuple
) -> None:
    """A forced calibration throws away a working one and costs the settle."""
    await advance("imaging_guiding")
    await _call(hass, service, GUIDER)
    assert rig.sent == [expected]


async def test_the_livestack_switch_reads_the_status_endpoint(
    hass: HomeAssistant, config_entry, rig
) -> None:
    """The endpoint answers `"Running"` where the spec's enum says `running`,
    so the comparison is case-insensitive."""
    await _set_up_at(hass, config_entry, rig, "imaging_guiding")
    assert hass.states.get(LIVESTACK).state == "on"


async def test_the_livestack_switch_exists_and_reads_off_without_the_plugin(
    hass: HomeAssistant, loaded_entry
) -> None:
    """`/livestack/status` "cannot fail, even if the livestack plugin is not
    installed" — but a build without the route 404s, and that rig gets a switch
    that reads stopped rather than no switch at all."""
    assert hass.states.get(LIVESTACK).state == "off"


async def test_a_commands_own_response_never_sets_the_state(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """Measured: set-light?on=true answered success while an immediate re-read
    still showed LightOn false; it changed seconds later."""
    await _call(hass, SERVICE_TURN_ON, LIVESTACK)
    assert rig.sent == [("/livestack/start", None)]
    assert hass.states.get(LIVESTACK).state == "off"


@pytest.mark.synthetic
async def test_only_binary_switch_channels_land_on_this_platform(
    hass: HomeAssistant, advance
) -> None:
    """Max - Min == StepSize is binary; a dew heater at 0-100 is a `number`."""
    await advance("switch_hub_with_a_dimmable_channel")
    present = [entity for entity in (OUTLET, DIMMABLE) if hass.states.get(entity)]
    assert present == [OUTLET]


@pytest.mark.synthetic
async def test_a_switch_channel_reads_its_value_not_its_target_value(
    hass: HomeAssistant, advance
) -> None:
    """`TargetValue` is what the channel was last asked for, which is the last
    commanded state — the thing §5.2.3 refuses to show as the state."""
    await advance("switch_channel_commanded_not_yet_switched")
    assert hass.states.get(OUTLET).state == "off"


async def test_a_switch_channel_sends_the_channels_own_index(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """`index` is the channel's `Id`, not its position in the wire's list."""
    await _call(hass, SERVICE_TURN_OFF, OUTLET)
    assert rig.sent == [("/equipment/switch/set", {"index": 0, "value": 0.0})]


@pytest.mark.synthetic
async def test_on_and_off_are_the_channels_own_range_ends(
    hass: HomeAssistant, config_entry, rig
) -> None:
    """A channel numbering its two states 1 and 2 is on at 2 and off at 1;
    sending a hardcoded 0 would be out of range and silently clamped."""
    await _set_up_at(hass, config_entry, rig, "switch_channel_with_a_shifted_range")
    assert hass.states.get(OUTLET).state == "off"
    await _call(hass, SERVICE_TURN_ON, OUTLET)
    assert rig.sent == [("/equipment/switch/set", {"index": 0, "value": 2.0})]


@pytest.mark.parametrize(
    ("state", "temperature"),
    # Two setpoints, because one cannot tell a reading from a constant: 1.4.5
    # hardcoded -10 °C over 15 minutes whatever the camera was set to.
    [
        ("imaging", 0.0),
        pytest.param(
            "camera_cooling_to_minus_ten", -10.0, marks=pytest.mark.synthetic
        ),
    ],
)
async def test_the_cooler_sends_the_setpoint_the_camera_reports(
    hass: HomeAssistant, advance, rig, state: str, temperature: float
) -> None:
    """/cool has no "resume at the existing target" form, so starting the
    cooler has to name a temperature."""
    await advance(state)
    await _call(hass, SERVICE_TURN_ON, COOLER)
    assert rig.sent == [
        ("/equipment/camera/cool", {"temperature": temperature, "minutes": -1})
    ]


@pytest.mark.synthetic
async def test_the_cooler_refuses_to_start_without_a_setpoint(
    hass: HomeAssistant, advance, rig
) -> None:
    """A camera with no cooling reports `TargetTemp: "NaN"`. Cooling to a
    guessed temperature is worse than refusing."""
    await advance("camera_without_a_cooling_setpoint")
    with pytest.raises(ServiceValidationError):
        await _call(hass, SERVICE_TURN_ON, COOLER)
    assert rig.sent == []


async def test_turning_the_cooler_off_warms_rather_than_cooling(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """There is no cooler toggle: the two directions are different endpoints."""
    await _call(hass, SERVICE_TURN_OFF, COOLER)
    assert rig.sent == [("/equipment/camera/warm", {"minutes": -1})]


async def test_the_dew_heater_sends_the_parameter_the_api_binds(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """The parameter is `power`, not `on`; an unbound one is ignored and the
    call still answers Success: true."""
    await _call(hass, SERVICE_TURN_ON, DEW_HEATER)
    assert rig.sent == [("/equipment/camera/dew-heater", {"power": "true"})]


async def test_the_cover_switch_needs_a_panel_that_can_open_and_close(
    hass: HomeAssistant, set_up_with_flat_device
) -> None:
    """A panel with no cover would otherwise ship a switch that does nothing."""
    await set_up_with_flat_device(supports_open_close=False)
    assert hass.states.get(COVER) is None


async def test_the_cover_switch_is_off_while_the_cover_is_closed(
    hass: HomeAssistant, loaded_entry
) -> None:
    assert hass.states.get(COVER).state == "off"


async def test_a_cover_between_positions_reads_unknown(
    hass: HomeAssistant, set_up_with_flat_device
) -> None:
    """`NeitherOpenNorClosed` is a real `CoverState`, and calling it closed
    would report a shut cover over an open one."""
    await set_up_with_flat_device(cover_state="NeitherOpenNorClosed")
    assert hass.states.get(COVER).state == "unknown"


async def test_opening_the_cover_inverts_the_parameter_the_api_takes(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """set-cover's parameter is `closed`, so opening sends false."""
    await _call(hass, SERVICE_TURN_ON, COVER)
    assert rig.sent == [("/equipment/flatdevice/set-cover", {"closed": "false"})]


@pytest.mark.parametrize(
    ("method", "entity_id"),
    # Both entity classes: a descriptor switch and a switch-device channel.
    [("set_dew_heater", DEW_HEATER), ("set_switch_value", OUTLET)],
)
async def test_a_refused_command_surfaces_as_a_home_assistant_error(
    hass: HomeAssistant, loaded_entry, monkeypatch, method: str, entity_id: str
) -> None:
    async def refuse(self, *args) -> None:
        raise NinaCommandError("device not connected")

    monkeypatch.setattr(NinaClientV2, method, refuse)
    with pytest.raises(HomeAssistantError):
        await _call(hass, SERVICE_TURN_ON, entity_id)


@pytest.mark.parametrize("suffix", ["camera_cooler_switch", "guider_switch"])
async def test_the_kept_switches_keep_their_1_4_5_unique_id(
    hass: HomeAssistant, loaded_entry, advance, entity_registry, suffix: str
) -> None:
    """The guider is only observed in `imaging_guiding`, and the camera is
    observed in both, so one state registers the pair."""
    await advance("imaging_guiding")
    assert _registered(entity_registry, loaded_entry, suffix) is not None


@pytest.mark.parametrize("key", ["mount_tracking_switch", "flat_light_switch"])
async def test_the_cut_switches_are_not_registered(
    loaded_entry: MockConfigEntry, entity_registry, key: str
) -> None:
    """Tracking is `select.mount_tracking_rate`, whose options include
    `Stopped`; the panel's light is the `light` (§5.3.4)."""
    assert _registered(entity_registry, loaded_entry, key) is None


async def test_the_long_tail_ships_diagnostic_and_disabled(
    loaded_entry: MockConfigEntry, entity_registry
) -> None:
    """`dome_following` is absent from this assertion: no capture observes a
    dome, so §5.2.2 gates it out entirely."""
    entry = entity_registry.async_get(
        _registered(entity_registry, loaded_entry, "rotator_reverse")
    )
    assert (entry.entity_category, entry.disabled_by is not None) == (
        EntityCategory.DIAGNOSTIC,
        True,
    )


def test_every_dome_descriptor_is_marked_unverified() -> None:
    """Dome ships untested; the marker is enforced, not documented (§5.3.1)."""
    assert [d.key for d in DESCRIPTIONS if d.kind == "dome" and d.verified] == []

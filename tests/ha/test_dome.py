"""The dome, against the test VM's OmniSim dome (`docs/test-vm.md`).

Real wire data from a simulated dome. The reference rig has none, so every
other platform test sees the dome slot unobserved and creates nothing.
"""

from homeassistant.components.button.const import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.number import ATTR_VALUE
from homeassistant.components.number.const import (
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import pytest

from custom_components.nina_astrophotography.const import DOMAIN, SERVICE_DOME_OPEN
from ha.registry import get_device
from helpers import state_of

SHUTTER = "sensor.n_i_n_a_dome_shutter_status"
SLEWING = "binary_sensor.n_i_n_a_dome_slewing"
SYNCHRONIZED = "binary_sensor.n_i_n_a_dome_synchronized"
OPEN = "button.n_i_n_a_dome_open"
HOME = "button.n_i_n_a_dome_home"
AZIMUTH = "number.n_i_n_a_dome_azimuth"

# Every dome entity on a dome reporting every capability: its category, and
# whether it ships enabled.
SHIPPED = {
    "sensor.n_i_n_a_dome_shutter_status": (None, True),
    "button.n_i_n_a_dome_open": (None, True),
    "button.n_i_n_a_dome_close": (None, True),
    "button.n_i_n_a_dome_park": (None, True),
    "binary_sensor.n_i_n_a_dome_at_park": (None, True),
    "binary_sensor.n_i_n_a_dome_slewing": (None, True),
    "switch.n_i_n_a_dome_following": (EntityCategory.CONFIG, True),
    "binary_sensor.n_i_n_a_dome_synchronized": (EntityCategory.DIAGNOSTIC, True),
    "binary_sensor.n_i_n_a_dome_at_home": (EntityCategory.DIAGNOSTIC, False),
    "button.n_i_n_a_dome_home": (EntityCategory.CONFIG, False),
    "number.n_i_n_a_dome_azimuth": (EntityCategory.CONFIG, False),
}


# The simulator profile's interlocks.
INTERLOCKS = {
    "close_on_unsafe": True,
    "refuse_unsafe_shutter_move": False,
    "refuse_open_without_safety_monitor": True,
    "refuse_unpark_while_shut": False,
    "park_mount_before_shutter_move": False,
    "park_dome_before_shutter_move": False,
    "find_home_before_park": True,
}


def _dome_rows(hass: HomeAssistant, entry) -> list[er.RegistryEntry]:
    device = get_device(hass, entry, "dome")
    return er.async_entries_for_device(
        er.async_get(hass), device.id, include_disabled_entities=True
    )


async def _reload(hass: HomeAssistant, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()


async def test_each_dome_entity_ships_as_an_operator_uses_it(
    hass, config_entry, rig, set_up_at
) -> None:
    """The roof's state and its controls are on the device page; hand moves,
    which fight N.I.N.A.'s own slaving, ship disabled.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    assert {
        row.entity_id: (row.entity_category, row.disabled_by is None)
        for row in _dome_rows(hass, config_entry)
    } == SHIPPED


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("state", "created"),
    [
        (
            # Capability flags off but the shutter's, azimuth "NaN".
            "roll_off_roof",
            {SHUTTER, OPEN, "button.n_i_n_a_dome_close"},
        ),
        (
            # `CanSetShutter` off.
            "dome_without_shutter_control",
            set(SHIPPED) - {OPEN, "button.n_i_n_a_dome_close"},
        ),
    ],
    ids=["roll-off roof", "no shutter control"],
)
async def test_a_dome_gets_only_what_its_driver_can_do(
    hass, config_entry, rig, set_up_at, state, created
) -> None:
    """The parked capture with capability flags turned off."""
    await set_up_at(hass, config_entry, rig, state)
    assert {row.entity_id for row in _dome_rows(hass, config_entry)} == created


async def test_the_shutter_carries_ninas_own_interlocks(
    hass, config_entry, rig, set_up_at
) -> None:
    """What N.I.N.A. enforces whatever Home Assistant does, off the profile."""
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    attributes = state_of(hass, SHUTTER).attributes
    assert {key: attributes[key] for key in INTERLOCKS} == INTERLOCKS


async def test_a_dome_connected_after_setup_gets_its_entities(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    assert hass.states.get(SHUTTER) is None
    await advance("simulator_dome_parked")
    assert state_of(hass, SHUTTER).state == "closed"


@pytest.mark.parametrize(
    ("state", "entity_id", "expected"),
    [
        ("simulator_dome_parked", SHUTTER, "closed"),
        ("simulator_dome_following", SHUTTER, "open"),
        pytest.param(
            "simulator_dome_shutter_error",
            SHUTTER,
            "error",
            marks=pytest.mark.synthetic,
        ),
        ("simulator_dome_disconnected", SHUTTER, "unavailable"),
        ("simulator_dome_parked", SLEWING, "off"),
        ("simulator_dome_slewing", SLEWING, "on"),
        ("simulator_dome_following", SYNCHRONIZED, "on"),
        ("simulator_dome_parked", SYNCHRONIZED, "unknown"),
    ],
)
async def test_each_dome_reading(
    hass, loaded_entry, advance, state, entity_id, expected
) -> None:
    """Entered from parked, so the dropped dome is one that was observed.
    `ShutterError` is synthetic: the simulator cannot fail.
    """
    await advance("simulator_dome_parked")
    await advance(state)
    assert state_of(hass, entity_id).state == expected


# A command refused in one state: how to send it, the path it would reach,
# the state that refuses it, and the refusal.
_REFUSED = [
    pytest.param(
        (BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: HOME}),
        "/equipment/dome/home",
        "simulator_dome_following",
        "dome_following",
        id="home while following",
    ),
    pytest.param(
        (NUMBER_DOMAIN, SERVICE_SET_VALUE, {ATTR_ENTITY_ID: AZIMUTH, ATTR_VALUE: 90}),
        "/equipment/dome/slew",
        "simulator_dome_following",
        "dome_following",
        id="slew while following",
    ),
    pytest.param(
        (BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: OPEN}),
        "/equipment/dome/open",
        "simulator_dome_unsafe",
        "dome_unsafe",
        marks=pytest.mark.synthetic,
        id="open button while unsafe",
    ),
    pytest.param(
        (DOMAIN, SERVICE_DOME_OPEN, {}),
        "/equipment/dome/open",
        "simulator_dome_unsafe",
        "dome_unsafe",
        marks=pytest.mark.synthetic,
        id="open action while unsafe",
    ),
]


async def _set_up_with_hand_moves(hass, entry, rig, set_up_at, state: str) -> None:
    """Set up at `state` with home and azimuth enabled; they ship disabled."""
    await set_up_at(hass, entry, rig, state)
    registry = er.async_get(hass)
    for entity_id in (HOME, AZIMUTH):
        registry.async_update_entity(entity_id, disabled_by=None)
    await _reload(hass, entry)


@pytest.mark.parametrize(("call", "path", "state", "key"), _REFUSED)
async def test_a_dangerous_dome_command_is_refused(
    hass, config_entry, rig, set_up_at, call, path, state, key
) -> None:
    """N.I.N.A. answers a hand move while following by turning following off,
    and opens into an unsafe night unless its profile says otherwise. The
    unsafe state is the parked capture with the monitor's `IsSafe` false.
    """
    await _set_up_with_hand_moves(hass, config_entry, rig, set_up_at, state)
    with pytest.raises(ServiceValidationError) as refused:
        await hass.services.async_call(*call, blocking=True)
    assert refused.value.translation_key == key
    assert path not in [p for p, _ in rig.sent]


@pytest.mark.parametrize(("call", "path", "state", "key"), _REFUSED)
async def test_the_same_command_is_sent_when_it_is_safe(
    hass, config_entry, rig, set_up_at, call, path, state, key
) -> None:
    """Parked: not following, and the monitor reads safe."""
    await _set_up_with_hand_moves(
        hass, config_entry, rig, set_up_at, "simulator_dome_parked"
    )
    await hass.services.async_call(*call, blocking=True)
    assert path in [p for p, _ in rig.sent]


def _disable_every_dome_row(hass: HomeAssistant, entry, user_disabled: str) -> None:
    """As 2.0.0 left them, with one row the user disabled besides."""
    registry = er.async_get(hass)
    for row in _dome_rows(hass, entry):
        registry.async_update_entity(
            row.entity_id,
            disabled_by=er.RegistryEntryDisabler.USER
            if row.entity_id == user_disabled
            else er.RegistryEntryDisabler.INTEGRATION,
        )


def _enabled(hass: HomeAssistant, entry) -> set[str]:
    return {row.entity_id for row in _dome_rows(hass, entry) if row.disabled_by is None}


async def test_an_upgrade_enables_the_dome_rows_shipped_enabled(
    hass, config_entry, rig, set_up_at
) -> None:
    """A row the user disabled stays so, as do the hand moves."""
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    _disable_every_dome_row(hass, config_entry, user_disabled=SHUTTER)
    await _reload(hass, config_entry)
    assert _enabled(hass, config_entry) == {
        entity_id
        for entity_id, (_, enabled) in SHIPPED.items()
        if enabled and entity_id != SHUTTER
    }


@pytest.mark.synthetic
async def test_an_upgrade_leaves_a_roll_off_roofs_unusable_rows_disabled(
    hass, config_entry, rig, set_up_at
) -> None:
    """An install upgraded from 2.0.0 holds a row for every dome entity,
    whatever the driver can do. The roof is the parked capture with every
    capability flag but the shutter's off.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    _disable_every_dome_row(hass, config_entry, user_disabled="")
    rig.goto("roll_off_roof")
    await _reload(hass, config_entry)
    assert _enabled(hass, config_entry) == {
        SHUTTER,
        OPEN,
        "button.n_i_n_a_dome_close",
    }


async def test_an_upgrade_honours_an_entry_that_disables_new_entities(
    hass, config_entry, rig, set_up_at
) -> None:
    """Home Assistant records that system option as `disabled_by` integration."""
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    _disable_every_dome_row(hass, config_entry, user_disabled="")
    hass.config_entries.async_update_entry(config_entry, pref_disable_new_entities=True)
    await _reload(hass, config_entry)
    assert _enabled(hass, config_entry) == set()


@pytest.mark.synthetic
async def test_opening_is_sent_when_the_monitor_is_not_reporting(
    hass, config_entry, rig, set_up_at
) -> None:
    """Only a monitor reporting unsafe refuses; one that is down refuses
    nothing, as on a rig without one. The monitor's block is derived down.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_monitor_down")
    await hass.services.async_call(DOMAIN, SERVICE_DOME_OPEN, {}, blocking=True)
    assert "/equipment/dome/open" in [p for p, _ in rig.sent]


async def test_an_upgrade_enables_the_rows_of_a_dome_connected_later(
    hass, config_entry, rig, set_up_at
) -> None:
    """N.I.N.A. may connect the dome only when a sequence starts, long after
    Home Assistant has set up.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    _disable_every_dome_row(hass, config_entry, user_disabled="")
    rig.goto("imaging")
    await _reload(hass, config_entry)
    assert _enabled(hass, config_entry) == set()

    rig.goto("simulator_dome_parked")
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert _enabled(hass, config_entry) == {
        entity_id for entity_id, (_, enabled) in SHIPPED.items() if enabled
    }

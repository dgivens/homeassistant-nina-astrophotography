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

from custom_components.nina_astrophotography.const import DOMAIN
from ha.registry import get_device
from helpers import state_of

SHUTTER = "sensor.n_i_n_a_dome_shutter_status"
SYNCHRONIZED = "binary_sensor.n_i_n_a_dome_synchronized"
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


def _dome_rows(hass: HomeAssistant, registry: er.EntityRegistry, entry):
    device = get_device(hass, entry, "dome")
    return er.async_entries_for_device(
        registry, device.id, include_disabled_entities=True
    )


async def test_each_dome_entity_ships_as_an_operator_uses_it(
    hass, config_entry, rig, set_up_at, entity_registry
) -> None:
    """The roof's state and its controls are on the device page; hand moves,
    which fight N.I.N.A.'s own slaving, ship disabled.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")
    assert {
        row.entity_id: (row.entity_category, row.disabled_by is None)
        for row in _dome_rows(hass, entity_registry, config_entry)
    } == SHIPPED


async def test_a_roll_off_roof_gets_its_shutter_alone(
    hass, config_entry, rig, set_up_at, entity_registry
) -> None:
    """No azimuth, park or home on the driver: no entity that would drive one."""
    await set_up_at(hass, config_entry, rig, "roll_off_roof")
    assert sorted(
        row.entity_id for row in _dome_rows(hass, entity_registry, config_entry)
    ) == [
        "binary_sensor.n_i_n_a_dome_slewing",
        "button.n_i_n_a_dome_close",
        "button.n_i_n_a_dome_open",
        "sensor.n_i_n_a_dome_shutter_status",
    ]


async def test_a_dome_connected_after_setup_gets_its_entities(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    assert hass.states.get(SHUTTER) is None
    await advance("simulator_dome_parked")
    assert state_of(hass, SHUTTER).state == "closed"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("simulator_dome_parked", "closed"),
        ("simulator_dome_following", "open"),
        pytest.param("simulator_dome_opening", "opening", marks=pytest.mark.synthetic),
        pytest.param(
            "simulator_dome_shutter_error", "error", marks=pytest.mark.synthetic
        ),
        ("simulator_dome_disconnected", "unavailable"),
    ],
)
async def test_the_shutter_reads_each_state(
    hass, loaded_entry, advance, state, expected
) -> None:
    """Entered from parked, so the dropped dome is one that was observed."""
    await advance("simulator_dome_parked")
    await advance(state)
    assert state_of(hass, SHUTTER).state == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [("simulator_dome_following", "on"), ("simulator_dome_parked", "unknown")],
)
async def test_synchronized_reads_only_while_following(
    hass, config_entry, rig, set_up_at, state, expected
) -> None:
    """N.I.N.A. keeps the last `IsSynchronized` after following stops."""
    await set_up_at(hass, config_entry, rig, state)
    assert state_of(hass, SYNCHRONIZED).state == expected


async def _move_by_hand(hass: HomeAssistant, entity_id: str) -> None:
    if entity_id == HOME:
        await hass.services.async_call(
            BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: HOME}, blocking=True
        )
    else:
        await hass.services.async_call(
            NUMBER_DOMAIN,
            SERVICE_SET_VALUE,
            {ATTR_ENTITY_ID: AZIMUTH, ATTR_VALUE: 90},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("entity_id", "path"),
    [(HOME, "/equipment/dome/home"), (AZIMUTH, "/equipment/dome/slew")],
)
@pytest.mark.parametrize(
    ("state", "refused"),
    [("simulator_dome_following", True), ("simulator_dome_parked", False)],
)
async def test_a_hand_move_is_refused_while_following(
    hass, config_entry, rig, set_up_at, entity_registry, entity_id, path, state, refused
) -> None:
    """N.I.N.A. answers one by turning following off, and the slit leaves the
    scope with nothing said.
    """
    await set_up_at(hass, config_entry, rig, state)
    entity_registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()
    if refused:
        with pytest.raises(ServiceValidationError):
            await _move_by_hand(hass, entity_id)
    else:
        await _move_by_hand(hass, entity_id)
    assert [p for p, _ in rig.sent if p == path] == ([] if refused else [path])


# A row's `unique_id` suffix, the platform it is on, who disabled it before the
# upgrade, and whether it is enabled after.
_UPGRADED = [
    ("dome_shutter_status", "sensor", er.RegistryEntryDisabler.INTEGRATION, True),
    ("btn_dome_open", "button", er.RegistryEntryDisabler.INTEGRATION, True),
    ("dome_following", "switch", er.RegistryEntryDisabler.INTEGRATION, True),
    ("btn_dome_close", "button", er.RegistryEntryDisabler.USER, False),
    ("dome_home", "button", er.RegistryEntryDisabler.INTEGRATION, False),
    ("dome_azimuth", "number", er.RegistryEntryDisabler.INTEGRATION, False),
]


async def test_an_upgrade_enables_the_dome_rows_that_now_ship_enabled(
    hass, config_entry, rig, set_up_at, entity_registry
) -> None:
    """A row the user disabled stays so, as do the hand moves."""
    config_entry.add_to_hass(hass)
    for suffix, platform, disabler, _ in _UPGRADED:
        entity_registry.async_get_or_create(
            platform,
            DOMAIN,
            f"{config_entry.entry_id}_{suffix}",
            config_entry=config_entry,
            disabled_by=disabler,
        )
    rig.goto("imaging")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.minor_version == 2
    assert {
        suffix: entity_registry.async_get(
            entity_registry.async_get_entity_id(
                platform, DOMAIN, f"{config_entry.entry_id}_{suffix}"
            )
        ).disabled_by
        is None
        for suffix, platform, _, _ in _UPGRADED
    } == {suffix: enabled for suffix, _, _, enabled in _UPGRADED}

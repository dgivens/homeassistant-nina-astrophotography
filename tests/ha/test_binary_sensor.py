"""Binary sensors: what was cut, what survived, and the safety polarity.

Every assertion goes through `hass.states` or the entity registry — the
registry for the long tail, which ships disabled and so has no state.
"""
import pytest
from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.binary_sensor import DESCRIPTIONS
from custom_components.nina_astrophotography.const import DOMAIN

AUTOFOCUS_FAILED = "binary_sensor.n_i_n_a_focuser_autofocus_failed"
MONITOR_CONNECTED = "binary_sensor.n_i_n_a_safety_monitor_connected"
SEQUENCE_RUNNING = "binary_sensor.n_i_n_a_sequence_running"
UNSAFE = "binary_sensor.n_i_n_a_safety_monitor_unsafe"


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    """The entity id claiming this `unique_id` suffix, or None if nothing does.

    The suffix is the 1.4.5 key wherever one survives, which is what an upgraded
    install's registry rows are keyed on.
    """
    return registry.async_get_entity_id(
        BINARY_SENSOR_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def _set_up_at(hass: HomeAssistant, entry: MockConfigEntry, rig, state: str):
    """Set the entry up with the rig already in `state`.

    `/event-history` is replayed once, at setup, so a state that differs only in
    its event history has to be in force before the entry loads — advancing on
    to it leaves the events the first replay already folded in.
    """
    rig.goto(state)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    "key",
    [
        # §5.2.1 — availability carries these.
        "camera_connected", "mount_connected", "focuser_connected",
        "filterwheel_connected", "guider_connected", "rotator_connected",
        "dome_connected", "flatdevice_connected", "weather_connected",
        "switch_connected",
        # §5.2.3 — read-only mirrors of a switch, number, select or sensor.
        "camera_cooling_enabled", "camera_dew_heater_on", "dome_following",
        "rotator_reversed", "guider_is_guiding", "dome_shutter_open",
        "flatdevice_cover_open", "flatdevice_light_on", "mount_tracking",
        "livestack_running",
        # No `Slewing` on MountModel: nothing above the seam can compute it.
        "mount_slewing",
    ],
)
async def test_the_cut_binary_sensors_are_not_registered(
    loaded_entry: MockConfigEntry, entity_registry, key: str
) -> None:
    assert _registered(entity_registry, loaded_entry, key) is None


@pytest.mark.parametrize(
    "suffix",
    # The four 1.4.5 spellings are the point: a survivor keeps its unique_id,
    # so an upgraded install keeps the registry row and the automations on it.
    ["safetymonitor_is_safe", "safetymonitor_connected", "mount_parked",
     "camera_exposing", "mount_at_home", "focuser_is_moving",
     "filterwheel_is_moving", "rotator_is_moving", "rotator_synced",
     "autofocus_failed", "sequence_running"],
)
async def test_the_kept_binary_sensors_are_registered(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    """The dome's three are absent from this table on purpose: no capture has a
    dome carrying a DeviceId, so the slot is None and §5.2.2 gates them out."""
    assert _registered(entity_registry, loaded_entry, suffix) is not None


@pytest.mark.parametrize(
    ("state", "expected"),
    [("imaging", "on"), ("imaging_guiding", "off")],
    ids=["IsSafe false", "IsSafe true"],
)
async def test_the_safety_sensor_reads_on_when_conditions_are_unsafe(
    hass: HomeAssistant, advance, state: str, expected: str
) -> None:
    """HA's SAFETY device class is on = problem, and the shipped blueprint
    triggers on `to: "on"`. Backwards, it ships an abort that fires when the
    sky clears and stays silent under cloud."""
    await advance(state)
    assert hass.states.get(UNSAFE).state == expected


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [(MONITOR_CONNECTED, "off"), (UNSAFE, "unavailable")],
    ids=["the connectivity sensor", "the safety sensor"],
)
async def test_only_the_connectivity_sensor_survives_the_monitors_disconnection(
    hass: HomeAssistant, advance, entity_id: str, expected: str
) -> None:
    """The one §7.3 level-2 exemption, and its boundary.

    A roof-close automation triggering on `to: "off"` must still fire when the
    monitor itself drops out, and `to: "unavailable"` cannot substitute — it
    conflates device-disconnected, N.I.N.A.-unreachable, HA-restarting and
    coordinator-failed. The exemption is per descriptor, not per device.
    """
    await advance("safety_monitor_disconnected")
    assert hass.states.get(entity_id).state == expected


async def test_an_unreachable_rig_still_makes_the_connectivity_sensor_unavailable(
    hass: HomeAssistant, advance
) -> None:
    """Level 1 is not exempted: nothing is known about the monitor when nothing
    is known about the rig."""
    await advance("nina_unreachable")
    assert hass.states.get(MONITOR_CONNECTED).state == "unavailable"


async def test_an_unanswered_autofocus_start_raises_the_problem_sensor(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, inside_the_dawn_session
) -> None:
    """There is no autofocus-failed event: the dawn night's eighth
    AUTOFOCUS-STARTING going unanswered past the timeout is the whole signal."""
    await _set_up_at(hass, config_entry, rig, "autofocus_timed_out")
    assert hass.states.get(AUTOFOCUS_FAILED).state == "on"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("sequence_complete_tracking_off", "off"),
        pytest.param("idle_with_stale_running_nodes", "off",
                     marks=pytest.mark.synthetic),
        ("imaging_guiding", "on"),
    ],
)
async def test_sequence_running_follows_activity_and_not_node_status(
    hass: HomeAssistant, advance, state: str, expected: str
) -> None:
    """§6.2: node `Status` persists from the loaded sequence file and from
    prior runs, so an idle rig reports RUNNING nodes with nothing happening.
    The meridian blueprint uses this sensor as a condition."""
    await advance(state)
    assert hass.states.get(SEQUENCE_RUNNING).state == expected


@pytest.mark.parametrize(
    "suffix",
    ["focuser_is_moving", "filterwheel_is_moving", "rotator_is_moving",
     "rotator_synced"],
)
async def test_the_long_tail_ships_diagnostic_and_disabled(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    """Gold entity-category / entity-disabled-by-default. The dome's three are
    not here: no capture observes a dome, so they are never registered."""
    row = entity_registry.async_get(
        _registered(entity_registry, loaded_entry, suffix)
    )
    assert (row.entity_category, row.disabled_by is not None) == (
        EntityCategory.DIAGNOSTIC, True,
    )


async def test_a_device_observed_after_setup_gets_its_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, caplog
) -> None:
    """Equipment routinely connects long after Home Assistant starts, and the
    focuser carries no DeviceId in the partial-connection capture.

    The second refresh pins the other half of the rule: the listener runs on
    every publish, so without the `added` set it would re-add every descriptor.
    The entity registry cannot show that — Home Assistant recognises the
    re-added `unique_id`, refuses the entity and logs it — so the assertion is
    on the log line, which is the only observable difference.
    """
    await _set_up_at(hass, config_entry, rig, "partial_equipment_connection")
    assert hass.states.get(AUTOFOCUS_FAILED) is None

    coordinator = config_entry.runtime_data.coordinator
    rig.goto("imaging")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(AUTOFOCUS_FAILED) is not None

    caplog.clear()
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert "does not generate unique IDs" not in caplog.text


async def test_a_hub_entity_is_not_on_an_equipment_device(
    loaded_entry: MockConfigEntry, entity_registry, device_registry
) -> None:
    """`kind=None` puts a rig-scoped entity on the hub (§5.1), which is what
    keeps `binary_sensor.<instance>_sequence_running` free of a device word."""
    entry = entity_registry.async_get(SEQUENCE_RUNNING)
    assert device_registry.async_get(entry.device_id).name == "N.I.N.A."


def test_every_dome_descriptor_is_marked_unverified() -> None:
    """Dome ships untested; the marker is enforced, not documented (§5.3.1)."""
    assert [d.key for d in DESCRIPTIONS if d.kind == "dome" and d.verified] == []

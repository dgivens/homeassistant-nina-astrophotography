"""sensor: the equipment readings and the sequence pair.

The session family and the weather channels have their own files. What is here
is the rule the equipment table lives by — a sentinel reads `unknown`, never a
number — and the §5.2.3 cuts and `unique_id` survivals, which are observable
only in the registry.

The blanket `"NaN"` rule is not retested per sensor: the mapper's own suite
pins it field by field, and the only connected device the corpus ever shows
reporting `"NaN"` is the weather station, whose channels answer `unavailable`
rather than `unknown` by a rule of their own (§5.2.2).
"""
import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import DOMAIN

FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip"
FOCUSER_POSITION = "sensor.n_i_n_a_focuser_position"


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    return registry.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def test_the_meridian_sentinel_is_unknown_but_a_real_reading_is_minutes(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """24 is what an untracked mount returns; 12 h is legitimate — a mount
    inside a pier-side window adds 12 — so a "≥12 → unknown" rule is wrong.
    The unit is minutes, which is what a flip warning is written in."""
    await advance("imaging_guiding")
    assert float(hass.states.get(FLIP).state) > 0
    await advance("sequence_complete_tracking_off")
    assert hass.states.get(FLIP).state == "unknown"


async def test_the_focuser_position_sensor_carries_a_state_class(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """Long-term statistics: `NumberEntity` has none, and focuser position
    against temperature is the standard temp-comp-slope diagnostic."""
    entity_registry.async_update_entity(FOCUSER_POSITION, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(FOCUSER_POSITION).attributes["state_class"] == "measurement"


@pytest.mark.parametrize(
    "suffix",
    [
        "rotator_position",
        "rotator_mechanical_position",
        "dome_azimuth",
        "camera_usb_limit",
        "camera_target_temperature",
        "camera_current_filter",
        "camera_name",
        "mount_status",
        "safetymonitor_name",
        "sequence_status",
    ],
    ids=lambda suffix: suffix,
)
async def test_the_cut_sensors_are_not_registered(
    loaded_entry: MockConfigEntry, advance, entity_registry, suffix: str
) -> None:
    """§5.2.3's read-only mirrors, the driver names §5.1 moved onto the device
    registry, and `sequence_status` — node status persists from prior runs, so
    it reported RUNNING on an idle rig (§6.2)."""
    await advance("imaging_guiding")
    assert _registered(entity_registry, loaded_entry, suffix) is None


@pytest.mark.parametrize(
    "suffix",
    [
        "camera_temperature",
        "camera_cooler_power",
        "camera_gain",
        "camera_offset",
        "camera_status",
        "mount_ra",
        "mount_dec",
        "mount_altitude",
        "mount_azimuth",
        "mount_sidereal_time",
        "mount_time_to_meridian_flip",
        "focuser_position",
        "focuser_temperature",
        "focuser_step_size",
        "guider_status",
        "guider_rms_total",
        "guider_rms_ra",
        "guider_rms_dec",
        "sequence_target_name",
        "sequence_progress",
    ],
    ids=lambda suffix: suffix,
)
async def test_the_kept_sensors_keep_their_1_4_5_unique_id(
    loaded_entry: MockConfigEntry, advance, entity_registry, suffix: str
) -> None:
    """An upgrade must not strand a registry row: Home Assistant keys on
    `unique_id`, so a changed one mints a fresh entity and leaves the
    automation pointing at the old id permanently unavailable."""
    await advance("imaging_guiding")
    assert _registered(entity_registry, loaded_entry, suffix) is not None


async def test_the_sequence_target_is_the_one_the_scheduler_announced(
    hass: HomeAssistant, loaded_entry
) -> None:
    """A Target Scheduler rig publishes no target in `/sequence/json` — its
    imaging container holds the list internally — so `TS-TARGETSTART` is where
    the name comes from."""
    assert hass.states.get("sensor.n_i_n_a_sequence_target").state == "NGC 281"


async def test_sequence_progress_is_unknown_where_no_node_counts_iterations(
    hass: HomeAssistant, loaded_entry
) -> None:
    """The truth about what this API exposes on a Target Scheduler rig.
    Inventing a percentage from node statuses would be worse (§6.2)."""
    assert hass.states.get("sensor.n_i_n_a_sequence_progress").state == "unknown"

"""The scenario fixtures move a loaded entry between captured rig states."""
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

# The /application-start the restart capture carries. Everything the design
# filters by process boundary keys on this string.
RESTART_GENERATION = "2026-09-04T10:58:59.1429105-05:00"


async def test_advancing_to_a_restart_publishes_the_new_generation(
    loaded_entry: MockConfigEntry, advance
) -> None:
    await advance("nina_restarted")
    assert loaded_entry.runtime_data.coordinator.data.generation == RESTART_GENERATION


async def test_a_state_awaiting_capture_skips_rather_than_being_faked(advance) -> None:
    """Reported as skipped and named: a hand-written fixture would encode the
    spec's mistakes instead of the rig's behaviour."""
    await advance("camera_warm_at_setup")
    raise AssertionError("advance() must skip a state the corpus cannot show")


async def test_two_instances_each_read_their_own_rig(
    hass: HomeAssistant, two_rigs
) -> None:
    """One session serves both hosts, so a router bug shows as both entries
    publishing the same generation."""
    first, second = two_rigs
    assert first.runtime_data.coordinator.data.generation != RESTART_GENERATION
    assert second.runtime_data.coordinator.data.generation == RESTART_GENERATION
    assert [e.state for e in two_rigs] == [ConfigEntryState.LOADED] * 2

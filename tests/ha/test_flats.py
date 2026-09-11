"""Flats: disabled by default, because `/flats/status` observes only API-started runs."""
from homeassistant.core import HomeAssistant

STATE = "sensor.n_i_n_a_flats_state"
TOTAL = "sensor.n_i_n_a_flats_total_iterations"


async def test_flats_entities_are_disabled_by_default(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """This rig runs Target Scheduler Flats, so `/flats/status` reads
    `{State: "Finished", TotalIterations: -1, CompletedIterations: -1}` straight
    through a completed dawn run — an entity that reports a stale "Finished"
    all night is worse than no entity."""
    entry = entity_registry.async_get(STATE)
    assert entry.disabled_by is not None
    assert entry.entity_category == "diagnostic"


async def test_the_idle_iteration_sentinel_is_unknown(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """An idle wizard reports -1 iterations, which is not a count."""
    entity_registry.async_update_entity(TOTAL, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(TOTAL).state == "unknown"

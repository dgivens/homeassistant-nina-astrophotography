"""The entity registry, snapshotted — the rename artifact (§8.6).

The **registry**, not `hass.states`: the disabled long tail has no state, so a
state snapshot omits exactly the entities most likely to be misconfigured. What
is recorded per row is what an upgrade turns on — `unique_id`, `entity_id`,
`original_name`, `entity_category` and whether it ships enabled.

**Regeneration is its own commit, and the diff IS the review.** Its job here is
review, not regression: a changed `unique_id` is not a bug, it just has to be
seen, and it has to be reconciled against `docs/2.0-renames.md`.

The rig is walked to `imaging_guiding` first — the one state whose every
endpoint is captured, with the guider up. What no capture can show is still
missing: the dome's entities, which need hardware nobody has, and the switch
device's `number` and `sensor` channels, which need a driver richer than this
rig's two-outlet bridge.
"""
from pathlib import Path

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

# Syrupy's own directory, so the plain-text inventory sits beside the .ambr
# it is regenerated with.
SNAPSHOTS = Path(__file__).parent / "__snapshots__"

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.IMAGE,
    Platform.EVENT,
]


@pytest.fixture
async def registered(hass: HomeAssistant, loaded_entry, advance) -> MockConfigEntry:
    """Every entity the captured corpus can produce, in one registry."""
    await advance("imaging_guiding")
    return loaded_entry


def _rows(hass: HomeAssistant, entry: MockConfigEntry, platform: Platform) -> list:
    registry = er.async_get(hass)
    return [
        {
            "unique_id": row.unique_id,
            "entity_id": row.entity_id,
            "original_name": row.original_name,
            "entity_category": row.entity_category,
            "enabled_default": not row.disabled_by,
        }
        for row in sorted(
            (
                row
                for row in er.async_entries_for_config_entry(registry, entry.entry_id)
                if row.domain == platform
            ),
            key=lambda row: row.unique_id,
        )
    ]


@pytest.mark.parametrize("platform", PLATFORMS, ids=lambda p: p.value)
async def test_registry_snapshot(
    hass: HomeAssistant, registered, snapshot: SnapshotAssertion, platform: Platform
) -> None:
    assert _rows(hass, registered, platform) == snapshot


async def test_a_small_state_snapshot_pins_the_value_contracts(
    hass: HomeAssistant, registered, snapshot: SnapshotAssertion
) -> None:
    """Separate and deliberately small — the registry snapshot covers naming,
    and a wide state snapshot would churn on every fixture change."""
    watched = [
        "sensor.n_i_n_a_session_avg_hfr",
        "sensor.n_i_n_a_session_integration_time",
        "binary_sensor.n_i_n_a_safety_monitor_unsafe",
    ]
    assert {e: hass.states.get(e).state for e in watched} == snapshot


async def test_entity_id_inventory_is_current(hass: HomeAssistant, registered) -> None:
    """A committed, plain-text list of every 2.0 entity id.

    Phase D's blueprint and card tests read this rather than scraping syrupy's
    `.ambr` format, which would couple them to a snapshot serialization.
    Regenerating it is part of the snapshot commit.
    """
    registry = er.async_get(hass)
    ids = sorted(
        row.entity_id
        for row in er.async_entries_for_config_entry(registry, registered.entry_id)
    )
    path = SNAPSHOTS / "entity_ids.txt"
    if not path.exists() or path.read_text(encoding="utf-8").split() != ids:
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        pytest.fail("entity_ids.txt regenerated — review and commit it")

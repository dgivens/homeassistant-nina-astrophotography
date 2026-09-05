"""The N.I.N.A. generation, read from the published `NinaData`.

A restart is applied by FILTERING on the generation tag: the pre-restart frames
stay in the coordinator's set and stop counting. Clearing would race a
concurrent poll and lose events arriving during the refetch.
"""
from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from scenarios.fake_rig import FakeRig

# The /application-start the restart capture carries.
RESTART_GENERATION = "2026-09-04T10:58:59.1429105-05:00"


@pytest.fixture(autouse=True)
def _inside_the_dawn_session(freezer):
    """07:30 on the rig — after its dawn flats, before its noon rollover — so
    the 122 captured frames are all one session."""
    freezer.move_to("2026-09-04T12:30:00+00:00")


def _reseeds(rig: FakeRig) -> int:
    """How many times the rig has been asked for /image-history?all=true."""
    return sum(1 for _, params in rig.requests if params == {"all": "true"})


async def test_setup_seeds_the_session_from_the_full_history(
    loaded_entry: MockConfigEntry,
) -> None:
    """`?all=true` is the only reseed source: the bare path answers the newest
    frame alone, which would leave the session count reading 1 all night."""
    assert loaded_entry.runtime_data.coordinator.data.session.image_count == 122


async def test_a_restart_empties_the_session_without_clearing_the_set(
    loaded_entry: MockConfigEntry, advance
) -> None:
    await advance("nina_restarted")
    data = loaded_entry.runtime_data.coordinator.data
    assert data.generation == RESTART_GENERATION
    assert data.session.image_count == 0


async def test_the_event_stream_follows_the_new_generation(
    loaded_entry: MockConfigEntry, advance
) -> None:
    """An event tagged with the stale generation would be filtered out of the
    fold the moment it arrived."""
    await advance("nina_restarted")
    assert loaded_entry.runtime_data.events.generation == RESTART_GENERATION


async def test_a_count_mismatch_reseeds_only_once_it_persists(
    rig: FakeRig, loaded_entry: MockConfigEntry, advance
) -> None:
    """A frame saved between the `?count=true` read and the history read fails
    the invariant for one tick; reseeding on that costs a 62 KB refetch every
    time it happens."""
    seeded = _reseeds(rig)
    await advance("imaging_count_ahead")
    assert _reseeds(rig) == seeded
    await advance("imaging_count_ahead")
    assert _reseeds(rig) == seeded + 1


async def test_an_empty_history_is_not_a_failure(
    loaded_entry: MockConfigEntry, advance
) -> None:
    """Of the three ways an empty history answers, only bare `/image-history`'s
    `Index out of range` looks like one."""
    await advance("nina_restarted")
    assert loaded_entry.state is ConfigEntryState.LOADED

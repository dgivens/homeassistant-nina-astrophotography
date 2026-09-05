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


async def test_a_restart_reseeds_the_new_generations_frames(
    rig: FakeRig, loaded_entry: MockConfigEntry, advance, freezer
) -> None:
    """N.I.N.A. restarts at dusk and saves subs before Home Assistant's next
    poll, so a restart that only moved the generation would read 0 frames until
    the double-mismatch guard fired two ticks later.

    `imaging_guiding` IS such a restart: a new `/application-start` with 27
    frames already down. The clock moves into that state's own session.
    """
    freezer.move_to("2026-09-05T07:30:00+00:00")
    await advance("imaging_guiding")
    assert loaded_entry.runtime_data.coordinator.data.session.image_count == 27
    assert _reseeds(rig) == 2                  # setup, then the restart


async def test_the_event_stream_follows_the_new_generation(
    loaded_entry: MockConfigEntry, advance
) -> None:
    """An event tagged with the stale generation would be filtered out of the
    fold the moment it arrived."""
    await advance("nina_restarted")
    assert loaded_entry.runtime_data.events.generation == RESTART_GENERATION


@pytest.mark.synthetic
@pytest.mark.parametrize(("ticks", "reseeds"), [(1, 0), (2, 1), (5, 1)])
async def test_a_count_mismatch_reseeds_once_it_persists_and_never_again(
    rig: FakeRig, loaded_entry: MockConfigEntry, advance, ticks: int, reseeds: int
) -> None:
    """A frame saved between the `?count=true` read and the history read fails
    the invariant for one tick, and reseeding on that costs a 62 KB refetch
    every time it happens. A gap the refetch cannot close — an unmappable item,
    or two frames sharing a `(date, filename)` — is structural, so asking again
    every two ticks would go on for the life of the process.

    No capture can hold a snapshot of a race: the state varies the captured
    count envelope's one number."""
    seeded = _reseeds(rig)
    for _ in range(ticks):
        await advance("imaging_count_ahead")
    assert _reseeds(rig) == seeded + reseeds


@pytest.mark.synthetic
async def test_an_unreadable_application_start_does_not_blank_the_session(
    loaded_entry: MockConfigEntry, advance
) -> None:
    """Adopting the null would filter every frame of the generation away for a
    tick, and the session sensors would read zero and recover."""
    before = loaded_entry.runtime_data.coordinator.data.generation
    await advance("imaging_start_unreadable")
    data = loaded_entry.runtime_data.coordinator.data
    assert data.generation == before
    assert data.session.image_count == 122


@pytest.mark.synthetic
async def test_a_generation_adopted_late_reseeds_the_frames_under_it(
    hass, config_entry: MockConfigEntry, rig: FakeRig
) -> None:
    """An `/application-start` unreadable on the FIRST poll seeds the frames
    under a null tag; adopting the real one on the next poll filters every one
    of them out of the fold, and the reseed guard takes two more ticks to put
    them back.

    A transiently empty endpoint has no capture: the state varies the captured
    envelope's one scalar."""
    rig.goto("imaging_start_unreadable")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    rig.goto("imaging")
    await config_entry.runtime_data.coordinator.async_refresh()
    assert config_entry.runtime_data.coordinator.data.session.image_count == 122


async def test_an_empty_history_is_not_a_failure(
    loaded_entry: MockConfigEntry, advance
) -> None:
    """Of the three ways an empty history answers, only bare `/image-history`'s
    `Index out of range` looks like one."""
    await advance("nina_restarted")
    assert loaded_entry.state is ConfigEntryState.LOADED

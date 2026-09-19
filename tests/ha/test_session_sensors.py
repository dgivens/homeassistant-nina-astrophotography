"""The session family: one family, fed by both paths (§5.2.4).

`dawn_flats` is content-identical to `imaging` — the 67 flats sit in the same
captured history, because dawn flats are a phase of the night rather than a
different snapshot — so the dawn assertions hold under either name. The name
says what is being exercised.

Every test here runs inside the captured session: the fold measures the
rollover against a real clock, and 2026-09-03's frames are outside today's
window.
"""
from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import DOMAIN

pytestmark = pytest.mark.usefixtures("inside_the_dawn_session")

LAST_IMAGE_HFR = "sensor.n_i_n_a_last_image_hfr"
LAST_IMAGE_MEAN_ADU = "sensor.n_i_n_a_last_image_mean_adu"
SESSION_AVG_HFR = "sensor.n_i_n_a_session_avg_hfr"
SESSION_INTEGRATION_TIME = "sensor.n_i_n_a_session_integration_time"
SESSION_START = "sensor.n_i_n_a_session_start"

RIG = timezone(timedelta(hours=-5))


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    """The entity id claiming this `unique_id` suffix, or None if nothing does."""
    return registry.async_get_entity_id(
        SENSOR_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


async def test_the_last_image_sensors_ignore_calibration_frames(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """The newest frame of the night is a flat: HFR 0, Mean ADU 33,139.77. The
    newest LIGHT is HFR 1.454, Mean ADU 548.6, and that is what these report."""
    await advance("dawn_flats")
    assert (float(hass.states.get(LAST_IMAGE_HFR).state),
            float(hass.states.get(LAST_IMAGE_MEAN_ADU).state)) == (
        pytest.approx(1.454, abs=0.001), pytest.approx(548.6, abs=0.1))


async def test_integration_time_sums_actual_exposures(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """Count x shortest exposure gives 2.75 h on this night — a 2.25x error."""
    await advance("dawn_flats")
    assert float(hass.states.get(SESSION_INTEGRATION_TIME).state) == pytest.approx(
        6.20, abs=0.02
    )


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("by_target", {"Dark Shark Nebula", "Lobster & Bubble", "NGC 281",
                       "Wizard Nebula"}),
        ("by_filter", {"B", "L", "O", "R", "S"}),
    ],
)
async def test_the_breakdowns_are_attributes_not_entities(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance,
    attribute: str, expected: set[str],
) -> None:
    """Per-target HFR means ranged 1.429-1.667 against a session-wide 1.513, so
    the breakdown is worth carrying — but as attributes of the summary sensor,
    not as entities that come and go with the night's target list."""
    await advance("dawn_flats")
    assert set(hass.states.get(SESSION_AVG_HFR).attributes[attribute]) == expected


async def test_recent_frames_is_every_type_newest_first_and_bounded(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """Unlike the sensor's own LIGHT-only state, `recent_frames` is every type
    this process saved, which a dashboard's strip must label correctly
    whatever it lands on. The newest frame of the night is a flat, not a
    light (see the ignores-calibration test above)."""
    await advance("dawn_flats")
    recent = hass.states.get(LAST_IMAGE_MEAN_ADU).attributes["recent_frames"]
    assert len(recent) == 20
    assert recent[0]["mean"] == pytest.approx(33139.77, abs=0.01)


async def test_recent_lights_survive_a_dawn_flat_run(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """What the frame-stats card draws its sparklines from, so a page reload
    keeps them: lights only, oldest first, ending on the sensor's own frame."""
    await advance("dawn_flats")
    state = hass.states.get(LAST_IMAGE_HFR)
    recent = state.attributes["recent_lights"]
    assert len(recent) == 55
    assert recent[-1]["hfr"] == pytest.approx(float(state.state))


async def test_recent_lights_name_their_target(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance
) -> None:
    """A Target Scheduler night changes field mid-series, and star count moves
    by whole factors with it; the card marks the change from this field."""
    await advance("dawn_flats")
    recent = hass.states.get(LAST_IMAGE_HFR).attributes["recent_lights"]
    assert {light["target"] for light in recent} == {
        "Dark Shark Nebula", "Lobster & Bubble", "NGC 281", "Wizard Nebula"}


async def test_the_session_start_sensor_is_the_most_recent_local_noon(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, advance, entity_registry
) -> None:
    """Frames at 2026-09-03T21:39 and 2026-09-04T02:35 are one session; a
    midnight rollover would have split the night in two."""
    entity_registry.async_update_entity(SESSION_START, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    await advance("dawn_flats")
    assert dt_util.parse_datetime(hass.states.get(SESSION_START).state) == datetime(
        2026, 9, 3, 12, 0, tzinfo=RIG
    )


@pytest.mark.parametrize(
    "suffix",
    # The 1.4.5 spellings are the point: the pushed family won (§5.2.4), so the
    # survivor keeps the PUSHED entity's unique_id and the polled duplicate is
    # the one that goes.
    ["frame_session_count", "frame_session_integration", "frame_session_avg_hfr",
     "frame_session_min_hfr", "frame_session_max_hfr", "frame_session_avg_stars",
     "frame_last_hfr", "frame_last_stars", "frame_last_mean_adu",
     "frame_last_target", "frame_last_filter", "frame_last_exposure",
     "frame_last_rms"],
)
async def test_a_surviving_session_sensor_keeps_its_1_4_5_unique_id(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    assert _registered(entity_registry, loaded_entry, suffix) is not None


@pytest.mark.parametrize(
    "suffix",
    # The polled duplicates of the collapsed family (§5.2.4)...
    ["image_last_hfr", "image_last_star_count", "image_last_mean_adu",
     "image_count",
     # ...and the pushed family's presentation tail, which the cards compute
     # for themselves in phase D.
     "frame_rolling_avg_hfr", "frame_rolling_avg_stars", "frame_rolling_avg_adu",
     "frame_hfr_trend", "frame_hfr_trend_delta", "frame_per_filter_counts",
     "frame_sparkline_data",
     # Min, Max, Median, StDev and HFRStDev have no `Frame` field: models.py is
     # closed to fields nothing above the seam consumes.
     "frame_last_min_adu", "frame_last_max_adu", "frame_last_median_adu",
     "frame_last_std_dev_adu", "frame_last_hfr_std_dev"],
)
async def test_the_cut_session_sensors_are_not_registered(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    assert _registered(entity_registry, loaded_entry, suffix) is None

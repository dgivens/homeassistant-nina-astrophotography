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

import json
from pathlib import Path

from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from ha.registry import registered
from helpers import state_of

FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip"
FOCUSER_POSITION = "sensor.n_i_n_a_focuser_position"
SEQUENCE_PROGRESS = "sensor.n_i_n_a_sequence_progress"
WAIT_ENDS_AT = "sensor.n_i_n_a_wait_ends_at"
LAST_FRAME_AT = "sensor.n_i_n_a_last_frame_at"
GUIDER_RMS = (
    "sensor.n_i_n_a_guider_rms_total",
    "sensor.n_i_n_a_guider_rms_ra",
    "sensor.n_i_n_a_guider_rms_declination",
)


async def test_the_meridian_sentinel_is_unknown_but_a_real_reading_is_minutes(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """24 is what an untracked mount returns; 12 h is legitimate — a mount
    inside a pier-side window adds 12 — so a "≥12 → unknown" rule is wrong.
    The unit is minutes, which is what a flip warning is written in.
    """
    await advance("imaging_guiding")
    assert float(state_of(hass, FLIP).state) > 0
    await advance("sequence_complete_tracking_off")
    assert state_of(hass, FLIP).state == "unknown"


async def test_the_focuser_position_sensor_carries_a_state_class(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """Long-term statistics: `NumberEntity` has none, and focuser position
    against temperature is the standard temp-comp-slope diagnostic.
    """
    entity_registry.async_update_entity(FOCUSER_POSITION, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert state_of(hass, FOCUSER_POSITION).attributes["state_class"] == "measurement"


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
    it reads RUNNING on an idle rig (§6.2).
    """
    await advance("imaging_guiding")
    assert registered(SENSOR_DOMAIN, entity_registry, loaded_entry, suffix) is None


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
    automation pointing at the old id permanently unavailable.
    """
    await advance("imaging_guiding")
    assert registered(SENSOR_DOMAIN, entity_registry, loaded_entry, suffix) is not None


@pytest.mark.parametrize(
    "state",
    [
        "scheduler_waiting_lost_lock",
        "simulator_guider_calibrating",
        "simulator_guider_connected",
    ],
)
async def test_guide_rms_reads_unknown_unless_the_guider_is_guiding(
    hass: HomeAssistant, config_entry, rig, set_up_at, state: str
) -> None:
    """Outside `Guiding`, N.I.N.A. reports the last run's RMS or 0, and either
    in long-term statistics is guiding that never happened.
    """
    await set_up_at(hass, config_entry, rig, state)
    readings = [state_of(hass, entity_id).state for entity_id in GUIDER_RMS]
    assert readings == ["unknown"] * 3


async def test_guide_rms_reads_the_reported_figures_while_guiding(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    readings = [float(state_of(hass, entity_id).state) for entity_id in GUIDER_RMS]
    assert readings == pytest.approx([0.413, 0.369, 0.184], abs=0.001)


async def test_the_sequence_target_is_the_one_the_scheduler_announced(
    hass: HomeAssistant, loaded_entry
) -> None:
    """A Target Scheduler rig publishes no target in `/sequence/json` — its
    imaging container holds the list internally — so `TS-TARGETSTART` is where
    the name comes from.
    """
    assert state_of(hass, "sensor.n_i_n_a_sequence_target").state == "NGC 281"


async def test_sequence_progress_is_unknown_where_no_node_counts_iterations(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """No node on a Target Scheduler rig counts iterations, so there is no
    percentage to report; inventing one from node statuses would be worse
    (§6.2).
    """
    entity_registry.async_update_entity(SEQUENCE_PROGRESS, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert state_of(hass, SEQUENCE_PROGRESS).state == "unknown"


async def test_the_flip_sensor_publishes_the_offset_a_warning_needs(
    hass: HomeAssistant, loaded_entry
) -> None:
    """`meridian_flip_warning.yaml` reads this attribute by name to place its
    early warning. Rename or drop it and the blueprint silently falls back to
    warning AT the flip.
    """
    flip = state_of(hass, FLIP)

    assert "flip_fires_at_minutes" in flip.attributes


def test_the_blueprint_reads_the_attribute_by_that_name() -> None:
    """The other half of the seam: nothing else connects the two."""
    blueprint = (
        Path(__file__).resolve().parents[2]
        / "blueprints"
        / "automation"
        / "nina_astrophotography"
        / "meridian_flip_warning.yaml"
    )

    assert "flip_fires_at_minutes" in blueprint.read_text(encoding="utf-8")


async def test_the_wait_end_is_published_in_utc_as_home_assistant_stores_it(
    hass: HomeAssistant, config_entry, rig, set_up_at, during_the_scheduler_wait
) -> None:
    """21:05:40 on a UTC−5 rig. A TIMESTAMP sensor stores UTC, so the local
    time the wire sent is only visible here as its instant — which is what a
    `time` trigger with an offset needs.
    """
    await set_up_at(hass, config_entry, rig, "scheduler_waiting")
    assert state_of(hass, WAIT_ENDS_AT).state == "2026-09-16T02:05:40+00:00"


async def test_the_last_frame_timestamp_is_the_newest_frame_of_any_type(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """`now() - last_frame_at` is what a stall looks like, and a dawn flat run
    is the rig working — so this is the 06:26 FLAT, not the 04:25 LIGHT that
    `sensor.last_image_*` reports.
    """
    await advance("dawn_flats")
    assert state_of(hass, LAST_FRAME_AT).state == "2026-09-04T11:26:34+00:00"


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.n_i_n_a_focuser_autofocus_position", 2340.0),
        ("sensor.n_i_n_a_focuser_autofocus_starting_position", 2352.0),
        ("sensor.n_i_n_a_focuser_autofocus_hfr", 1.55229727412562),
        ("sensor.n_i_n_a_focuser_autofocus_starting_hfr", 1.5191799853991006),
        ("sensor.n_i_n_a_focuser_autofocus_temperature", 25.7),
        ("sensor.n_i_n_a_focuser_autofocus_duration", 242.0079444),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
async def test_the_last_autofocus_run_is_published_reading_by_reading(
    hass: HomeAssistant, config_entry, rig, set_up_at, entity_id: str, expected: float
) -> None:
    """Separate sensors, not attributes on one: only a state is recorded, and
    focus drift against temperature is a chart over months.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    assert float(state_of(hass, entity_id).state) == pytest.approx(expected)


@pytest.mark.synthetic
async def test_a_focus_point_between_steps_is_published_where_the_focuser_went(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """2341.5 rounds half to even, as the autofocuser rounds it to move."""
    await set_up_at(hass, config_entry, rig, "autofocus_focus_point_between_steps")
    assert (
        float(state_of(hass, "sensor.n_i_n_a_focuser_autofocus_position").state) == 2342
    )


async def test_the_last_autofocus_time_is_published_in_utc(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """01:10 on a UTC−5 rig. The age of the run is what says a report belongs
    to a previous night, which every other autofocus reading depends on.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    assert (
        state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").state
        == "2026-09-05T06:10:14+00:00"
    )


async def test_the_last_autofocus_carries_what_measured_it(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """HFR is on a different scale per star detector, so a reading is only
    comparable with another taken the same way.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    attributes = state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").attributes

    assert attributes["method"] == "STARHFR"
    assert attributes["star_detector"] == "Hocus Focus"


async def test_the_last_autofocus_publishes_the_curve_a_card_plots(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """A curve is not a statistic, so it rides as an attribute — and it has to
    reach a Lovelace card as plain JSON rows rather than as models.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    curve = state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").attributes["curve"]

    assert [sorted(row) for row in curve] == [["error", "position", "value"]] * 9


async def test_the_last_autofocus_publishes_the_fit_overlay(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """A card cannot re-derive the fitted curves, so they ship parsed — and
    coefficients have to survive as a JSON array, not a Python tuple.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    fits = state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").attributes["fits"]

    assert json.loads(json.dumps(fits))[0]["coefficients"] == pytest.approx(
        [0.0003058854621319121, -1.4293365331583652, 1671.5984427459177]
    )


@pytest.mark.synthetic
async def test_the_last_autofocus_publishes_a_hyperbola_a_card_can_evaluate(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """A card evaluates the curve rather than parsing the equation string."""
    await set_up_at(
        hass, config_entry, rig, "autofocus_hyperbolic_with_a_flat_trend_line"
    )
    fits = state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").attributes["fits"]
    (hyperbolic,) = (fit for fit in fits if fit["name"] == "Hyperbolic")

    assert json.loads(json.dumps(hyperbolic["hyperbola"])) == {
        "x0": 2336.0,
        "y0": -1.0,
        "a": 2.8,
        "b": 48.0,
        "c": 48.0,
        "slope": 0.0,
        "blend": None,
        "blend_width": None,
    }


@pytest.mark.parametrize(
    ("rig_state", "fitted_hfr"),
    [
        # The mean of the trend-line intersection and the quadratic minimum.
        ("imaging_guiding", 1.0932570683996303),
        # A HYPERBOLIC run's focus point is the hyperbola's minimum.
        pytest.param(
            "autofocus_hyperbolic_with_a_flat_trend_line",
            1.8,
            marks=pytest.mark.synthetic,
        ),
    ],
    ids=["trend parabolic", "hyperbolic"],
)
async def test_the_last_autofocus_publishes_the_fitted_hfr_its_fitting_chose(
    hass: HomeAssistant, config_entry, rig, set_up_at, rig_state: str, fitted_hfr: float
) -> None:
    """A card reads this attribute: the `autofocus_fitted_hfr` sensor ships
    disabled, and `minima` carries curves the fitting ignores.
    """
    await set_up_at(hass, config_entry, rig, rig_state)
    attributes = state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").attributes

    assert attributes["fitted_hfr"] == pytest.approx(fitted_hfr)


@pytest.mark.parametrize(
    ("rig_state", "used"),
    [
        (
            "imaging_guiding",
            {"TrendLineIntersection": True, "QuadraticMinimum": True},
        ),
        pytest.param(
            "autofocus_hyperbolic_with_a_flat_trend_line",
            {"TrendLineIntersection": False, "HyperbolicMinimum": True},
            marks=pytest.mark.synthetic,
        ),
    ],
    ids=["trend parabolic", "hyperbolic"],
)
async def test_the_last_autofocus_says_which_minima_its_focus_point_used(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    rig_state: str,
    used: dict[str, bool],
) -> None:
    """Hocus Focus reports the trend-line intersection on every run, and a
    HYPERBOLIC fitting ignores it.
    """
    await set_up_at(hass, config_entry, rig, rig_state)
    minima = state_of(hass, "sensor.n_i_n_a_focuser_last_autofocus").attributes[
        "minima"
    ]

    assert {minimum["name"]: minimum["used"] for minimum in minima} == used


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("entity", "reading"),
    [
        ("sensor.n_i_n_a_site_latitude", "31.5478"),
        ("sensor.n_i_n_a_site_longitude", "-110.2977"),
    ],
    ids=["latitude", "longitude"],
)
async def test_the_site_is_the_one_nina_is_configured_for(
    hass: HomeAssistant, config_entry, rig, set_up_at, entity, reading
) -> None:
    """Where the RIG is, which for a hosted rig is not where Home Assistant is:
    the sky map card and the stall alert's sun both read it.

    Synthetic in `AstrometrySettings`: it is newer in the capture allowlist than
    the corpus is, so the committed projections carry no site.
    """
    await set_up_at(hass, config_entry, rig, "site_configured")

    assert state_of(hass, entity).state == reading


@pytest.mark.parametrize(
    "entity", ["sensor.n_i_n_a_site_latitude", "sensor.n_i_n_a_site_longitude"]
)
async def test_a_profile_with_no_site_reports_no_site(
    hass: HomeAssistant, loaded_entry, entity
) -> None:
    """Readers fall back to Home Assistant's own location on `unknown`, so this
    must not read as a number — 0 is a real place, not a missing site.
    """
    assert state_of(hass, entity).state == "unknown"


async def test_the_autofocus_readings_exist_before_a_run_reports(
    hass: HomeAssistant, loaded_entry
) -> None:
    """The dawn snapshot serves no report. The entities still belong to the
    focuser, and an automation may point at one from the first restart.
    """
    assert (
        state_of(hass, "sensor.n_i_n_a_focuser_autofocus_position").state == "unknown"
    )

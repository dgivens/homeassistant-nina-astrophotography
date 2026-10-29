"""Binary sensors: what was cut, what survived, and the safety polarity.

Every assertion goes through `hass.states` or the entity registry — the
registry for the long tail, which ships disabled and so has no state.
"""

from datetime import timedelta

from homeassistant.components.binary_sensor import DOMAIN as BINARY_SENSOR_DOMAIN
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import NinaRequestError
from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
from ha.registry import registered
from helpers import state_of

AUTOFOCUS_FAILED = "binary_sensor.n_i_n_a_focuser_autofocus_failed"
MONITOR_CONNECTED = "binary_sensor.n_i_n_a_safety_monitor_connected"
SEQUENCER_RUNNING = "binary_sensor.n_i_n_a_sequencer_running"
IMAGING = "binary_sensor.n_i_n_a_imaging"
SCHEDULER_WAITING = "binary_sensor.n_i_n_a_scheduler_waiting"
UNSAFE = "binary_sensor.n_i_n_a_safety_monitor_unsafe"
REACHABLE = "binary_sensor.n_i_n_a_reachable"
MERIDIAN_FLIP = "binary_sensor.n_i_n_a_mount_meridian_flip"


@pytest.mark.parametrize(
    "key",
    [
        # §5.2.1 — availability carries these.
        "camera_connected",
        "mount_connected",
        "focuser_connected",
        "filterwheel_connected",
        "guider_connected",
        "rotator_connected",
        "dome_connected",
        "flatdevice_connected",
        "weather_connected",
        "switch_connected",
        # §5.2.3 — read-only mirrors of a switch, number, select or sensor.
        "camera_cooling_enabled",
        "camera_dew_heater_on",
        "dome_following",
        "rotator_reversed",
        "guider_is_guiding",
        "dome_shutter_open",
        "flatdevice_cover_open",
        "flatdevice_light_on",
        "mount_tracking",
        "livestack_running",
        # No `Slewing` on MountModel: nothing above the seam can compute it.
        "mount_slewing",
        # Not reused: 1.4.5's `_sequence_running` published the imaging
        # heuristic, and `sequencer_running` answers a different question.
        "sequence_running",
    ],
)
async def test_the_cut_binary_sensors_are_not_registered(
    loaded_entry: MockConfigEntry, entity_registry, key: str
) -> None:
    assert registered(BINARY_SENSOR_DOMAIN, entity_registry, loaded_entry, key) is None


@pytest.mark.parametrize(
    "suffix",
    # The four 1.4.5 spellings are the point: a survivor keeps its unique_id,
    # so an upgraded install keeps the registry row and the automations on it.
    [
        "safetymonitor_is_safe",
        "safetymonitor_connected",
        "mount_parked",
        "camera_exposing",
        "mount_at_home",
        "focuser_is_moving",
        "filterwheel_is_moving",
        "rotator_is_moving",
        "rotator_synced",
        "autofocus_failed",
    ],
)
async def test_the_kept_binary_sensors_are_registered(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    """The dome's are absent: the reference rig has none, so §5.2.2 gates them
    out. `test_dome.py` covers them against the simulator's.
    """
    assert (
        registered(BINARY_SENSOR_DOMAIN, entity_registry, loaded_entry, suffix)
        is not None
    )


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
    sky clears and stays silent under cloud.
    """
    await advance(state)
    assert state_of(hass, UNSAFE).state == expected


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
    assert state_of(hass, entity_id).state == expected


async def test_reachable_turns_off_on_the_first_missed_poll(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """Inside the grace, when every other entity still shows its last value."""
    await advance("nina_unreachable")
    assert state_of(hass, REACHABLE).state == "off"


async def test_reachable_stays_available_through_an_outage(
    hass: HomeAssistant, outage, loaded_entry
) -> None:
    await outage()
    assert state_of(hass, REACHABLE).state == "off"


async def test_reachable_turns_off_with_no_grace_to_hold(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig
) -> None:
    """The failure that marks every other entity unavailable must still reach
    the one that reports it.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(config_entry, options={"outage_grace": 0})
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    rig.goto("nina_unreachable")
    await config_entry.runtime_data.coordinator.async_refresh()
    assert state_of(hass, REACHABLE).state == "off"


@pytest.mark.parametrize("answer", ["imaging", "refusal"])
async def test_an_answer_turns_reachable_back_on(
    hass: HomeAssistant, outage, loaded_entry, advance, monkeypatch, answer
) -> None:
    """A refusal is an answer too: the rig is up."""
    await outage()
    if answer == "refusal":
        monkeypatch.setattr(NinaClientV2, "get_equipment", _refusing)
    await advance("imaging")
    assert state_of(hass, REACHABLE).state == "on"


async def _refusing(self):
    raise NinaRequestError("400")


async def test_an_unreachable_rig_still_makes_the_connectivity_sensor_unavailable(
    hass: HomeAssistant, outage, loaded_entry
) -> None:
    """Level 1 is not exempted: nothing is known about the monitor when nothing
    is known about the rig.
    """
    await outage()
    assert state_of(hass, MONITOR_CONNECTED).state == "unavailable"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("sequence_complete_tracking_off", "off"),
        ("imaging_guiding", "on"),
    ],
)
async def test_imaging_follows_activity_and_not_node_status(
    hass: HomeAssistant, advance, state: str, expected: str
) -> None:
    """Frames arriving, never the tree: a sequence executing a wait reads
    RUNNING throughout and takes nothing.
    """
    await advance(state)
    assert state_of(hass, IMAGING).state == expected


@pytest.mark.parametrize(
    ("state", "expected"),
    [("scheduler_waiting", "on"), ("sequence_stopped", "off")],
    ids=["waiting until 21:05", "stopped, with the wait still in the history"],
)
async def test_the_waiting_sensor_clears_when_the_sequence_stops(
    hass: HomeAssistant,
    config_entry,
    rig,
    during_the_scheduler_wait,
    state: str,
    expected: str,
    set_up_at,
) -> None:
    """There is no TS-WAITSTOP: `sequence_stopped` still holds two TS-WAITSTART
    naming 21:05, so a sensor keyed on the newest wait alone would report a
    stopped rig as waiting.
    """
    await set_up_at(hass, config_entry, rig, state)
    assert state_of(hass, SCHEDULER_WAITING).state == expected


async def test_the_sequencer_runs_through_a_wait_that_takes_no_frames(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """The two entities read the two fields, and a wait is where they diverge —
    which is what the shutdown blueprint waits on, and what the meridian
    blueprint gates on.
    """
    await set_up_at(hass, config_entry, rig, "scheduler_waiting")
    assert state_of(hass, SEQUENCER_RUNNING).state == "on"
    assert state_of(hass, IMAGING).state == "off"


@pytest.mark.parametrize(
    "suffix",
    [
        "focuser_is_moving",
        "filterwheel_is_moving",
        "rotator_is_moving",
        "rotator_synced",
    ],
)
async def test_the_long_tail_ships_diagnostic_and_disabled(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    """Gold entity-category / entity-disabled-by-default. The dome's are in
    `test_dome.py`: the reference rig has none.
    """
    row = entity_registry.async_get(
        registered(BINARY_SENSOR_DOMAIN, entity_registry, loaded_entry, suffix)
    )
    assert (row.entity_category, row.disabled_by is not None) == (
        EntityCategory.DIAGNOSTIC,
        True,
    )


async def test_a_device_observed_after_setup_gets_its_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, caplog, set_up_at
) -> None:
    """Equipment routinely connects long after Home Assistant starts, and the
    focuser carries no DeviceId in the partial-connection capture.

    The second refresh pins the other half of the rule: the listener runs on
    every publish, so without the `added` set it would re-add every descriptor.
    The entity registry cannot show that — Home Assistant recognises the
    re-added `unique_id`, refuses the entity and logs it — so the assertion is
    on the log line, which is the only observable difference.
    """
    await set_up_at(hass, config_entry, rig, "partial_equipment_connection")
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
    keeps `binary_sensor.<instance>_sequencer_running` free of a device word.
    """
    entry = entity_registry.async_get(SEQUENCER_RUNNING)
    assert device_registry.async_get(entry.device_id).name == "N.I.N.A."


@pytest.mark.synthetic
async def test_a_rejected_run_raises_the_problem_and_publishes_what_it_was_judged_against(
    hass: HomeAssistant, inside_the_guiding_session, config_entry, rig, set_up_at
) -> None:
    """The failure that costs a night. A rejected run FINISHES — the event
    stream shows a normal pair, so the hung heuristic sees nothing — and
    N.I.N.A. writes its report with no verdict on it. The R² under the
    profile's `RSquaredThreshold` is the only evidence there is (§4.4), and
    `on` alone cannot be acted on without it.
    """
    await set_up_at(hass, config_entry, rig, "autofocus_rejected_on_r_squared")
    problem = state_of(hass, AUTOFOCUS_FAILED)
    assert problem.state == "on"
    assert problem.attributes["reason"] == "rejected"
    assert (
        problem.attributes["r_squared"]
        < problem.attributes["r_squared_threshold"]
        == 0.7
    )


@pytest.mark.parametrize(
    ("clock", "rig_state", "verdict", "attributes"),
    [
        # The same captured report unmodified: 0.971 against a 0.7 threshold.
        # The threshold is published whether or not anything failed: it says how
        # much headroom a passing run had. The sequence's refocus threshold
        # rides along for the autofocus card to flag drift against.
        (
            "inside_the_guiding_session",
            "imaging_guiding",
            "off",
            {
                "reason": None,
                "r_squared_threshold": 0.7,
                "refocus_temperature_delta": 2.0,
            },
        ),
        # There is no autofocus-failed event: the dawn night's eighth
        # AUTOFOCUS-STARTING going unanswered past the timeout is the whole
        # signal. A run that hangs never writes a report, so `last-af` still
        # holds the previous one and the reason says so.
        ("inside_the_dawn_session", "autofocus_timed_out", "on", {"reason": "hung"}),
        # The report file outlives a restart, and with no frozen clock this runs
        # a day or more after the capture, so the same rejected report is
        # older than the session. Believing it would raise a problem every
        # time Home Assistant started.
        (None, "autofocus_rejected_on_r_squared", "off", {}),
    ],
    ids=["fitted well", "unanswered start", "report older than the session"],
)
async def test_the_autofocus_problem_sensor_judges_this_sessions_runs(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    request: pytest.FixtureRequest,
    clock: str | None,
    rig_state: str,
    verdict: str,
    attributes: dict,
) -> None:
    if clock:
        request.getfixturevalue(clock)
    await set_up_at(hass, config_entry, rig, rig_state)
    problem = state_of(hass, AUTOFOCUS_FAILED)
    assert problem.state == verdict
    assert {key: problem.attributes[key] for key in attributes} == attributes


@pytest.fixture
async def before_flip(
    hass: HomeAssistant,
    config_entry,
    rig,
    push,
    set_up_at,
    inside_the_guiding_session,
) -> None:
    """The rig at `imaging_guiding` with a bare `MOUNT-BEFORE-FLIP` pushed,
    fabricated: no capture holds a flip underway.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")
    push({"Event": "MOUNT-BEFORE-FLIP"})
    await hass.async_block_till_done()


@pytest.mark.synthetic
async def test_the_flip_sensor_runs_from_the_flips_start_to_its_end(
    hass: HomeAssistant, before_flip, push, freezer
) -> None:
    """Fabricates the bare `MOUNT-AFTER-FLIP` push."""
    during = state_of(hass, MERIDIAN_FLIP).state
    freezer.tick(timedelta(minutes=2))
    push({"Event": "MOUNT-AFTER-FLIP"})
    await hass.async_block_till_done()
    assert (during, state_of(hass, MERIDIAN_FLIP).state) == ("on", "off")


@pytest.mark.synthetic
async def test_the_flip_slews_when_the_tracked_countdown_reaches_the_window(
    hass: HomeAssistant, before_flip
) -> None:
    """The capture's mount reads 2.1036 h to the flip and its profile a
    15 − 5 minute window, so with the clock frozen N.I.N.A. would wait 116.2
    minutes.
    """
    slews_at = state_of(hass, MERIDIAN_FLIP).attributes["slews_at"]
    waits = slews_at - dt_util.utcnow()
    assert waits == timedelta(hours=2.1036111110833335) - timedelta(minutes=10)


@pytest.mark.synthetic
async def test_the_slew_estimate_survives_the_wait_with_tracking_off(
    hass: HomeAssistant, config_entry, rig, before_flip, freezer
) -> None:
    """A poll during the wait reads no countdown, and must not lose the one
    read before it.
    """
    placed = state_of(hass, MERIDIAN_FLIP).attributes["slews_at"]
    freezer.tick(timedelta(seconds=10))
    rig.goto("waiting_to_flip")
    await config_entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    assert state_of(hass, MERIDIAN_FLIP).attributes["slews_at"] == placed


@pytest.mark.synthetic
async def test_a_flip_that_lapsed_without_its_end_does_not_hold_the_next(
    hass: HomeAssistant, config_entry, before_flip, push, freezer
) -> None:
    """The first flip's 116-minute wait and its hour of steps pass with no
    `MOUNT-AFTER-FLIP`, so the next flip must be placed from a fresh reading.
    """
    freezer.tick(timedelta(hours=3))
    await config_entry.runtime_data.coordinator.async_refresh()
    push({"Event": "MOUNT-BEFORE-FLIP"})
    await hass.async_block_till_done()
    assert state_of(hass, MERIDIAN_FLIP).attributes["slews_at"] is not None

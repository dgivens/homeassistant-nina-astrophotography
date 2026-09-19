"""wire → models. Every sentinel, timezone and quirk dies in this module."""
from datetime import timedelta

from helpers import load_fixture as load
from nina_astrophotography.api.v2.mapper import (
    map_equipment_info,
    map_event,
    map_flat_device,
    map_flats_status,
    map_frame,
    map_guider,
    map_last_autofocus,
    map_livestack_status,
    map_mount,
    map_profile,
    map_sequence,
    map_switch,
    nan_to_none,
    rig_utc_offset,
)
import pytest


@pytest.mark.parametrize(
    ("value", "expected"),
    [("NaN", None), ("nan", None), (0.0, 0.0), (None, None), ("Sidereal", "Sidereal"),
     (float("nan"), None)],
)
def test_the_blanket_nan_rule(value, expected) -> None:
    """.NET serializes double.NaN as a JSON string, and json.loads also accepts
    a bare NaN literal as a float. No allowlist.
    """
    assert nan_to_none(value) == expected


def test_disconnected_devices_are_present_but_not_connected() -> None:
    snapshot = map_equipment_info(load("restart_equipment_partial_connect.json"))
    assert snapshot.mount is not None
    assert snapshot.mount.connected is False


def test_a_disconnected_device_drops_its_registry_metadata() -> None:
    """The wire omits DeviceId/Name/DisplayName rather than nulling them; the
    coordinator latches "ever observed" from this, so the mapper must not invent.
    """
    snapshot = map_equipment_info(load("restart_equipment_partial_connect.json"))
    assert snapshot.mount.meta.device_id is None


def test_a_block_absent_from_the_wire_maps_to_none() -> None:
    """All eleven blocks are always emitted; a missing one is not a device."""
    assert map_equipment_info({}).camera is None


def test_nan_fields_map_to_none_not_zero() -> None:
    """Nineteen fields are "NaN" with weather, mount, focuser and dome down."""
    snapshot = map_equipment_info(load("restart_equipment_partial_connect.json"))
    assert snapshot.weather is not None
    assert all(v is None for v in snapshot.weather.channels.values())


def test_tracking_mode_is_mapped_verbatim() -> None:
    """The wire's own spelling, never the spec's enum ('Siderial')."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    # /equipment/info nests eleven device blocks under Camera, Dome, FilterWheel,
    # FlatDevice, Focuser, Guider, Mount, Rotator, SafetyMonitor, Switch and
    # WeatherData. The per-device /equipment/<x>/info captures are a BARE device
    # object — do not feed them to map_equipment_info.
    assert snapshot.mount.tracking_mode == "Stopped"


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("tracking", "flip", "expected"),
    [
        (False, 24, None),      # the dawn capture verbatim: tracking off
        (True, 24, None),       # the literal sentinel, whatever TrackingEnabled says
        # A mount inside the pier-side window that adds 12 h: legitimate,
        # not "unknown".
        (True, 12, 12.0),
        (True, 1.5, 1.5),
        # Over 24 is not a value the calculation can produce — it subtracts 24
        # from whatever reaches it — and it still passes through: the rule is
        # the literal 24 and nothing else.
        (True, 24.08, 24.08),
    ],
)
def test_only_the_literal_24_sentinel_or_tracking_off_nulls_the_flip_time(
    tracking, flip, expected
) -> None:
    """24 h to flip means tracking is off, not 'a day away' (§11). The sentinel
    is exactly 24, and every other reading passes through — the mapper never
    infers one from a range. No capture has a tracking mount, so the dawn mount
    is re-timed.
    """
    wire = load("dawn_equipment_info.json")["Mount"]
    mount = map_mount({**wire, "TrackingEnabled": tracking, "TimeToMeridianFlip": flip})
    assert mount.time_to_meridian_flip == expected


def test_flat_panel_range_comes_from_the_driver() -> None:
    """MaxBrightness 4096 on this panel; 255 on an Alnitak. Never hardcode."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert snapshot.flat_device.max_brightness == 4096


def test_the_per_device_endpoint_shape_maps_too() -> None:
    """dawn_flatdevice_connected.json is a bare FlatDeviceInfo, not a snapshot."""
    panel = map_flat_device(load("dawn_flatdevice_connected.json"))
    assert panel.max_brightness == 4096


@pytest.mark.parametrize(
    ("device", "field", "expected"),
    [
        ("camera", "gain", 100),
        ("camera", "binning_modes", ("1x1", "2x2", "3x3", "4x4")),
        ("camera", "target_temperature", 20.0),
        ("camera", "battery", None),            # Battery -1 with HasBattery false
        # Per-camera, and narrower than the 0-100 a range-free reading suggests.
        ("camera", "usb_limit_min", 40),
        ("camera", "usb_limit_max", 100),
        ("mount", "epoch", "JNOW"),
        ("mount", "tracking_modes", ("Sidereal", "Lunar", "Solar", "Stopped")),
        ("focuser", "position", 2332),
        ("filter_wheel", "selected_filter", "R"),
        ("filter_wheel", "available_filters", ("L", "R", "G", "B", "H", "O", "S")),
        ("guider", "state", None),              # no capture has a connected guider
        ("rotator", "synced", True),
        ("dome", "azimuth", None),              # "NaN" on a dome that never existed
        ("dome", "shutter_status", None),       # ShutterNone from a disconnected driver
        ("flat_device", "cover_state", "Closed"),
        ("safety_monitor", "is_safe", False),
    ],
)
def test_each_device_block_maps_its_readings(device, field, expected) -> None:
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert getattr(getattr(snapshot, device), field) == expected


@pytest.mark.parametrize("field", ["position", "step_size", "temperature"])
def test_a_disconnected_device_reports_no_readings(field) -> None:
    """A disconnected driver answers Position 0 / StepSize 0: artefacts of the
    driver template, not readings. Only `connected`, `meta` and the capability
    flags survive a Connected: false block.
    """
    focuser = map_equipment_info(load("restart_equipment_partial_connect.json")).focuser
    assert getattr(focuser, field) is None


@pytest.mark.synthetic
def test_a_zero_plate_scale_is_no_reading_even_on_a_connected_guider() -> None:
    """No capture has a connected guider, so the dawn guider is re-flagged."""
    wire = load("dawn_equipment_info.json")["Guider"]
    assert map_guider({**wire, "Connected": True}).pixel_scale is None


def test_switch_channels_carry_their_writability_and_range() -> None:
    channel = map_equipment_info(load("dawn_equipment_info.json")).switch_device.channels[0]
    assert (channel.name, channel.writable, channel.binary) == ("Flat Panel", True, True)


@pytest.mark.synthetic
def test_a_disconnected_switch_keeps_its_channels_and_loses_only_their_values() -> None:
    """Channel names and ranges are the device's capability, not a reading, so
    they survive a disconnect the way every other block's option lists do. No
    capture has a disconnected switch, so the dawn block is re-flagged.
    """
    wire = load("dawn_equipment_info.json")["Switch"]
    channel = map_switch({**wire, "Connected": False}).channels[0]
    assert (channel.name, channel.maximum, channel.value) == ("Flat Panel", 1.0, None)


def test_the_channel_map_is_the_thirteen_channels_not_average_period() -> None:
    """AveragePeriod is a driver setting, not a reading (§5.2.2)."""
    weather = map_equipment_info(load("weather_source_openmeteo.json")).weather
    assert sorted(weather.channels) == [
        "cloud_cover", "dew_point", "humidity", "pressure", "rain_rate",
        "sky_brightness", "sky_quality", "sky_temperature", "star_fwhm",
        "temperature", "wind_direction", "wind_gust", "wind_speed"]


def test_a_channel_this_source_reports_keeps_its_reading() -> None:
    weather = map_equipment_info(load("weather_source_openmeteo.json")).weather
    assert weather.channels["cloud_cover"] == 14


def test_the_rig_offset_comes_from_the_mounts_own_clock() -> None:
    """The client caches it so naive log-scraped event times can be resolved."""
    assert rig_utc_offset(load("dawn_equipment_info.json")) == timedelta(hours=-5)


def test_the_rig_offset_falls_back_to_the_gap_between_the_two_clocks() -> None:
    """`Now` carries the offset on this build; the pair still states it if a
    driver ever reports `Now` naive.
    """
    wire = load("dawn_equipment_info.json")
    clock = wire["Mount"]["Coordinates"]["DateTime"]
    clock["Now"] = clock["Now"].removesuffix("-05:00")
    assert rig_utc_offset(wire) == timedelta(hours=-5)


def test_the_rig_offset_is_unknown_without_a_mount_clock() -> None:
    assert rig_utc_offset(load("restart_equipment_partial_connect.json")) is None


@pytest.fixture
def first_flat() -> dict:
    return next(f for f in load("dawn_image_history_with_flats.json")
                if f["ImageType"] == "FLAT")


@pytest.fixture
def first_light() -> dict:
    return next(f for f in load("dawn_image_history_with_flats.json")
                if f["ImageType"] == "LIGHT")


def test_calibration_frames_lose_their_hfr_but_keep_their_adu(first_flat) -> None:
    """Keyed on ImageType, which is on both paths. HFR 0 is a reliable
    calibration signal but not a sufficient one — see the clouded-light test.
    """
    frame = map_frame(first_flat, generation="g1")
    assert (frame.hfr, frame.stars) == (None, None)
    assert frame.mean is not None


def test_the_adu_range_is_mapped_from_min_and_max(first_light) -> None:
    frame = map_frame(first_light, generation="g1")
    assert (frame.min, frame.max) == (first_light["Min"], first_light["Max"])


@pytest.mark.synthetic
def test_a_nan_adu_range_is_none() -> None:
    """Min/Max are ordinary numeric fields, so the .NET NaN-as-string quirk
    applies to them the same as Mean and Median. No captured frame carries
    it; constructed deliberately.
    """
    wire = {"ImageType": "LIGHT", "Date": "2026-09-04T02:00:00.000-05:00",
            "Filename": "frame_9998.fits", "Min": "NaN", "Max": "NaN"}
    frame = map_frame(wire, generation="g1")
    assert (frame.min, frame.max) == (None, None)


@pytest.mark.synthetic
@pytest.mark.parametrize("image_type", ["DARK", "BIAS", "DARKFLAT"])
def test_every_calibration_type_is_stripped_like_a_flat(first_flat, image_type) -> None:
    """Calibration is the explicit set FLAT/DARK/BIAS/DARKFLAT. The corpus has
    flats and one dark push; the flat is re-typed for the rest.
    """
    frame = map_frame({**first_flat, "ImageType": image_type}, generation="g1")
    assert (frame.hfr, frame.stars) == (None, None)


def test_light_frames_keep_their_hfr(first_light) -> None:
    assert map_frame(first_light, generation="g1").hfr is not None


@pytest.mark.synthetic
def test_a_snapshot_is_not_calibration_and_keeps_its_readings(first_light) -> None:
    """Only the calibration set loses readings; a SNAPSHOT is of the sky. No
    capture holds one, so a light is re-typed.
    """
    frame = map_frame({**first_light, "ImageType": "SNAPSHOT"}, generation="g1")
    assert (frame.hfr, frame.stars) == (first_light["HFR"], first_light["Stars"])


def test_the_guide_rms_is_the_arcsecond_figure_in_the_rms_text(first_light) -> None:
    """RmsText is 'Tot: 0.26 (0.42")' — guide-camera pixels first, then
    arcseconds. Pixels are not comparable between rigs; arcseconds are.
    """
    assert map_frame(first_light, generation="g1").rms_arcsec == 0.42


def test_a_calibration_frame_has_no_guide_rms(first_flat) -> None:
    """A flat reports 'Tot: 0.00 (0.00")' because the guider is stopped. Kept as
    0.0 it reads as perfect guiding across 67 of this session's 122 frames.
    """
    assert map_frame(first_flat, generation="g1").rms_arcsec is None


@pytest.mark.synthetic
def test_an_unguided_light_has_no_guide_rms(first_light) -> None:
    """Zero total RMS is no guiding, not perfect guiding — the same rule as
    HFR 0 on a light. Every captured light was guided, so one is re-texted.
    """
    frame = map_frame({**first_light, "RmsText": 'Tot: 0.00 (0.00")'}, generation="g1")
    assert frame.rms_arcsec is None


def test_a_frame_of_unknown_type_keeps_the_readings_it_has(first_light) -> None:
    """The type decides only what is dropped. No captured frame is missing its
    ImageType, so a captured light is stripped of it deliberately.
    """
    frame = map_frame({k: v for k, v in first_light.items() if k != "ImageType"},
                      generation="g1")
    assert (frame.hfr, frame.stars, frame.rms_arcsec) == (
        first_light["HFR"], first_light["Stars"], 0.42)


def test_an_unparsable_rms_text_is_no_reading(first_light) -> None:
    assert map_frame({**first_light, "RmsText": "n/a"}, generation="g1").rms_arcsec is None


@pytest.mark.synthetic
def test_a_clouded_light_keeps_its_zero_star_count() -> None:
    """A light through thick cloud reports HFR 0 with Stars 0, and "zero stars
    detected" is the most diagnostic reading a clouded-out sub has. Keying
    calibration on HFR == 0 alone would classify it as a flat and discard it.

    The corpus cannot show this: no captured LIGHT has HFR 0, and the minimum
    star count across the 55 lights is 3758. Constructed deliberately.
    """
    clouded = {"ImageType": "LIGHT", "HFR": 0.0, "Stars": 0, "Mean": 612.0,
               "Date": "2026-09-04T02:00:00.000-05:00",
               "Filename": "frame_9999.fits", "ExposureTime": 300.0}
    frame = map_frame(clouded, generation="g1")
    assert frame.stars == 0
    assert frame.hfr is None


def test_a_dark_is_calibration_even_though_its_star_count_is_positive() -> None:
    """The captured dark reports HFR 0.0 and Stars 1 — keying on Stars == -1
    would misclassify every dark.
    """
    push = load("live_image_save_push.json")["ImageStatistics"]
    frame = map_frame(push, generation="g1")
    assert frame.hfr is None and frame.stars is None


def test_a_frame_taken_with_no_filter_names_none() -> None:
    """The dark push carries Filter "" — no filter is not a filter named ""."""
    push = load("live_image_save_push.json")["ImageStatistics"]
    assert map_frame(push, generation="g1").filter_name is None


def _first_event(name: str) -> dict:
    """The first `/event-history` entry of that name from the dawn night: an
    offset-aware mediator IMAGE-SAVE (21:26:56-05:00), a naive-UTC
    TS-NEWTARGETSTART (02:15:32) and a naive-local ERROR-PLATESOLVE (21:54:26).
    """
    return next(e for e in load("dawn_event_history.json") if e["Event"] == name)


def test_mediator_event_times_are_offset_aware_local() -> None:
    event = map_event(_first_event("IMAGE-SAVE"), generation="g1")
    assert event.time.utcoffset() == timedelta(hours=-5)


def test_ts_event_times_are_naive_utc() -> None:
    """Two naive formats, indistinguishable by shape — key on the event name."""
    event = map_event(_first_event("TS-NEWTARGETSTART"), generation="g1")
    assert event.time.utcoffset() == timedelta(0)


def test_log_scraped_event_times_are_local_and_still_offset_aware() -> None:
    """Left naive, the first ERROR-PLATESOLVE to land beside 600 offset-aware
    events crashes fold()'s sorted iteration with "can't compare offset-naive
    and offset-aware datetimes". Every NinaEvent.time is aware.
    """
    event = map_event(_first_event("ERROR-PLATESOLVE"), generation="g1",
                      rig_offset=timedelta(hours=-5))
    assert event.time.utcoffset() == timedelta(hours=-5)


def test_a_naive_local_time_falls_back_to_utc_before_the_offset_is_known() -> None:
    """The first poll can arrive after the first event. Ordering must always be
    defined; replay corrects it once the mount's clock has been read.
    """
    event = map_event(_first_event("ERROR-PLATESOLVE"), generation="g1")
    assert event.time.utcoffset() == timedelta(0)


def test_every_event_class_sorts_together() -> None:
    """The property that matters: one comparable ordering across all three."""
    offset = timedelta(hours=-5)
    events = [map_event(_first_event(name), "g1", rig_offset=offset)
              for name in ("IMAGE-SAVE", "TS-NEWTARGETSTART", "ERROR-PLATESOLVE")]
    # In UTC: TS-NEWTARGETSTART 02:15:32 is already UTC; IMAGE-SAVE 21:26:56-05:00
    # is 02:26:56; ERROR-PLATESOLVE 21:54:26 local is 02:54:26. Reading the
    # wall-clock strings as written puts the TS-* event last instead of first.
    assert [e.name for e in sorted(events, key=lambda e: e.time)] == [
        "TS-NEWTARGETSTART", "IMAGE-SAVE", "ERROR-PLATESOLVE"]


def test_a_socket_image_save_is_timed_by_the_frame_it_carries() -> None:
    """The live socket IMAGE-SAVE carries ImageStatistics and no Time (§3.4)."""
    event = map_event(load("live_image_save_push.json"), generation="g1")
    assert event.frame is not None
    assert event.time == event.frame.date


@pytest.mark.parametrize("wire", [{"Event": "SEQUENCE-FINISHED"},
                                  {"Event": "SEQUENCE-FINISHED", "Time": "07:06"}])
def test_an_event_with_no_usable_time_and_no_frame_is_not_an_event(wire) -> None:
    with pytest.raises(ValueError):
        map_event(wire, generation="g1")


def test_event_payloads_keep_their_scalars_and_drop_the_empty_coordinates() -> None:
    """TS-* payloads carry "Coordinates": {"RA": [], …} — empty arrays where
    scalars belong. Nothing above the seam can use them.
    """
    wire = next(e for e in load("dawn_event_history.json")
                if e["Event"] == "TS-TARGETSTART")
    data = map_event(wire, generation="g1").data
    assert data["TargetName"] == "Lobster & Bubble"
    assert "Coordinates" not in data


def test_the_sequence_root_is_synthetic_and_holds_the_global_triggers() -> None:
    """/sequence/json answers a LIST of top-level nodes, the first of which is a
    bare {"GlobalTriggers": [...]} with no Name or Status of its own.
    """
    root = map_sequence(load("dawn_sequence_complete.json"))
    assert root.name == "Sequence"
    assert root.children[0].name == "GlobalTriggers"


def test_sequence_leaves_carry_their_status() -> None:
    root = map_sequence(load("dawn_sequence_complete.json"))
    start = next(c for c in root.children if c.name == "Start_Container")
    assert start.status == "FINISHED"


def test_a_sequence_that_did_not_serialize_is_not_a_tree() -> None:
    """'Sequence is not initialized' answers Response: "" (§3.5)."""
    assert map_sequence(load("startup_sequence_not_initialized.json")) is None


def test_idle_flat_wizard_iterations_are_not_a_count() -> None:
    """-1 through a completed Target Scheduler flat run — confirmed."""
    status = map_flats_status(load("dawn_flats_status_idle.json"))
    assert status.total_iterations is None
    assert status.completed_iterations is None


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        # The captured shape: Response is the bare status string.
        (load("imaging_guiding_livestack_status.json"), (True, "Running")),
        pytest.param("stopped", (False, "stopped"), marks=pytest.mark.synthetic),
        # The spec's documented shape, kept because the enum is lowercase there
        # and a live rig has answered "Stopped".
        pytest.param({"Status": "Running"}, (True, "Running"),
                     marks=pytest.mark.synthetic),
        pytest.param({"Status": "STOPPED"}, (False, "STOPPED"),
                     marks=pytest.mark.synthetic),
        # The plugin may not be installed; the empty state is "", not "None".
        pytest.param({}, (False, ""), marks=pytest.mark.synthetic),
    ],
    ids=["captured bare string", "bare string stopped", "spec dict running",
         "spec dict stopped", "absent"],
)
def test_livestack_status_reads_both_wire_shapes(wire, expected) -> None:
    status = map_livestack_status(wire)
    assert (status.running, status.raw_state) == expected


def test_the_profile_allowlist_maps_from_its_nested_sections() -> None:
    """/profile/show is captured as an allowlist projection and never as a
    fixture — a full dump held a live WeatherUnderground key (§8.3).
    """
    profile = map_profile({
        "TelescopeSettings": {"FocalLength": 500},
        "CameraSettings": {"PixelSize": 3.76},
        "FocuserSettings": {"AutoFocusTimeoutSeconds": 600, "RSquaredThreshold": 0.9},
        "MeridianFlipSettings": {"MinutesAfterMeridian": 5,
                                 "MaxMinutesAfterMeridian": 15,
                                 "UseSideOfPier": True},
    })
    assert profile == type(profile)(
        focal_length=500.0, pixel_size=3.76, autofocus_timeout_seconds=600.0,
        r_squared_threshold=0.9, min_minutes_after_meridian=5.0,
        max_minutes_after_meridian=15.0, use_side_of_pier=True)


def test_an_absent_profile_section_is_no_reading() -> None:
    assert map_profile({}).focal_length is None


def test_the_autofocus_reports_worst_fit_is_what_a_threshold_judges() -> None:
    """N.I.N.A. computes an R² only for the fittings a run actually used and
    sends `"NaN"` for the rest — this TRENDPARABOLIC run carries a `"NaN"`
    Hyperbolic — so the minimum of what survives the `"NaN"` rule is the worst
    fit computed, and no fitting-to-R² table has to be guessed at.
    """
    report = map_last_autofocus(load("imaging_guiding_last_af.json"))
    assert report.r_squared == pytest.approx(0.9710548595560263)


def test_an_autofocus_report_carries_where_it_left_the_focuser() -> None:
    """`CalculatedFocusPoint` is the fitted minimum, not the run's start."""
    report = map_last_autofocus(load("imaging_guiding_last_af.json"))
    assert (report.position, report.filter_name) == (2340, "L")


def test_the_autofocus_hfr_is_the_sweeps_lowest_measured_point() -> None:
    """`CalculatedFocusPoint.Value` is not an achieved HFR: under a `TREND*`
    fitting N.I.N.A. sets it to the mean of the trendline intersection and the
    quadratic minimum, which here reads 1.09 against a best measured 1.55. The
    measured point is what compares run to run and across fittings.
    """
    report = map_last_autofocus(load("imaging_guiding_last_af.json"))
    assert report.hfr == pytest.approx(1.55229727412562)
    assert report.fitted_hfr == pytest.approx(1.0932570683996303)


def test_an_autofocus_report_carries_where_the_run_started() -> None:
    """`InitialFocusPoint` is where the focuser was before the run — the other
    end of the move, without which the run's size is unknowable.
    """
    report = map_last_autofocus(load("imaging_guiding_last_af.json"))
    assert report.initial_position == 2352
    assert report.initial_hfr == pytest.approx(1.5191799853991006)


def test_an_autofocus_runs_duration_is_seconds() -> None:
    """`Duration` is a .NET TimeSpan string, not a number: the overhead a run
    costs a session is only comparable once it is seconds.
    """
    report = map_last_autofocus(load("imaging_guiding_last_af.json"))
    assert report.duration_seconds == pytest.approx(242.0079444)


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("00:04:02", 242.0),             # a run that lands on a whole second
        ("1.02:03:04", 93784.0),         # days, which .NET writes with a dot
        ("", None),
        ("4 minutes", None),
        (242, None),                     # never observed as a number
    ],
)
def test_the_timespan_forms_a_duration_can_arrive_in(duration, expected) -> None:
    """Fabricates `Duration` alone; every observed capture carries the
    `hh:mm:ss.fffffff` form, and the day-prefixed form is .NET's own.
    """
    report = map_last_autofocus({"Duration": duration})
    assert report.duration_seconds == (
        None if expected is None else pytest.approx(expected))


@pytest.mark.synthetic
@pytest.mark.parametrize("method", ["CONTRASTDETECTION", "ContrastDetection", "MYSTERY"])
def test_only_a_star_hfr_run_reports_pixels(method: str) -> None:
    """Fabricates `Method`: the corpus is all STARHFR. CONTRASTDETECTION
    measures a contrast score, so its focus points are not pixels — publishing
    them as HFR would put two different quantities in one statistic — and a
    method nobody here has seen gets the same treatment rather than the
    benefit of the doubt. The positions survive: a step is a step.
    """
    wire = dict(load("imaging_guiding_last_af.json"), Method=method)
    report = map_last_autofocus(wire)
    assert (report.hfr, report.fitted_hfr, report.initial_hfr) == (None, None, None)
    assert (report.position, report.initial_position) == (2340, 2352)


@pytest.mark.synthetic
def test_a_focus_point_of_zero_is_no_measurement() -> None:
    """Fabricates `InitialFocusPoint`: N.I.N.A. leaves it at 0 where the
    pre-sweep measurement found no stars, which is its own `initialHFR != 0`
    guard. A star has a size, and a 0 in a MEASUREMENT sensor is what corrupts
    a long-term statistic.
    """
    wire = dict(load("imaging_guiding_last_af.json"),
                InitialFocusPoint={"Position": 2352, "Value": 0, "Error": 0})
    assert map_last_autofocus(wire).initial_hfr is None


def test_the_autofocus_curve_ascends_in_focuser_position() -> None:
    """A plot needs monotonic x, and the report does not state its own order."""
    curve = map_last_autofocus(load("imaging_guiding_last_af.json")).curve
    assert [point.position for point in curve] == [
        2212, 2247, 2282, 2317, 2352, 2387, 2422, 2457, 2492]


def test_an_autofocus_curve_point_carries_its_spread() -> None:
    """`Error` is how widely star sizes varied across that frame, which
    N.I.N.A. draws as the point's error bar.
    """
    curve = map_last_autofocus(load("imaging_guiding_last_af.json")).curve
    assert curve[4].error == pytest.approx(0.10801730574556397)


@pytest.fixture
def failed_sweep_point():
    """A two-point sweep whose first frame measured nothing. Fabricated —
    every captured sweep is complete — and marked `synthetic` at each use.
    """
    return map_last_autofocus(dict(
        load("imaging_guiding_last_af.json"),
        MeasurePoints=[{"Position": 2317, "Value": 0, "Error": 0},
                       {"Position": 2352, "Value": 1.5, "Error": 0.1}]))


@pytest.mark.synthetic
def test_a_position_the_sweep_measured_nothing_at_stays_on_the_curve(
    failed_sweep_point,
) -> None:
    """Deleting the row would take its position off the axis, and a chart
    would then draw a straight chord across the failure instead of breaking
    the line where the sweep actually lost a frame.
    """
    assert [(p.position, p.value) for p in failed_sweep_point.curve] == [
        (2317, None), (2352, 1.5)]


@pytest.mark.synthetic
def test_only_the_positions_that_measured_something_are_counted(
    failed_sweep_point,
) -> None:
    """`measured_points` is what the run got; the curve's length is what it
    paid for, failures included.
    """
    assert (failed_sweep_point.measured_points,
            len(failed_sweep_point.curve)) == (1, 2)


@pytest.mark.synthetic
def test_a_failed_sweep_point_is_not_the_best_hfr(failed_sweep_point) -> None:
    """The headline HFR is a minimum over the curve, so a frame that measured
    nothing must not read as the sharpest focus the run achieved.
    """
    assert failed_sweep_point.hfr == pytest.approx(1.5)


@pytest.mark.synthetic
def test_a_sweep_point_without_a_position_cannot_be_plotted() -> None:
    """Fabricates a positionless entry. A position is the x axis: a row
    lacking one has nowhere to go on the chart, unlike a failed measurement.
    """
    wire = dict(load("imaging_guiding_last_af.json"),
                MeasurePoints=[{"Value": 1.7, "Error": 0.1},
                               {"Position": 2352, "Value": 1.5, "Error": 0.1}])
    assert [p.position for p in map_last_autofocus(wire).curve] == [2352]


@pytest.mark.synthetic
def test_a_report_without_a_sweep_has_an_empty_curve() -> None:
    """Fabricates a report with no `MeasurePoints`. An absent sweep and an
    empty one draw the same, so this is `()` rather than None — a chart should
    not have to test for two kinds of nothing.
    """
    wire = load("imaging_guiding_last_af.json")
    del wire["MeasurePoints"]
    report = map_last_autofocus(wire)
    assert report.curve == ()
    assert (report.hfr, report.measured_points) == (None, None)


def test_a_fitted_curve_is_published_as_coefficients() -> None:
    """N.I.N.A. writes the fit as an equation STRING. A chart needs to evaluate
    it, and parsing it once here beats parsing it in JavaScript on every
    render.
    """
    quadratic = next(f for f in map_last_autofocus(
        load("imaging_guiding_last_af.json")).fits if f.name == "Quadratic")
    assert quadratic.coefficients == pytest.approx(
        (0.0003058854621319121, -1.4293365331583652, 1671.5984427459177))


def test_each_fit_keeps_its_own_r_squared() -> None:
    """`AutoFocusReport.r_squared` is the worst fit of the run, which is right
    for a threshold and cannot label an individual line in a chart legend.
    """
    fits = {f.name: f.r_squared
            for f in map_last_autofocus(load("imaging_guiding_last_af.json")).fits}
    assert fits == pytest.approx({"Quadratic": 0.9710548595560263,
                                  "LeftTrend": 0.9902518159347956,
                                  "RightTrend": 0.9998991212499581})


def test_a_fitting_this_run_did_not_use_is_not_published() -> None:
    """N.I.N.A. carries one entry per fitting it knows and an empty equation
    for the ones it did not run, which is no curve to draw.
    """
    names = [f.name for f in map_last_autofocus(
        load("imaging_guiding_last_af.json")).fits]
    assert "Hyperbolic" not in names and "Gaussian" not in names


def test_the_fit_minima_are_read_by_the_names_the_rig_uses() -> None:
    """The second entry is named after whichever curve was fitted — the spec
    calls it `HyperbolicMinimum`, this TRENDPARABOLIC run calls it
    `QuadraticMinimum` — so keying on a literal name would find nothing.
    """
    minima = map_last_autofocus(load("imaging_guiding_last_af.json")).minima
    assert [(m.name, m.position) for m in minima] == [
        ("TrendLineIntersection", 2344), ("QuadraticMinimum", 2336)]


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("equation", "expected"),
    [
        ("y = 2 * x^2 + -3 * x + 4", (2.0, -3.0, 4.0)),
        ("y = -0.5 * x + 1.25", (-0.5, 1.25)),
        ("y = 3 * x^3 + 1", (3.0, 0.0, 0.0, 1.0)),   # zero-filled, not skipped
        ("y = 1E+05 * x + 2", (100000.0, 2.0)),      # the split must not be on "+"
        ("", None),
        ("y = a / (x - b)", None),                   # no hyperbolic form observed
    ],
)
def test_the_equation_forms_a_fit_can_arrive_in(equation, expected) -> None:
    """Fabricates `Fittings.Quadratic`: the corpus carries only a quadratic and
    two trend lines, and a hyperbolic or gaussian run has never been captured,
    so anything that is not a polynomial yields no coefficients rather than a
    guess.
    """
    wire = dict(load("imaging_guiding_last_af.json"),
                Fittings={"Quadratic": equation})
    fits = map_last_autofocus(wire).fits
    if expected is None:
        assert [f.coefficients for f in fits] in ([], [None])
    else:
        assert fits[0].coefficients == pytest.approx(expected)


def test_a_rig_that_has_never_run_an_autofocus_has_no_report() -> None:
    assert map_last_autofocus({}) is None

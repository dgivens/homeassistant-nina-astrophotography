"""wire → models. Every sentinel, timezone and quirk dies in this module."""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from nina_astrophotography.api.v2.mapper import (
    map_equipment_info,
    map_event,
    map_frame,
    map_flats_status,
    map_livestack_status,
    map_profile,
    map_sequence,
    nan_to_none,
    rig_offset,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str):
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    document.pop("_meta", None)
    return document["Response"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("NaN", None), ("nan", None), (0.0, 0.0), (None, None), ("Sidereal", "Sidereal"),
     (float("nan"), None)],
)
def test_the_blanket_nan_rule(value, expected) -> None:
    """.NET serializes double.NaN as a JSON string, and json.loads also accepts
    a bare NaN literal as a float. No allowlist."""
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


def test_tracking_mode_is_the_wire_spelling_not_the_specs() -> None:
    """The spec says 'Siderial'; the wire says 'Sidereal'."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    # /equipment/info nests eleven device blocks under Camera, Dome, FilterWheel,
    # FlatDevice, Focuser, Guider, Mount, Rotator, SafetyMonitor, Switch and
    # WeatherData. The per-device /equipment/<x>/info captures are a BARE device
    # object — do not feed them to map_equipment_info.
    assert snapshot.mount.tracking_mode in {"Sidereal", "Lunar", "Solar", "King",
                                            "Stopped", None}


def test_the_meridian_24_sentinel_maps_to_none() -> None:
    """24 h to flip means tracking is off, not 'a day away' (§11)."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert snapshot.mount.tracking_enabled is False
    assert snapshot.mount.time_to_meridian_flip is None


def test_a_tracking_mount_keeps_a_twelve_hour_flip_time() -> None:
    """12 h is legitimate — it means "just flipped" — so "≥12 → unknown" would
    be wrong. No capture has a tracking mount, so the fixture is retimed."""
    from nina_astrophotography.api.v2.mapper import map_mount

    wire = load("dawn_equipment_info.json")["Mount"]
    mount = map_mount({**wire, "TrackingEnabled": True, "TimeToMeridianFlip": 12})
    assert mount.time_to_meridian_flip == 12


def test_flat_panel_range_comes_from_the_driver() -> None:
    """MaxBrightness 4096 on this panel; 255 on an Alnitak. Never hardcode."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert snapshot.flat_device.max_brightness == 4096


def test_the_per_device_endpoint_shape_maps_too() -> None:
    """dawn_flatdevice_connected.json is a bare FlatDeviceInfo, not a snapshot."""
    from nina_astrophotography.api.v2.mapper import map_flat_device

    panel = map_flat_device(load("dawn_flatdevice_connected.json"))
    assert panel.max_brightness == 4096


@pytest.mark.parametrize(
    ("device", "field", "expected"),
    [
        ("camera", "gain", 100),
        ("camera", "binning_modes", ("1x1", "2x2", "3x3", "4x4")),
        ("camera", "target_temperature", 0.0),
        ("mount", "epoch", "JNOW"),
        ("mount", "tracking_modes", ("Sidereal", "Lunar", "Solar", "Stopped")),
        ("focuser", "position", 2332),
        ("focuser", "max_step", None),          # not on the wire, nor in the spec
        ("filter_wheel", "selected_filter", "R"),
        ("filter_wheel", "available_filters", ("L", "R", "G", "B", "H", "O", "S")),
        ("guider", "state", None),              # no capture has a connected guider
        ("rotator", "synced", True),
        ("dome", "azimuth", None),              # "NaN" on a dome that never existed
        ("dome", "shutter_status", "ShutterNone"),
        ("flat_device", "cover_state", "Closed"),
        ("safety_monitor", "is_safe", False),
    ],
)
def test_each_device_block_maps_its_readings(device, field, expected) -> None:
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert getattr(getattr(snapshot, device), field) == expected


def test_switch_channels_carry_their_writability_and_range() -> None:
    channel = map_equipment_info(load("dawn_equipment_info.json")).switch_device.channels[0]
    assert (channel.name, channel.writable, channel.binary) == ("Flat Panel", True, True)


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
    assert rig_offset(load("dawn_equipment_info.json")) == timedelta(hours=-5)


def test_the_rig_offset_falls_back_to_the_gap_between_the_two_clocks() -> None:
    """`Now` carries the offset on this build; the pair still states it if a
    driver ever reports `Now` naive."""
    wire = load("dawn_equipment_info.json")
    clock = wire["Mount"]["Coordinates"]["DateTime"]
    clock["Now"] = clock["Now"].removesuffix("-05:00")
    assert rig_offset(wire) == timedelta(hours=-5)


def test_the_rig_offset_is_unknown_without_a_mount_clock() -> None:
    assert rig_offset(load("restart_equipment_partial_connect.json")) is None


def test_calibration_frames_lose_their_hfr_but_keep_their_adu() -> None:
    """Keyed on ImageType, which is on both paths. HFR 0 is a reliable
    calibration signal but not a sufficient one — see the clouded-light test."""
    flats = [f for f in load("dawn_image_history_with_flats.json")
             if f["ImageType"] == "FLAT"]
    frame = map_frame(flats[0], generation="g1")
    assert frame.hfr is None
    assert frame.stars is None
    assert frame.mean is not None


def test_light_frames_keep_their_hfr() -> None:
    lights = [f for f in load("dawn_image_history_with_flats.json")
              if f["ImageType"] == "LIGHT"]
    assert map_frame(lights[0], generation="g1").hfr is not None


def test_the_total_guide_rms_is_parsed_out_of_the_rms_text() -> None:
    """RmsText is 'Tot: 0.26 (0.42")' — pixels first, arcseconds in brackets."""
    lights = [f for f in load("dawn_image_history_with_flats.json")
              if f["ImageType"] == "LIGHT"]
    assert map_frame(lights[0], generation="g1").rms == 0.26


def test_an_unparsable_rms_text_is_no_reading() -> None:
    lights = [f for f in load("dawn_image_history_with_flats.json")
              if f["ImageType"] == "LIGHT"]
    assert map_frame({**lights[0], "RmsText": "n/a"}, generation="g1").rms is None


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
    would misclassify every dark."""
    push = load("live_image_save_push.json")["ImageStatistics"]
    frame = map_frame(push, generation="g1")
    assert frame.hfr is None and frame.stars is None


def test_mediator_event_times_are_offset_aware_local() -> None:
    event = map_event({"Event": "IMAGE-SAVE", "Time": "2026-09-03T23:26:19.36-05:00"},
                      generation="g1")
    assert event.time.utcoffset() is not None


def test_ts_event_times_are_naive_utc() -> None:
    """Two naive formats, indistinguishable by shape — key on the event name."""
    event = map_event({"Event": "TS-TARGETSTART", "Time": "2026-09-04T02:15:32.78"},
                      generation="g1")
    assert event.time.utcoffset().total_seconds() == 0


def test_log_scraped_event_times_are_local_and_still_offset_aware() -> None:
    """Left naive, the first ERROR-PLATESOLVE to land beside 600 offset-aware
    events crashes fold()'s sorted iteration with "can't compare offset-naive
    and offset-aware datetimes". Every NinaEvent.time is aware."""
    from datetime import timedelta

    event = map_event({"Event": "ERROR-PLATESOLVE", "Time": "2026-09-03T21:54:26.93"},
                      generation="g1", rig_offset=timedelta(hours=-5))
    assert event.time.utcoffset() == timedelta(hours=-5)


def test_a_naive_local_time_falls_back_to_utc_before_the_offset_is_known() -> None:
    """The first poll can arrive after the first event. Ordering must always be
    defined; replay corrects it once the mount's clock has been read."""
    event = map_event({"Event": "ERROR-PLATESOLVE", "Time": "2026-09-03T21:54:26.93"},
                      generation="g1")
    assert event.time.utcoffset() == timedelta(0)


def test_every_event_class_sorts_together() -> None:
    """The property that matters: one comparable ordering across all three."""
    from datetime import timedelta

    offset = timedelta(hours=-5)
    events = [
        map_event({"Event": "IMAGE-SAVE", "Time": "2026-09-03T23:26:19.36-05:00"},
                  "g1", rig_offset=offset),
        map_event({"Event": "TS-TARGETSTART", "Time": "2026-09-04T02:15:32.78"},
                  "g1", rig_offset=offset),
        map_event({"Event": "ERROR-PLATESOLVE", "Time": "2026-09-03T21:54:26.93"},
                  "g1", rig_offset=offset),
    ]
    # TS-* is naive UTC, so 02:15:32.78 is 21:15 local and sorts FIRST — before
    # the 21:54 local ERROR-PLATESOLVE. Reading the three wall-clock strings and
    # assuming they order as written gets this backwards.
    assert [e.name for e in sorted(events, key=lambda e: e.time)] == [
        "TS-TARGETSTART", "ERROR-PLATESOLVE", "IMAGE-SAVE"]


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
    scalars belong. Nothing above the seam can use them."""
    wire = next(e for e in load("dawn_event_history.json")
                if e["Event"] == "TS-TARGETSTART")
    data = map_event(wire, generation="g1").data
    assert data["TargetName"] == "Lobster & Bubble"
    assert "Coordinates" not in data


def test_the_sequence_root_is_synthetic_and_holds_the_global_triggers() -> None:
    """/sequence/json answers a LIST of top-level nodes, the first of which is a
    bare {"GlobalTriggers": [...]} with no Name or Status of its own."""
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


@pytest.mark.parametrize("raw", ["running", "Running", "STOPPED", "stopped"])
def test_livestack_status_compares_case_insensitively(raw: str) -> None:
    """The OpenAPI enum is [running, stopped]; a live rig returned "Stopped"."""
    status = map_livestack_status({"Status": raw})
    assert status.running is (raw.lower() == "running")


def test_the_profile_allowlist_maps_from_its_nested_sections() -> None:
    """/profile/show is captured as an allowlist projection and never as a
    fixture — a full dump held a live WeatherUnderground key (§8.3)."""
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

"""wire → models.

Every wire quirk lives here and nowhere else:

  - "NaN" → None across every field, no allowlist. .NET serializes double.NaN
    as a JSON string, and the sentinel is overloaded — disconnected, momentarily
    unreadable, and not implemented by this driver all look alike.
  - Calibration is the explicit set FLAT / DARK / BIAS / DARKFLAT, keyed on
    `ImageType`, never on `HFR == 0`. A calibration frame loses `hfr`, `stars`
    and the guide RMS; LIGHT, SNAPSHOT and an unknown type keep their readings
    under the sentinel rules alone (HFR 0, Stars -1, RMS 0 → None). A LIGHT
    keeps `stars` even at 0, because a clouded sub reporting zero stars is the
    most diagnostic reading it has. `Stars -1` is a sentinel everywhere and
    never a calibration signal — flats report it, the captured dark reported
    `Stars 1`.
  - TimeToMeridianFlip is None while tracking is off, and at the literal 24 —
    the sentinel — whatever TrackingEnabled says. Tracking off and a driver
    exception both return that 24 without computing anything; every computed
    value is in [0, 24), because the calculation subtracts 24 from whatever
    reaches it. 12 h is legitimate — a mount inside the pier-side window that
    adds 12 h reads it — so "≥12" is no rule either: only the literal 24 is.
  - A `Connected: false` block maps with every reading None — `connected`,
    `meta` and the capabilities survive, and a switch's channel list is a
    capability, not a reading. A disconnected driver answers Position 0,
    StepSize 0, ShutterNone: template defaults, not readings. Guider
    PixelScale 0 is no reading even when connected.
  - Three timestamp classes, two of them naive and indistinguishable by shape,
    keyed by EVENT NAME through EVENT_TIMEZONES. Every NinaEvent.time is
    offset-aware: the fold sorts events, and one naive time among aware ones
    raises. Where the class is local and the rig's offset is not yet known, UTC
    stands in — ordering must always be defined, and replay corrects it.
  - The live socket IMAGE-SAVE carries ImageStatistics and no Time; the frame's
    own Date is its time.
  - TS-* payloads carry "Coordinates": {"RA": [], …} — empty arrays where
    scalars belong — so NinaEvent.data keeps scalars only.
  - Flat-panel brightness range is per-device; mount tracking modes come from
    TrackingModes. Never hardcode either.

A device block is mapped whenever it is present, disconnected or not: a
disconnected device DROPS `DeviceId`, `Name` and `DisplayName` rather than
nulling them, and the "has ever carried a DeviceId" latch that distinguishes
"never observed" from "down" needs state, so it lives in the coordinator. This
module is stateless.

If a sentinel reaches derive.py, models.py carries sentinel values and the seam
is broken.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any

from ..models import (
    CameraModel,
    DeviceMeta,
    DomeModel,
    EquipmentSnapshot,
    FilterWheelModel,
    FlatDeviceModel,
    FlatsStatus,
    FocuserModel,
    Frame,
    GuiderModel,
    LivestackStatus,
    MountModel,
    NinaEvent,
    ProfileSettings,
    RotatorModel,
    SafetyMonitorModel,
    SequenceNode,
    SwitchChannelModel,
    SwitchDeviceModel,
    WeatherModel,
)

_MERIDIAN_IDLE_SENTINEL = 24.0
_IDLE_ITERATIONS_SENTINEL = -1
_NO_STARS_SENTINEL = -1
_CALIBRATION_TYPES = frozenset({"FLAT", "DARK", "BIAS", "DARKFLAT"})

# Event-name PREFIX → the timezone a naive `Time` is in. Mediator events are
# offset-aware and need no entry; TS-* are naive UTC; log-scraped ERROR-* are
# naive local. Anything else naive is treated as local.
EVENT_TIMEZONES: Mapping[str, str] = MappingProxyType({"TS-": "utc", "ERROR-": "local"})

# WeatherData channel → model key. AveragePeriod is a driver setting, not a
# reading, and is deliberately absent.
_WEATHER_CHANNELS: Mapping[str, str] = MappingProxyType({
    "CloudCover": "cloud_cover",
    "DewPoint": "dew_point",
    "Humidity": "humidity",
    "Pressure": "pressure",
    "RainRate": "rain_rate",
    "SkyBrightness": "sky_brightness",
    "SkyQuality": "sky_quality",
    "SkyTemperature": "sky_temperature",
    "StarFWHM": "star_fwhm",
    "Temperature": "temperature",
    "WindDirection": "wind_direction",
    "WindGust": "wind_gust",
    "WindSpeed": "wind_speed",
})

# Keys under which /sequence/json nests child nodes. A node's own scalars go to
# `attributes`; these do not.
_SEQUENCE_CHILDREN = ("GlobalTriggers", "Conditions", "Items", "Triggers")
_SEQUENCE_OWN_KEYS = ("Name", "Status", "Iterations", *_SEQUENCE_CHILDREN)

# 'Tot: 0.26 (0.42")' — the bracketed figure is the arcsecond one.
_TOTAL_RMS_ARCSEC = re.compile(r"\(\s*([-+]?\d*\.?\d+)")


def nan_to_none(value: Any) -> Any:
    """The blanket rule."""
    if isinstance(value, str) and value.strip().lower() == "nan":
        return None
    if isinstance(value, float) and value != value:
        return None
    return value


def _dig(wire: Any, *path: str) -> Any:
    """Follow a key path, answering None at the first key that is not there."""
    node = wire
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return nan_to_none(node)


def _is_number(value: Any) -> bool:
    """`bool` is an `int` in Python; a flag is never a reading."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _number(wire: Any, *path: str) -> float | None:
    value = _dig(wire, *path)
    return float(value) if _is_number(value) else None


def _integer(wire: Any, *path: str) -> int | None:
    value = _dig(wire, *path)
    return int(value) if _is_number(value) else None


def _flag(wire: Any, *path: str) -> bool | None:
    value = _dig(wire, *path)
    return value if isinstance(value, bool) else None


def _text(wire: Any, *path: str) -> str | None:
    value = _dig(wire, *path)
    return value if isinstance(value, str) else None


def _timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _names(entries: Any) -> tuple[str, ...]:
    """The `Name` of each object in a list — filters, binning modes, ..."""
    return tuple(entry["Name"] for entry in entries or ()
                 if isinstance(entry, dict) and isinstance(entry.get("Name"), str))


def _meta(wire: dict) -> DeviceMeta:
    return DeviceMeta(
        name=_text(wire, "Name"),
        display_name=_text(wire, "DisplayName"),
        description=_text(wire, "Description"),
        driver_version=_text(wire, "DriverVersion"),
        device_id=_text(wire, "DeviceId"),
    )


def _connected(wire: dict) -> bool:
    return _flag(wire, "Connected") is True


def _readings(wire: dict) -> dict:
    """The block to read measurements from: empty when the device is down.

    Capability flags and registry metadata still come from `wire`; everything
    a driver measures comes from here, so a disconnected block maps to None
    for every reading without a per-field guard.
    """
    return wire if _connected(wire) else {}


def map_camera(wire: dict) -> CameraModel:
    readings = _readings(wire)
    has_battery = _flag(wire, "HasBattery")
    battery = _number(readings, "Battery")
    if has_battery is not True or (battery is not None and battery < 0):
        battery = None  # -1 is "no battery", not a charge level
    return CameraModel(
        connected=_connected(wire),
        meta=_meta(wire),
        temperature=_number(readings, "Temperature"),
        target_temperature=_number(readings, "TargetTemp"),
        cooler_on=_flag(readings, "CoolerOn"),
        cooler_power=_number(readings, "CoolerPower"),
        dew_heater_on=_flag(readings, "DewHeaterOn"),
        gain=_integer(readings, "Gain"),
        offset=_integer(readings, "Offset"),
        usb_limit=_integer(readings, "USBLimit"),
        usb_limit_min=_integer(wire, "USBLimitMin"),
        usb_limit_max=_integer(wire, "USBLimitMax"),
        camera_state=_text(readings, "CameraState"),
        is_exposing=_flag(readings, "IsExposing"),
        pixel_size=_number(readings, "PixelSize"),
        has_battery=has_battery,
        battery=battery,
        can_set_temperature=_flag(wire, "CanSetTemperature"),
        gains=tuple(int(gain) for gain in wire.get("Gains") or () if _is_number(gain)),
        binning_modes=_names(wire.get("BinningModes")),
        bin_x=_integer(readings, "BinX"),
    )


def map_mount(wire: dict) -> MountModel:
    readings = _readings(wire)
    tracking = _flag(readings, "TrackingEnabled")
    flip = _number(readings, "TimeToMeridianFlip")
    if tracking is False or flip == _MERIDIAN_IDLE_SENTINEL:
        flip = None
    return MountModel(
        connected=_connected(wire),
        meta=_meta(wire),
        right_ascension=_number(readings, "RightAscension"),
        declination=_number(readings, "Declination"),
        altitude=_number(readings, "Altitude"),
        azimuth=_number(readings, "Azimuth"),
        sidereal_time=_number(readings, "SiderealTime"),
        tracking_enabled=tracking,
        tracking_mode=_text(readings, "TrackingMode"),
        tracking_modes=tuple(mode for mode in wire.get("TrackingModes") or ()
                             if isinstance(mode, str)),
        at_park=_flag(readings, "AtPark"),
        at_home=_flag(readings, "AtHome"),
        side_of_pier=_text(readings, "SideOfPier"),
        time_to_meridian_flip=flip,
        can_slew_alt_az=_flag(wire, "CanSlewAltAz"),
        epoch=_text(wire, "EquatorialSystem"),
    )


def map_focuser(wire: dict) -> FocuserModel:
    readings = _readings(wire)
    return FocuserModel(
        connected=_connected(wire),
        meta=_meta(wire),
        position=_integer(readings, "Position"),
        temperature=_number(readings, "Temperature"),
        is_moving=_flag(readings, "IsMoving"),
        step_size=_number(readings, "StepSize"),
        temp_comp_available=_flag(wire, "TempCompAvailable"),
        temp_comp=_flag(readings, "TempComp"),
    )


def map_filter_wheel(wire: dict) -> FilterWheelModel:
    readings = _readings(wire)
    return FilterWheelModel(
        connected=_connected(wire),
        meta=_meta(wire),
        selected_filter=_text(readings, "SelectedFilter", "Name"),
        available_filters=_names(wire.get("AvailableFilters")),
        is_moving=_flag(readings, "IsMoving"),
    )


def map_guider(wire: dict) -> GuiderModel:
    """RMSError is reported in both pixels and arcseconds; arcseconds is the
    figure that means the same thing on every rig.
    """
    readings = _readings(wire)
    return GuiderModel(
        connected=_connected(wire),
        meta=_meta(wire),
        state=_text(readings, "State"),
        rms_total=_number(readings, "RMSError", "Total", "Arcseconds"),
        rms_ra=_number(readings, "RMSError", "RA", "Arcseconds"),
        rms_dec=_number(readings, "RMSError", "Dec", "Arcseconds"),
        # A plate scale of 0 is never a reading, connected or not.
        pixel_scale=_number(readings, "PixelScale") or None,
    )


def map_rotator(wire: dict) -> RotatorModel:
    readings = _readings(wire)
    return RotatorModel(
        connected=_connected(wire),
        meta=_meta(wire),
        position=_number(readings, "Position"),
        mechanical_position=_number(readings, "MechanicalPosition"),
        is_moving=_flag(readings, "IsMoving"),
        reverse=_flag(readings, "Reverse"),
        synced=_flag(readings, "Synced"),
    )


def map_dome(wire: dict) -> DomeModel:
    readings = _readings(wire)
    return DomeModel(
        connected=_connected(wire),
        meta=_meta(wire),
        azimuth=_number(readings, "Azimuth"),
        shutter_status=_text(readings, "ShutterStatus"),
        at_park=_flag(readings, "AtPark"),
        at_home=_flag(readings, "AtHome"),
        driver_following=_flag(readings, "DriverFollowing"),
        following=_flag(readings, "IsFollowing"),
        slewing=_flag(readings, "Slewing"),
    )


def map_flat_device(wire: dict) -> FlatDeviceModel:
    readings = _readings(wire)
    return FlatDeviceModel(
        connected=_connected(wire),
        meta=_meta(wire),
        cover_state=_text(readings, "CoverState"),
        light_on=_flag(readings, "LightOn"),
        brightness=_number(readings, "Brightness"),
        min_brightness=_number(readings, "MinBrightness"),
        max_brightness=_number(readings, "MaxBrightness"),
        supports_on_off=_flag(wire, "SupportsOnOff"),
        supports_open_close=_flag(wire, "SupportsOpenClose"),
    )


def map_weather(wire: dict) -> WeatherModel:
    """Every channel the wire carries is in the map; a channel this source
    cannot report arrives as "NaN" and so reads None, poll after poll. §5.2.2's
    first-reading rule keys on a channel having ever been non-None.
    """
    readings = _readings(wire)
    return WeatherModel(
        connected=_connected(wire),
        meta=_meta(wire),
        channels={channel: _number(readings, key)
                  for key, channel in _WEATHER_CHANNELS.items() if key in wire},
    )


def map_safety_monitor(wire: dict) -> SafetyMonitorModel:
    return SafetyMonitorModel(
        connected=_connected(wire),
        meta=_meta(wire),
        is_safe=_flag(_readings(wire), "IsSafe"),
    )


def map_switch(wire: dict) -> SwitchDeviceModel:
    """The channel list is the device's capability, so it survives a disconnect
    the way every other block's option lists and ranges do; only `value` is a
    reading, and a disconnected device has none.
    """
    connected = _connected(wire)
    channels: list[SwitchChannelModel] = []
    for key, writable in (("WritableSwitches", True), ("ReadonlySwitches", False)):
        for position, entry in enumerate(wire.get(key) or ()):
            index = _integer(entry, "Id")
            channels.append(SwitchChannelModel(
                index=index if index is not None else position,
                name=_text(entry, "Name") or "",
                description=_text(entry, "Description") or "",
                value=_number(entry, "Value") if connected else None,
                minimum=_number(entry, "Minimum"),
                maximum=_number(entry, "Maximum"),
                step_size=_number(entry, "StepSize"),
                writable=writable,
            ))
    return SwitchDeviceModel(
        connected=connected,
        meta=_meta(wire),
        channels=tuple(channels),
    )


_BLOCKS = (
    ("camera", "Camera", map_camera),
    ("mount", "Mount", map_mount),
    ("focuser", "Focuser", map_focuser),
    ("filter_wheel", "FilterWheel", map_filter_wheel),
    ("guider", "Guider", map_guider),
    ("rotator", "Rotator", map_rotator),
    ("dome", "Dome", map_dome),
    ("flat_device", "FlatDevice", map_flat_device),
    ("weather", "WeatherData", map_weather),
    ("safety_monitor", "SafetyMonitor", map_safety_monitor),
    ("switch_device", "Switch", map_switch),
)


def map_equipment_info(wire: dict) -> EquipmentSnapshot:
    """All eleven blocks, mapped whether the device is connected or not.

    `None` here means the block was missing from the response, which this build
    never does. "Never observed" is a latch over successive snapshots and is the
    coordinator's to keep.
    """
    def block(key: str, mapper: Any) -> Any:
        raw = wire.get(key)
        return mapper(raw) if isinstance(raw, dict) else None

    return EquipmentSnapshot(**{field: block(key, mapper)
                                for field, key, mapper in _BLOCKS})


def rig_utc_offset(wire: dict) -> timedelta | None:
    """The rig's UTC offset, from the mount's own clock in /equipment/info.

    Naive log-scraped event times are in this offset, and it is the only place
    the API states it. `None` while the mount is disconnected — the block drops
    `Coordinates` entirely.
    """
    now = _timestamp(_dig(wire, "Mount", "Coordinates", "DateTime", "Now"))
    if now is None:
        return None
    if now.utcoffset() is not None:
        return now.utcoffset()
    utcnow = _timestamp(_dig(wire, "Mount", "Coordinates", "DateTime", "UtcNow"))
    if utcnow is None:
        return None
    drift = now - utcnow.replace(tzinfo=None)
    return timedelta(minutes=round(drift.total_seconds() / 60))


def _total_rms_arcsec(raw: Any) -> float | None:
    """The bracketed arcsecond total of 'Tot: 0.18 (0.29")'; the leading figure
    is guide-camera pixels, which mean something different on every rig."""
    match = _TOTAL_RMS_ARCSEC.search(raw) if isinstance(raw, str) else None
    return float(match.group(1)) if match else None


def map_frame(wire: dict, generation: str | None) -> Frame:
    """One saved sub, from `/image-history` or from an `IMAGE-SAVE` push.

    `Date` and `Filename` are the frame's identity and are present on every
    frame on both paths; a payload without them is not a frame.

    Only the calibration set loses readings. LIGHT, SNAPSHOT and a frame with
    no `ImageType` at all keep every reading the sentinel rules allow: the type
    decides only what is *dropped*, so an unclassifiable frame is treated as
    neither calibration nor light rather than losing real data.
    """
    image_type = _text(wire, "ImageType")
    hfr = _number(wire, "HFR")
    stars = _integer(wire, "Stars")
    rms = _total_rms_arcsec(_dig(wire, "RmsText"))
    if image_type in _CALIBRATION_TYPES:
        # Its ADU statistics are real measurements and survive; HFR, star count
        # and guide RMS are meaningless on a frame with no sky in it.
        hfr = None
        stars = None
        rms = None
    else:
        # HFR 0 is "no stars measured", and 'Tot: 0.00' is no guiding, not
        # perfect guiding.
        hfr = hfr or None
        rms = rms or None
    return Frame(
        date=datetime.fromisoformat(wire["Date"]),
        filename=str(wire["Filename"]),
        target_name=_text(wire, "TargetName"),
        # A calibration frame taken with no filter reports "", not a filter name.
        filter_name=_text(wire, "Filter") or None,
        image_type=image_type,
        exposure_time=_number(wire, "ExposureTime"),
        hfr=hfr,
        stars=None if stars == _NO_STARS_SENTINEL else stars,
        mean=_number(wire, "Mean"),
        median=_number(wire, "Median"),
        std_dev=_number(wire, "StDev"),
        rms_arcsec=rms,
        temperature=_number(wire, "Temperature"),
        gain=_integer(wire, "Gain"),
        offset=_integer(wire, "Offset"),
        focal_length=_number(wire, "FocalLength"),
        generation=generation,
    )


def map_image_save(payload: dict, generation: str | None) -> Frame | None:
    """The frame inside an `IMAGE-SAVE`. `/event-history`'s stored copies carry
    no statistics at all, so absence is normal.
    """
    statistics = payload.get("ImageStatistics")
    if not isinstance(statistics, dict) or "Date" not in statistics:
        return None
    return map_frame(statistics, generation)


def _event_time(name: str, wire: dict, frame: Frame | None,
                offset: timedelta | None) -> datetime:
    parsed = _timestamp(wire.get("Time"))
    if parsed is None:
        if frame is None:
            raise ValueError(f"event {name!r} carries neither a Time nor a frame")
        return frame.date  # the live socket IMAGE-SAVE has no Time of its own
    if parsed.tzinfo is not None:
        return parsed
    zone = next((z for prefix, z in EVENT_TIMEZONES.items()
                 if name.startswith(prefix)), "local")
    if zone == "utc" or offset is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.replace(tzinfo=timezone(offset))


def map_event(wire: dict, generation: str | None, *,
              rig_offset: timedelta | None = None) -> NinaEvent:
    """One socket push or `/event-history` entry.

    `rig_offset` resolves the naive local times of the log-scraped `ERROR-*`
    events; without it they are read as UTC, which keeps every event comparable
    at the cost of a known offset. Replay corrects them once the mount's clock
    has been read.
    """
    name = str(wire.get("Event", ""))
    frame = map_image_save(wire, generation)
    return NinaEvent(
        name=name,
        time=_event_time(name, wire, frame, rig_offset),
        data={key: nan_to_none(value) for key, value in wire.items()
              if key not in ("Event", "Time", "ImageStatistics")
              and not isinstance(value, (dict, list))},
        generation=generation,
        frame=frame,
    )


def _sequence_node(wire: dict, fallback: str) -> SequenceNode:
    name = _text(wire, "Name")
    iterations = _dig(wire, "Iterations")
    return SequenceNode(
        name=name if name is not None else fallback,
        status=_text(wire, "Status"),
        iterations=None if iterations is None else str(iterations),
        children=tuple(_sequence_node(child, key)
                       for key in _SEQUENCE_CHILDREN
                       for child in wire.get(key) or ()
                       if isinstance(child, dict)),
        attributes={key: nan_to_none(value) for key, value in wire.items()
                    if key not in _SEQUENCE_OWN_KEYS
                    and not isinstance(value, (dict, list))},
    )


def map_sequence(wire: list[dict] | None) -> SequenceNode | None:
    """`/sequence/json` answers a LIST of top-level nodes — the global triggers
    in a bare wrapper, then the root containers — so the tree gets a synthetic
    root. A sequence that has not been loaded answers `""` and no tree.
    """
    if not isinstance(wire, list):
        return None
    return SequenceNode(
        name="Sequence",
        status=None,
        iterations=None,
        # The only nameless top-level node is the global-trigger wrapper, which
        # names itself through the key its children hang from.
        children=tuple(_sequence_node(node, "GlobalTriggers")
                       for node in wire if isinstance(node, dict)),
        attributes={},
    )


def _iterations(wire: dict, key: str) -> int | None:
    count = _integer(wire, key)
    return None if count == _IDLE_ITERATIONS_SENTINEL else count


def map_flats_status(wire: dict) -> FlatsStatus:
    """Only flats started through the API are counted; a Target Scheduler flat
    run leaves -1 iterations behind, which is no count at all.
    """
    return FlatsStatus(
        state=_text(wire, "State"),
        total_iterations=_iterations(wire, "TotalIterations"),
        completed_iterations=_iterations(wire, "CompletedIterations"),
    )


def map_livestack_status(wire: dict | str) -> LivestackStatus:
    """The Response is the BARE status string — `"Running"`, not
    `{"Status": "Running"}` as the spec documents. The documented shape is
    still read, because only one build has been observed. The spec's enum is
    also lowercase, and the rig answers "Stopped".
    """
    raw = wire if isinstance(wire, str) else _text(wire, "Status") or ""
    return LivestackStatus(running=raw.lower() == "running", raw_state=raw)


def map_profile(wire: dict) -> ProfileSettings:
    """The allowlisted slice of `/profile/show`. The full dump carries live
    credentials and is never captured, so this maps from the spec's names.
    """
    return ProfileSettings(
        focal_length=_number(wire, "TelescopeSettings", "FocalLength"),
        pixel_size=_number(wire, "CameraSettings", "PixelSize"),
        autofocus_timeout_seconds=_number(wire, "FocuserSettings",
                                          "AutoFocusTimeoutSeconds"),
        r_squared_threshold=_number(wire, "FocuserSettings", "RSquaredThreshold"),
        min_minutes_after_meridian=_number(wire, "MeridianFlipSettings",
                                           "MinutesAfterMeridian"),
        max_minutes_after_meridian=_number(wire, "MeridianFlipSettings",
                                           "MaxMinutesAfterMeridian"),
        use_side_of_pier=_flag(wire, "MeridianFlipSettings", "UseSideOfPier"),
    )

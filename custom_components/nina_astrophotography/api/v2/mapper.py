"""wire → models.

Every wire quirk lives here and nowhere else:

  - "NaN" → None across every field, no allowlist. .NET serializes double.NaN
    as a JSON string, and the sentinel is overloaded — disconnected, momentarily
    unreadable, and not implemented by this driver all look alike.
  - Calibration is keyed on `ImageType`, never on `HFR == 0`. A non-light loses
    both `hfr` and `stars`; a LIGHT keeps `stars` even at 0, because a clouded
    sub reporting zero stars is the most diagnostic reading it has. `Stars -1`
    is a sentinel everywhere and never a calibration signal — flats report it,
    the captured dark reported `Stars 1`.
  - TimeToMeridianFlip 24 → None, as is any value while tracking is off. 12 h is
    legitimate — it means "just flipped" — so a "≥12 → unknown" rule would be
    wrong.
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

_TOTAL_RMS = re.compile(r"[-+]?\d*\.?\d+")


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


def _number(wire: Any, *path: str) -> float | None:
    value = _dig(wire, *path)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _integer(wire: Any, *path: str) -> int | None:
    value = _dig(wire, *path)
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


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


def map_camera(wire: dict) -> CameraModel:
    return CameraModel(
        connected=_connected(wire),
        meta=_meta(wire),
        temperature=_number(wire, "Temperature"),
        target_temperature=_number(wire, "TargetTemp"),
        cooler_on=_flag(wire, "CoolerOn"),
        cooler_power=_number(wire, "CoolerPower"),
        dew_heater_on=_flag(wire, "DewHeaterOn"),
        gain=_integer(wire, "Gain"),
        offset=_integer(wire, "Offset"),
        usb_limit=_integer(wire, "USBLimit"),
        camera_state=_text(wire, "CameraState"),
        is_exposing=_flag(wire, "IsExposing"),
        pixel_size=_number(wire, "PixelSize"),
        has_battery=_flag(wire, "HasBattery"),
        battery=_number(wire, "Battery"),
        can_set_temperature=_flag(wire, "CanSetTemperature"),
        gains=tuple(int(gain) for gain in wire.get("Gains") or ()
                    if isinstance(gain, (int, float)) and not isinstance(gain, bool)),
        binning_modes=_names(wire.get("BinningModes")),
        bin_x=_integer(wire, "BinX"),
    )


def map_mount(wire: dict) -> MountModel:
    tracking = _flag(wire, "TrackingEnabled")
    flip = _number(wire, "TimeToMeridianFlip")
    if tracking is False or (flip is not None and flip >= _MERIDIAN_IDLE_SENTINEL):
        flip = None
    return MountModel(
        connected=_connected(wire),
        meta=_meta(wire),
        right_ascension=_number(wire, "RightAscension"),
        declination=_number(wire, "Declination"),
        altitude=_number(wire, "Altitude"),
        azimuth=_number(wire, "Azimuth"),
        sidereal_time=_number(wire, "SiderealTime"),
        tracking_enabled=tracking,
        tracking_mode=_text(wire, "TrackingMode"),
        tracking_modes=tuple(mode for mode in wire.get("TrackingModes") or ()
                             if isinstance(mode, str)),
        at_park=_flag(wire, "AtPark"),
        at_home=_flag(wire, "AtHome"),
        side_of_pier=_text(wire, "SideOfPier"),
        time_to_meridian_flip=flip,
        can_slew_alt_az=_flag(wire, "CanSlewAltAz"),
        epoch=_text(wire, "EquatorialSystem"),
    )


def map_focuser(wire: dict) -> FocuserModel:
    return FocuserModel(
        connected=_connected(wire),
        meta=_meta(wire),
        position=_integer(wire, "Position"),
        temperature=_number(wire, "Temperature"),
        is_moving=_flag(wire, "IsMoving"),
        max_step=None,  # neither the wire nor the spec carries a travel limit
        step_size=_number(wire, "StepSize"),
        temp_comp_available=_flag(wire, "TempCompAvailable"),
        temp_comp=_flag(wire, "TempComp"),
    )


def map_filter_wheel(wire: dict) -> FilterWheelModel:
    return FilterWheelModel(
        connected=_connected(wire),
        meta=_meta(wire),
        selected_filter=_text(wire, "SelectedFilter", "Name"),
        available_filters=_names(wire.get("AvailableFilters")),
        is_moving=_flag(wire, "IsMoving"),
    )


def map_guider(wire: dict) -> GuiderModel:
    """RMSError is reported in both pixels and arcseconds; arcseconds is the
    figure that means the same thing on every rig.
    """
    return GuiderModel(
        connected=_connected(wire),
        meta=_meta(wire),
        state=_text(wire, "State"),
        rms_total=_number(wire, "RMSError", "Total", "Arcseconds"),
        rms_ra=_number(wire, "RMSError", "RA", "Arcseconds"),
        rms_dec=_number(wire, "RMSError", "Dec", "Arcseconds"),
        pixel_scale=_number(wire, "PixelScale"),
    )


def map_rotator(wire: dict) -> RotatorModel:
    return RotatorModel(
        connected=_connected(wire),
        meta=_meta(wire),
        position=_number(wire, "Position"),
        mechanical_position=_number(wire, "MechanicalPosition"),
        is_moving=_flag(wire, "IsMoving"),
        reverse=_flag(wire, "Reverse"),
        synced=_flag(wire, "Synced"),
    )


def map_dome(wire: dict) -> DomeModel:
    return DomeModel(
        connected=_connected(wire),
        meta=_meta(wire),
        azimuth=_number(wire, "Azimuth"),
        shutter_status=_text(wire, "ShutterStatus"),
        at_park=_flag(wire, "AtPark"),
        at_home=_flag(wire, "AtHome"),
        driver_following=_flag(wire, "DriverFollowing"),
        following=_flag(wire, "IsFollowing"),
        slewing=_flag(wire, "Slewing"),
    )


def map_flat_device(wire: dict) -> FlatDeviceModel:
    return FlatDeviceModel(
        connected=_connected(wire),
        meta=_meta(wire),
        cover_state=_text(wire, "CoverState"),
        light_on=_flag(wire, "LightOn"),
        brightness=_number(wire, "Brightness"),
        min_brightness=_number(wire, "MinBrightness"),
        max_brightness=_number(wire, "MaxBrightness"),
        supports_on_off=_flag(wire, "SupportsOnOff"),
        supports_open_close=_flag(wire, "SupportsOpenClose"),
    )


def map_weather(wire: dict) -> WeatherModel:
    """A channel this source cannot report is absent from the map, not None: the
    entity for it is created on first reading and kept thereafter (§5.2.2).
    """
    return WeatherModel(
        connected=_connected(wire),
        meta=_meta(wire),
        channels={channel: _number(wire, key)
                  for key, channel in _WEATHER_CHANNELS.items() if key in wire},
    )


def map_safety_monitor(wire: dict) -> SafetyMonitorModel:
    return SafetyMonitorModel(
        connected=_connected(wire),
        meta=_meta(wire),
        is_safe=_flag(wire, "IsSafe"),
    )


def map_switch(wire: dict) -> SwitchDeviceModel:
    channels: list[SwitchChannelModel] = []
    for key, writable in (("WritableSwitches", True), ("ReadonlySwitches", False)):
        for position, entry in enumerate(wire.get(key) or ()):
            index = _integer(entry, "Id")
            channels.append(SwitchChannelModel(
                index=index if index is not None else position,
                name=_text(entry, "Name") or "",
                description=_text(entry, "Description") or "",
                value=_number(entry, "Value"),
                minimum=_number(entry, "Minimum"),
                maximum=_number(entry, "Maximum"),
                step_size=_number(entry, "StepSize"),
                writable=writable,
            ))
    return SwitchDeviceModel(
        connected=_connected(wire),
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


def rig_offset(wire: dict) -> timedelta | None:
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


def _total_rms(raw: Any) -> float | None:
    """`RmsText` is 'Tot: 0.18 (0.29")' — total in pixels, then in arcseconds."""
    match = _TOTAL_RMS.search(raw) if isinstance(raw, str) else None
    return float(match.group()) if match else None


def map_frame(wire: dict, generation: str | None) -> Frame:
    """One saved sub, from `/image-history` or from an `IMAGE-SAVE` push.

    `Date` and `Filename` are the frame's identity and are present on every
    frame on both paths; a payload without them is not a frame.
    """
    image_type = _text(wire, "ImageType")
    hfr = _number(wire, "HFR")
    stars = _integer(wire, "Stars")
    if image_type != "LIGHT":
        # Calibration. Its ADU statistics are real measurements and survive;
        # HFR and star count are meaningless on a frame with no sky in it.
        hfr = None
        stars = None
    elif hfr == 0:
        hfr = None
    return Frame(
        date=datetime.fromisoformat(wire["Date"]),
        filename=str(wire["Filename"]),
        target_name=_text(wire, "TargetName"),
        filter_name=_text(wire, "Filter"),
        image_type=image_type,
        exposure_time=_number(wire, "ExposureTime"),
        hfr=hfr,
        stars=None if stars == _NO_STARS_SENTINEL else stars,
        mean=_number(wire, "Mean"),
        median=_number(wire, "Median"),
        std_dev=_number(wire, "StDev"),
        rms=_total_rms(_dig(wire, "RmsText")),
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


def map_flats_status(wire: dict) -> FlatsStatus:
    """Only flats started through the API are counted; a Target Scheduler flat
    run leaves -1 iterations behind, which is no count at all.
    """
    total = _integer(wire, "TotalIterations")
    completed = _integer(wire, "CompletedIterations")
    return FlatsStatus(
        state=_text(wire, "State"),
        total_iterations=None if total == _IDLE_ITERATIONS_SENTINEL else total,
        completed_iterations=(None if completed == _IDLE_ITERATIONS_SENTINEL
                              else completed),
    )


def map_livestack_status(wire: dict) -> LivestackStatus:
    """The spec's enum is lowercase; the rig answers "Stopped"."""
    raw = str(_dig(wire, "Status"))
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

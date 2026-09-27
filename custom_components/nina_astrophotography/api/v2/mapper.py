"""wire → models. Every wire quirk lives here.

  - `"NaN"` → `None` across every field, no allowlist. .NET serializes
    `double.NaN` as that string, and it is overloaded: disconnected,
    momentarily unreadable, and unimplemented all look alike.
  - Calibration is FLAT / DARK / BIAS / DARKFLAT, keyed on `ImageType`, never
    on `HFR == 0`. It loses `hfr`, `stars` and the guide RMS; a light keeps
    `stars` even at 0, since a clouded sub reporting none is still
    diagnostic. `Stars -1` is a sentinel everywhere, never a calibration
    signal.
  - `TimeToMeridianFlip` is `None` while tracking is off, and at the literal
    24 (the sentinel) regardless of `TrackingEnabled` — every computed value
    is in [0, 24), so 12 h is a legitimate reading and only 24 is the sentinel.
  - A `Connected: false` block maps with every reading `None`; `connected`,
    `meta` and capability flags survive, since a disconnected driver answers
    template defaults for readings, not for capabilities.
  - Every `NinaEvent.time` is offset-aware, keyed on event name through
    `EVENT_TIMEZONES`; where the zone is local and the rig's offset is
    unknown, UTC stands in until replay corrects it.
  - `TS-*` payloads carry empty arrays where scalars belong (`"RA": []`), so
    `NinaEvent.data` keeps scalars only.
  - Flat-panel brightness range and mount tracking modes are per-device;
    never hardcoded.

A device block is mapped whenever present, connected or not: the coordinator
keeps the "has ever carried a `DeviceId`" latch; this module is stateless.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
import math
import re
from types import MappingProxyType
from typing import Any

from ..models import (
    AutoFocusReport,
    CameraModel,
    CurveFit,
    DeviceMeta,
    DomeModel,
    EquipmentSnapshot,
    FilterWheelModel,
    FitMinimum,
    FlatDeviceModel,
    FlatsStatus,
    FocuserModel,
    FocusPoint,
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
# Far above any plausible ASCOM switch id, so a synthesized read-only index
# can never collide with a real one from either list.
_READONLY_INDEX_BASE = 10_000

# Event-name PREFIX → the timezone a naive `Time` is in. Mediator events are
# offset-aware and need no entry; TS-* are naive UTC; log-scraped ERROR-* are
# naive local. Anything else naive is treated as local.
EVENT_TIMEZONES: Mapping[str, str] = MappingProxyType({"TS-": "utc", "ERROR-": "local"})

_SCHEDULER_WAIT_STARTED = "TS-WAITSTART"

# WeatherData channel → model key. AveragePeriod is a driver setting, not a
# reading, and is deliberately absent.
_WEATHER_CHANNELS: Mapping[str, str] = MappingProxyType(
    {
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
    }
)

# Keys under which /sequence/json nests child nodes. A node's own scalars go to
# `attributes`; these do not.
_SEQUENCE_CHILDREN = ("GlobalTriggers", "Conditions", "Items", "Triggers")
_SEQUENCE_OWN_KEYS = ("Name", "Status", "Iterations", *_SEQUENCE_CHILDREN)

# 'Tot: 0.26 (0.42")' — the bracketed figure is the arcsecond one.
_TOTAL_RMS_ARCSEC = re.compile(r"\(\s*([-+]?\d*\.?\d+)")

# .NET's TimeSpan: `[-][d.]hh:mm:ss[.fffffff]`, days separated by a DOT — so
# "1.02:03:04" is a day and two hours, not a fractional day.
_TIMESPAN = re.compile(
    r"^(?P<sign>-)?(?:(?P<days>\d+)\.)?(?P<hours>\d{1,2}):"
    r"(?P<minutes>\d{2}):(?P<seconds>\d{2}(?:\.\d+)?)$"
)

# The only method whose focus points are HFR in pixels. An allowlist, not a
# denylist: CONTRASTDETECTION is the one non-HFR method shipped today, and a
# method nobody here has seen must not have its numbers published as pixels.
_HFR_METHODS = frozenset({"STARHFR"})


def nan_to_none(value: Any) -> Any:
    """The blanket rule."""
    if isinstance(value, str) and value.strip().lower() == "nan":
        return None
    if isinstance(value, float) and math.isnan(value):
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


def _range(wire: Any, low_key: str, high_key: str) -> tuple[float, float] | None:
    """`(low, high)`, or `None` for an empty or missing range."""
    low, high = _number(wire, low_key), _number(wire, high_key)
    if low is None or high is None or high <= low:
        return None
    return low, high


def _flag(wire: Any, *path: str) -> bool | None:
    value = _dig(wire, *path)
    return value if isinstance(value, bool) else None


def _text(wire: Any, *path: str) -> str | None:
    value = _dig(wire, *path)
    return value if isinstance(value, str) else None


def _timespan_seconds(raw: Any) -> float | None:
    """A .NET TimeSpan string as seconds; None for anything else."""
    match = _TIMESPAN.match(raw.strip()) if isinstance(raw, str) else None
    if match is None:
        return None
    total = (
        int(match["days"] or 0) * 86400
        + int(match["hours"]) * 3600
        + int(match["minutes"]) * 60
        + float(match["seconds"])
    )
    return -total if match["sign"] else total


def _timestamp(raw: Any) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _slots(entries: Any) -> Mapping[str, int]:
    """Filter name → the wheel's own `Id`, for entries that carry both."""
    if not isinstance(entries, list):
        return MappingProxyType({})
    return MappingProxyType(
        {
            entry["Name"]: index
            for entry in entries
            if isinstance(entry, dict)
            and isinstance(entry.get("Name"), str)
            and (index := _integer(entry, "Id")) is not None
        }
    )


def _names(entries: Any) -> tuple[str, ...]:
    """The `Name` of each object in a list — filters, binning modes, ..."""
    return tuple(
        entry["Name"]
        for entry in entries or ()
        if isinstance(entry, dict) and isinstance(entry.get("Name"), str)
    )


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
    """Where readings come from; empty when the device is down, so every
    reading maps to `None` without a per-field guard. Capability flags and
    metadata still read from `wire`.
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
        # The driver's setpoint. TargetTemp is not: it reads 0 whatever the
        # camera is cooling to.
        target_temperature=_number(readings, "TemperatureSetPoint"),
        cooler_on=_flag(readings, "CoolerOn"),
        cooler_power=_number(readings, "CoolerPower"),
        dew_heater_on=_flag(readings, "DewHeaterOn"),
        gain=_integer(readings, "Gain"),
        offset=_integer(readings, "Offset"),
        usb_limit=_integer(readings, "USBLimit"),
        usb_limit_range=_range(wire, "USBLimitMin", "USBLimitMax"),
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
        tracking_modes=tuple(
            mode for mode in wire.get("TrackingModes") or () if isinstance(mode, str)
        ),
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
        filter_slots=_slots(wire.get("AvailableFilters")),
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
        brightness_range=_range(readings, "MinBrightness", "MaxBrightness"),
        supports_on_off=_flag(wire, "SupportsOnOff"),
        supports_open_close=_flag(wire, "SupportsOpenClose"),
    )


def map_weather(wire: dict) -> WeatherModel:
    """Every channel the wire carries; one this source cannot report arrives
    as `"NaN"` and reads `None`, poll after poll.
    """
    readings = _readings(wire)
    return WeatherModel(
        connected=_connected(wire),
        meta=_meta(wire),
        channels={
            channel: _number(readings, key)
            for key, channel in _WEATHER_CHANNELS.items()
            if key in wire
        },
    )


def map_safety_monitor(wire: dict) -> SafetyMonitorModel:
    return SafetyMonitorModel(
        connected=_connected(wire),
        meta=_meta(wire),
        is_safe=_flag(_readings(wire), "IsSafe"),
    )


def _fallback_index(key: str, position: int) -> int:
    """A synthetic index for an entry with no `Id`, offset per list so the
    two lists cannot collide.
    """
    return position + (_READONLY_INDEX_BASE if key == "ReadonlySwitches" else 0)


def map_switch(wire: dict) -> SwitchDeviceModel:
    """The channel list survives a disconnect; only `value` is a reading."""
    connected = _connected(wire)
    channels: list[SwitchChannelModel] = []
    for key, writable in (("WritableSwitches", True), ("ReadonlySwitches", False)):
        for position, entry in enumerate(wire.get(key) or ()):
            index = _integer(entry, "Id")
            channels.append(
                SwitchChannelModel(
                    # Namespaced per list: `position` restarts at 0 for the
                    # second list, so both lists' fallbacks would collide.
                    index=index
                    if index is not None
                    else _fallback_index(key, position),
                    name=_text(entry, "Name") or "",
                    description=_text(entry, "Description") or "",
                    value=_number(entry, "Value") if connected else None,
                    minimum=_number(entry, "Minimum"),
                    maximum=_number(entry, "Maximum"),
                    step_size=_number(entry, "StepSize"),
                    writable=writable,
                )
            )
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
    """All eleven blocks, mapped whether connected or not.

    `None` means the block was missing from the response.
    """

    def block(key: str, mapper: Any) -> Any:
        raw = wire.get(key)
        return mapper(raw) if isinstance(raw, dict) else None

    return EquipmentSnapshot(
        **{field: block(key, mapper) for field, key, mapper in _BLOCKS}
    )


def rig_utc_offset(wire: dict) -> timedelta | None:
    """The rig's UTC offset, from the mount's clock in `/equipment/info`.

    `None` while the mount is disconnected, which drops `Coordinates`.
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
    """The bracketed arcsecond total of `'Tot: 0.18 (0.29")'`."""
    match = _TOTAL_RMS_ARCSEC.search(raw) if isinstance(raw, str) else None
    return float(match.group(1)) if match else None


def map_frame(wire: dict, generation: str | None) -> Frame:
    """One saved frame, from `/image-history` or an `IMAGE-SAVE` push.

    `Date` and `Filename` identify it on both paths. Only calibration types
    lose readings; anything else, including an unclassifiable frame, keeps
    what the sentinel rules allow.
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
        min=_number(wire, "Min"),
        max=_number(wire, "Max"),
        rms_arcsec=rms,
        temperature=_number(wire, "Temperature"),
        gain=_integer(wire, "Gain"),
        offset=_integer(wire, "Offset"),
        focal_length=_number(wire, "FocalLength"),
        generation=generation,
    )


def map_image_save(payload: dict, generation: str | None) -> Frame | None:
    """The frame inside an `IMAGE-SAVE`; absent on a stored/replayed copy."""
    statistics = payload.get("ImageStatistics")
    if not isinstance(statistics, dict) or "Date" not in statistics:
        return None
    return map_frame(statistics, generation)


def _event_time(
    name: str, wire: dict, frame: Frame | None, offset: timedelta | None
) -> datetime:
    parsed = _timestamp(wire.get("Time"))
    if parsed is None:
        if frame is None:
            raise ValueError(f"event {name!r} carries neither a Time nor a frame")
        return frame.date  # the live socket IMAGE-SAVE has no Time of its own
    if parsed.tzinfo is not None:
        return parsed
    zone = next(
        (z for prefix, z in EVENT_TIMEZONES.items() if name.startswith(prefix)), "local"
    )
    if zone == "utc" or offset is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.replace(tzinfo=timezone(offset))


def _wait_end(name: str, wire: dict, offset: timedelta | None) -> datetime | None:
    """`TS-WAITSTART`'s `WaitEndTime`, the rig's local time, unlike the same
    payload's naive-UTC `Time`. A naive value with no known offset yields no
    reading, unlike `_event_time`'s UTC fallback.
    """
    if name != _SCHEDULER_WAIT_STARTED:
        return None
    parsed = _timestamp(wire.get("WaitEndTime"))
    if parsed is None or parsed.tzinfo is not None:
        return parsed
    return None if offset is None else parsed.replace(tzinfo=timezone(offset))


def map_event(
    wire: dict, generation: str | None, *, rig_offset: timedelta | None = None
) -> NinaEvent:
    """One socket push or `/event-history` entry.

    `rig_offset` resolves `ERROR-*`'s naive local times; without it they read
    as UTC, and replay corrects them once the mount's clock is known.
    """
    name = str(wire.get("Event", ""))
    frame = map_image_save(wire, generation)
    return NinaEvent(
        name=name,
        time=_event_time(name, wire, frame, rig_offset),
        data={
            key: nan_to_none(value)
            for key, value in wire.items()
            if key not in ("Event", "Time", "ImageStatistics")
            and not isinstance(value, (dict, list))
        },
        generation=generation,
        frame=frame,
        wait_end=_wait_end(name, wire, rig_offset),
    )


def _sequence_node(wire: dict, fallback: str) -> SequenceNode:
    name = _text(wire, "Name")
    iterations = _dig(wire, "Iterations")
    return SequenceNode(
        name=name if name is not None else fallback,
        status=_text(wire, "Status"),
        iterations=None if iterations is None else str(iterations),
        children=tuple(
            _sequence_node(child, key)
            for key in _SEQUENCE_CHILDREN
            for child in wire.get(key) or ()
            if isinstance(child, dict)
        ),
        attributes={
            key: nan_to_none(value)
            for key, value in wire.items()
            if key not in _SEQUENCE_OWN_KEYS and not isinstance(value, (dict, list))
        },
    )


def map_sequence(wire: list[dict] | None) -> SequenceNode | None:
    """`/sequence/json` answers a list of top-level nodes, so the tree gets a
    synthetic root. An unloaded sequence answers `""` and no tree.
    """
    if not isinstance(wire, list):
        return None
    return SequenceNode(
        name="Sequence",
        status=None,
        iterations=None,
        children=tuple(
            _sequence_node(node, "GlobalTriggers")
            for node in wire
            if isinstance(node, dict)
        ),
        attributes={},
    )


def _iterations(wire: dict, key: str) -> int | None:
    count = _integer(wire, key)
    return None if count == _IDLE_ITERATIONS_SENTINEL else count


def map_flats_status(wire: dict) -> FlatsStatus:
    """Flats started through the API only; others leave `-1`, read as no count."""
    return FlatsStatus(
        state=_text(wire, "State"),
        total_iterations=_iterations(wire, "TotalIterations"),
        completed_iterations=_iterations(wire, "CompletedIterations"),
    )


def _numeric(value: Any) -> float | None:
    """A bare wire value as a number; `_number` needs a dict to walk."""
    value = nan_to_none(value)
    return float(value) if _is_number(value) else None


def _positive(value: float | None) -> float | None:
    """0 is "never measured", and a fit can extrapolate past zero."""
    return value if value is not None and value > 0 else None


def _hfr(wire: dict, point: str) -> float | None:
    """One focus point's HFR."""
    return _positive(_number(wire, point, "Value"))


def _focus_curve(wire: dict) -> tuple[FocusPoint, ...]:
    """Every position the sweep visited, sorted by position.

    A row with no position is dropped; one whose measurement failed stays, at
    `None`, so a chart breaks its line there instead of drawing a chord across
    the failure.
    """
    points = wire.get("MeasurePoints")
    if not isinstance(points, list):
        return ()
    swept = []
    for point in points:
        position = _integer(point, "Position")
        if position is None:
            continue
        # `Error` is not `_positive`-guarded: zero spread is a real reading.
        swept.append(
            FocusPoint(
                position=position,
                value=_positive(_number(point, "Value")),
                error=_number(point, "Error"),
            )
        )
    return tuple(sorted(swept, key=lambda point: point.position))


_TERM = re.compile(
    r"^(?P<coefficient>[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
    r"(?:\s*\*\s*x(?:\^(?P<power>\d+))?)?$"
)


def _polynomial(equation: str) -> tuple[float, ...] | None:
    """`"y = 0.0003 * x^2 + -1.429 * x + 1671.6"` → `(0.0003, -1.429, 1671.6)`.

    Highest power first, zero-filled. None for a non-polynomial equation, such
    as a hyperbolic or gaussian fit. Split on `" + "`, not `"+"`: .NET writes a
    negative coefficient as `+ -1.429` and an exponent as `1E+05`, and only the
    former carries spaces.
    """
    _, _, terms = equation.partition("=")
    if not terms.strip():
        return None
    powers: dict[int, float] = {}
    for term in terms.split(" + "):
        match = _TERM.match(term.strip())
        if match is None:
            return None
        power = 0 if "x" not in term else int(match["power"] or 1)
        powers[power] = powers.get(power, 0.0) + float(match["coefficient"])
    return tuple(powers.get(power, 0.0) for power in range(max(powers), -1, -1))


def _curve_fits(wire: dict) -> tuple[CurveFit, ...]:
    """The fits this run used, each with its own R².

    N.I.N.A. sends every fitting it knows, with an empty equation for the
    ones unused; a non-empty equation is the filter. `RSquares` has no
    Gaussian entry, hence a lookup rather than a zip.
    """
    fittings = wire.get("Fittings")
    if not isinstance(fittings, dict):
        return ()
    squares = wire.get("RSquares")
    squares = squares if isinstance(squares, dict) else {}
    return tuple(
        CurveFit(
            name=name,
            equation=equation,
            coefficients=_polynomial(equation),
            r_squared=_numeric(squares.get(name)),
        )
        for name, equation in fittings.items()
        if isinstance(equation, str) and equation.strip()
    )


def _fit_minima(wire: dict) -> tuple[FitMinimum, ...]:
    """Every `Intersections` entry, keyed by the wire's own name: the
    non-trendline entry is named for whichever curve was fitted.
    """
    intersections = wire.get("Intersections")
    if not isinstance(intersections, dict):
        return ()
    found = []
    for name, point in intersections.items():
        position = _integer(point, "Position")
        if position is not None:
            found.append(
                FitMinimum(
                    name=name,
                    position=position,
                    value=_positive(_number(point, "Value")),
                )
            )
    return tuple(found)


def map_last_autofocus(wire: dict) -> AutoFocusReport | None:
    """The newest autofocus report, or `None` where the rig has never run one.

    `r_squared` is the minimum of `RSquares`, which sends `"NaN"` for fittings
    this run did not use — the worst fit actually computed.

    A CONTRASTDETECTION run's focus points are a contrast score, not pixels,
    so `hfr`/`fitted_hfr` are dropped; positions stay. `hfr` is the sweep's
    lowest measured point, unlike `fitted_hfr` (`CalculatedFocusPoint.Value`),
    which under a `TREND*` fitting averages in the trendline intersection and
    reads far below anything measured.
    """
    if not wire:
        return None
    method = _text(wire, "Method")
    is_hfr = method is None or method.upper() in _HFR_METHODS
    squares = wire.get("RSquares")
    computed = (
        [
            value
            for value in (_numeric(v) for v in (squares or {}).values())
            if value is not None
        ]
        if isinstance(squares, dict)
        else []
    )
    curve = _focus_curve(wire)
    measured = [point.value for point in curve if point.value is not None]
    return AutoFocusReport(
        timestamp=_timestamp(wire.get("Timestamp")),
        filter_name=_text(wire, "Filter") or None,
        temperature=_number(wire, "Temperature"),
        method=method,
        fitting=_text(wire, "Fitting"),
        autofocuser=_text(wire, "AutoFocuserName"),
        star_detector=_text(wire, "StarDetectorName"),
        position=_integer(wire, "CalculatedFocusPoint", "Position"),
        hfr=min(measured) if measured and is_hfr else None,
        fitted_hfr=_hfr(wire, "CalculatedFocusPoint") if is_hfr else None,
        curve=curve,
        fits=_curve_fits(wire),
        minima=_fit_minima(wire),
        measured_points=len(measured) or None,
        initial_position=_integer(wire, "InitialFocusPoint", "Position"),
        initial_hfr=_hfr(wire, "InitialFocusPoint") if is_hfr else None,
        duration_seconds=_timespan_seconds(wire.get("Duration")),
        r_squared=min(computed) if computed else None,
    )


def map_livestack_status(wire: dict | str) -> LivestackStatus:
    """The Response is the bare status string (`"Running"`), not the spec's
    `{"Status": "Running"}`, which is still read as a fallback.
    """
    raw = wire if isinstance(wire, str) else _text(wire, "Status") or ""
    return LivestackStatus(running=raw.lower() == "running", raw_state=raw)


def map_profile(wire: dict) -> ProfileSettings:
    """The allowlisted slice of `/profile/show`."""
    return ProfileSettings(
        focal_length=_number(wire, "TelescopeSettings", "FocalLength"),
        pixel_size=_number(wire, "CameraSettings", "PixelSize"),
        autofocus_timeout_seconds=_number(
            wire, "FocuserSettings", "AutoFocusTimeoutSeconds"
        ),
        r_squared_threshold=_number(wire, "FocuserSettings", "RSquaredThreshold"),
        min_minutes_after_meridian=_number(
            wire, "MeridianFlipSettings", "MinutesAfterMeridian"
        ),
        max_minutes_after_meridian=_number(
            wire, "MeridianFlipSettings", "MaxMinutesAfterMeridian"
        ),
        use_side_of_pier=_flag(wire, "MeridianFlipSettings", "UseSideOfPier"),
        site_latitude=_number(wire, "AstrometrySettings", "Latitude"),
        site_longitude=_number(wire, "AstrometrySettings", "Longitude"),
        site_elevation=_number(wire, "AstrometrySettings", "Elevation"),
    )

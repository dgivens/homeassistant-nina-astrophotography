"""Normalized models — THE CONTRACT.

Everything above api/ speaks in these and never in dicts. Two rules:

**"Observed" is defined by key presence, not by `Connected`.** `/equipment/info`
always emits all eleven device blocks, including a full `Dome` block on a rig
that has never had a dome — so a device key being present proves nothing. What
distinguishes them is that a disconnected device *drops* `DeviceId`, `Name` and
`DisplayName`, while one that has never existed never had them. A device is
observed once it has carried a `DeviceId`; the coordinator **latches** that,
because evaluating it per-poll would delete the device the moment it disconnects.

`None` means "no reading". Every sentinel the API uses in-band — "NaN", HFR 0 on
a calibration frame, -1 iterations, 24 hours to meridian flip on an untracked
mount — is already gone by the time a value lands here. If a sentinel reaches
derive.py, the seam is broken.

A device that is `None` has never been observed; a device present with
`connected=False` has been observed and is currently down. §5.2.2's first-sight
rule and §7.3's availability levels both need that distinction from one snapshot.

This module is closed to fields no entity, service, session.py or derive.py
consumes. A guideline, not a test — the enforcement needs an exemption list on
its first service-only field.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DeviceMeta:
    """Registry metadata. DriverVersion is the device's sw_version (§5.1).

    DriverInfo is deliberately absent: the rotator and flat panel both return
    the ASCOM template default, though the filter wheel returns real firmware.
    """

    name: str | None
    display_name: str | None
    description: str | None
    driver_version: str | None
    device_id: str | None


@dataclass(frozen=True, slots=True)
class CameraModel:
    """`gains` and `binning_modes` are per-camera select options, never hardcoded."""

    connected: bool
    meta: DeviceMeta
    temperature: float | None
    target_temperature: float | None
    cooler_on: bool | None
    cooler_power: float | None
    dew_heater_on: bool | None
    gain: int | None
    offset: int | None
    usb_limit: int | None
    camera_state: str | None
    is_exposing: bool | None
    pixel_size: float | None
    """Microns. Pairs with the profile focal length for image scale."""
    has_battery: bool | None
    battery: float | None
    can_set_temperature: bool | None
    gains: tuple[int, ...]
    binning_modes: tuple[str, ...]
    """Mode names as the driver spells them, e.g. "1x1"."""
    bin_x: int | None
    """Current binning. Image scale scales by it; `/image-history` omits it."""


@dataclass(frozen=True, slots=True)
class MountModel:
    """Reported coordinates are in the mount's own `epoch`, never J2000 (§3.7)."""

    connected: bool
    meta: DeviceMeta
    right_ascension: float | None
    """Hours."""
    declination: float | None
    """Degrees."""
    altitude: float | None
    azimuth: float | None
    sidereal_time: float | None
    """Local apparent sidereal time, hours."""
    tracking_enabled: bool | None
    tracking_mode: str | None
    tracking_modes: tuple[str, ...]
    """Per-mount; the select's options come from here."""
    at_park: bool | None
    at_home: bool | None
    side_of_pier: str | None
    time_to_meridian_flip: float | None
    """Hours. The 24-hour untracked sentinel is already `None` here."""
    can_slew_alt_az: bool | None
    epoch: str | None
    """The epoch the mount reports in — JNOW on this rig."""


@dataclass(frozen=True, slots=True)
class FocuserModel:
    connected: bool
    meta: DeviceMeta
    position: int | None
    """Steps."""
    temperature: float | None
    is_moving: bool | None
    max_step: int | None
    step_size: float | None
    temp_comp_available: bool | None
    temp_comp: bool | None


@dataclass(frozen=True, slots=True)
class FilterWheelModel:
    connected: bool
    meta: DeviceMeta
    selected_filter: str | None
    available_filters: tuple[str, ...]
    is_moving: bool | None


@dataclass(frozen=True, slots=True)
class GuiderModel:
    connected: bool
    meta: DeviceMeta
    state: str | None
    """Looping | LostLock | Guiding | Stopped | Calibrating. `switch.guider` is
    `state == "Guiding"`, which is why `sensor.guider_status` is retained
    (§5.2.3): during LostLock the switch reads off but guiding has not stopped.
    """
    rms_total: float | None
    rms_ra: float | None
    rms_dec: float | None
    pixel_scale: float | None
    """Arcsec per pixel, for converting RMS from pixels."""


@dataclass(frozen=True, slots=True)
class RotatorModel:
    connected: bool
    meta: DeviceMeta
    position: float | None
    """Sky position angle, degrees. Meaningful only when `synced` (§5.2.3)."""
    mechanical_position: float | None
    is_moving: bool | None
    reverse: bool | None
    synced: bool | None


@dataclass(frozen=True, slots=True)
class DomeModel:
    """Spec-derived and untested against hardware (§5.3.1)."""

    connected: bool
    meta: DeviceMeta
    azimuth: float | None
    shutter_status: str | None
    at_park: bool | None
    at_home: bool | None
    driver_following: bool | None
    """The driver's own slaving flag, distinct from N.I.N.A.'s `following`."""
    following: bool | None
    slewing: bool | None


@dataclass(frozen=True, slots=True)
class FlatDeviceModel:
    connected: bool
    meta: DeviceMeta
    cover_state: str | None
    light_on: bool | None
    brightness: float | None
    """Raw driver units, spanning `min_brightness`–`max_brightness` (§5.3.4).
    Not Home Assistant's 0–255.
    """
    min_brightness: float | None
    max_brightness: float | None
    supports_on_off: bool | None
    supports_open_close: bool | None


@dataclass(frozen=True, slots=True)
class WeatherModel:
    """`channels` is a map, not a field per channel, so §5.2.2 can ask which
    channels this source has ever produced. Keys are the wire's names
    lowercased with underscores: cloud_cover, dew_point, humidity, pressure,
    rain_rate, sky_brightness, sky_quality, sky_temperature, star_fwhm,
    temperature, wind_direction, wind_gust, wind_speed. A channel this source
    cannot report is absent, not `None`.
    """

    connected: bool
    meta: DeviceMeta
    channels: Mapping[str, float | None]


@dataclass(frozen=True, slots=True)
class SafetyMonitorModel:
    connected: bool
    meta: DeviceMeta
    is_safe: bool | None


@dataclass(frozen=True, slots=True)
class SwitchChannelModel:
    index: int
    name: str
    description: str
    value: float | None
    minimum: float | None
    maximum: float | None
    step_size: float | None
    writable: bool
    """False for `ReadonlySwitches`, which also carry no range."""

    @property
    def binary(self) -> bool:
        """A one-step range is an on/off channel, and belongs on `switch`."""
        if self.minimum is None or self.maximum is None or self.step_size is None:
            return False
        return self.maximum - self.minimum == self.step_size


@dataclass(frozen=True, slots=True)
class SwitchDeviceModel:
    connected: bool
    meta: DeviceMeta
    channels: tuple[SwitchChannelModel, ...]


@dataclass(frozen=True, slots=True)
class EquipmentSnapshot:
    """`None` is "never observed"; a model with `connected=False` is "down"."""

    camera: CameraModel | None
    mount: MountModel | None
    focuser: FocuserModel | None
    filter_wheel: FilterWheelModel | None
    guider: GuiderModel | None
    rotator: RotatorModel | None
    dome: DomeModel | None
    flat_device: FlatDeviceModel | None
    weather: WeatherModel | None
    safety_monitor: SafetyMonitorModel | None
    switch_device: SwitchDeviceModel | None


@dataclass(frozen=True, slots=True)
class Frame:
    """One saved sub. Identity is `(date, filename)` on all three paths (§4.4)."""

    date: datetime
    """Save time, not exposure start — subtract `exposure_time` for the latter."""
    filename: str
    target_name: str | None
    filter_name: str | None
    image_type: str | None
    exposure_time: float | None
    """Seconds. Integration time sums these, never count × nominal."""
    hfr: float | None
    """The calibration-frame 0 is already `None` here (§5.2.4)."""
    stars: int | None
    mean: float | None
    median: float | None
    std_dev: float | None
    rms: float | None
    """Total guide RMS for the exposure, parsed out of the wire's `RmsText`."""
    temperature: float | None
    gain: int | None
    offset: int | None
    focal_length: float | None
    generation: str | None
    """The `/application-start` value in force when the frame was received; the
    process boundary is a filter on this, never a clear (§3.6).
    """


@dataclass(frozen=True, slots=True)
class NinaEvent:
    """One event from the socket or from `/event-history` replay."""

    name: str
    time: datetime
    """Always offset-aware."""
    data: Mapping[str, Any]
    """The event's own scalar payload; empty for the many bare `{Event, Time}`."""
    generation: str | None
    frame: Frame | None = None
    """Set on `IMAGE-SAVE`, whose payload is a frame the socket already mapped."""


@dataclass(frozen=True, slots=True)
class TargetBreakdown:
    """Light-frame totals for one group — one row per target, or per filter.

    `SessionStats.by_filter` reuses this with the filter name in `name`: the two
    breakdowns carry identical fields, so a second class would differ only in
    its docstring.
    """

    name: str
    count: int
    integration_seconds: float
    hfr_mean: float | None
    """None when no light in this group reported an HFR."""


@dataclass(frozen=True, slots=True)
class AutoFocusState:
    """`AUTOFOCUS-STARTING` and `AUTOFOCUS-FINISHED` do not pair up — an
    ordinary night ends with one more STARTING than FINISHED, and there is no
    failure event. A run is a failure once it has gone unanswered for longer
    than the profile's autofocus timeout (§4.4).
    """

    last_success_at: datetime | None
    running_since: datetime | None
    """The newest STARTING with no FINISHED after it."""
    failed: bool


@dataclass(frozen=True, slots=True)
class SessionStats:
    """The session fold's result (§5.2.4).

    Every aggregate but `image_count` is over LIGHT frames only. Flats report a
    Mean ADU two orders of magnitude above a light's and an HFR of zero, which
    is what made `Last Image Mean ADU` read 33,139 after a dawn flat run on
    1.4.4.
    """

    session_start: datetime | None
    """None only when nothing has been observed and no clock was supplied."""
    image_count: int
    """Every frame in the session window, calibration included."""
    light_count: int
    integration_seconds: float
    """Summed exposures, never count × nominal."""
    hfr_mean: float | None
    hfr_best: float | None
    """The smallest HFR — a tighter star is a better one."""
    hfr_worst: float | None
    star_count_mean: float | None
    last_frame: Frame | None
    """The newest LIGHT, never the newest frame."""
    by_target: tuple[TargetBreakdown, ...]
    """Sorted by name."""
    by_filter: tuple[TargetBreakdown, ...]
    """Sorted by name; the filter name sits in `TargetBreakdown.name`."""
    autofocus: AutoFocusState


@dataclass(frozen=True, slots=True)
class SequenceNode:
    """One node of `/sequence/json`, normalized so derive.py can walk it purely."""

    name: str
    status: str | None
    iterations: str | None
    """The wire's progress text, e.g. "3/10"; parsed in derive.py."""
    children: tuple[SequenceNode, ...]
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class FlatsStatus:
    """Observes only flats started through the API — Target Scheduler Flats run
    invisibly to it and leave `-1` iterations, which arrive here as `None`.
    """

    state: str | None
    total_iterations: int | None
    completed_iterations: int | None


@dataclass(frozen=True, slots=True)
class LivestackStatus:
    running: bool
    raw_state: str
    """The status string as sent; case varies from the spec's enum (§5.3.2)."""


@dataclass(frozen=True, slots=True)
class VersionInfo:
    api_version: str | None
    nina_version: str | None


@dataclass(frozen=True, slots=True)
class ProfileSettings:
    """The allowlisted slice of `/profile/show` (§8.3)."""

    focal_length: float | None
    """Millimetres."""
    pixel_size: float | None
    """Microns."""
    autofocus_timeout_seconds: float | None
    """The window an `AUTOFOCUS-STARTING` has to finish in before it is a
    failure (§4.4).
    """
    r_squared_threshold: float | None
    min_minutes_after_meridian: float | None
    max_minutes_after_meridian: float | None
    use_side_of_pier: bool | None

"""Normalized models: the contract everything above `api/` speaks, never dicts.

`None` means no reading. Every in-band sentinel — `"NaN"`, a calibration
frame's HFR 0, -1 iterations, an untracked mount's 24 h to flip — is already
`None` here.

A device that is `None` has never been observed; one with `connected=False` is
down. A down device carries only `connected`, `meta` and its capability flags:
a disconnected driver answers template defaults for every reading.

Add a field only when something consumes it.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

ShutterState = Literal["open", "closed", "opening", "closing", "error"]
"""ASCOM's `ShutterState`, as N.I.N.A. reports it without its `Shutter` prefix."""


@dataclass(frozen=True, slots=True)
class DeviceMeta:
    """Device registry metadata; `driver_version` is the device's sw_version.

    No `DriverInfo`: many drivers return the ASCOM template default.
    """

    name: str | None
    display_name: str | None
    description: str | None
    driver_version: str | None
    device_id: str | None


@dataclass(frozen=True, slots=True)
class CameraModel:
    """A camera; `gains` and `binning_modes` are its own."""

    connected: bool
    meta: DeviceMeta
    temperature: float | None
    target_temperature: float | None
    cooler_on: bool | None
    cooler_power: float | None
    dew_heater_on: bool | None
    gain: int | None
    gain_range: tuple[float, float] | None
    """`(GainMin, GainMax)`, per camera; `None` while the camera is down."""
    offset: int | None
    usb_limit: int | None
    usb_limit_range: tuple[float, float] | None
    """`(USBLimitMin, USBLimitMax)`, per camera."""
    camera_state: str | None
    is_exposing: bool | None
    pixel_size: float | None
    """Microns."""
    exposure_range: tuple[float, float] | None
    """`(ExposureMin, ExposureMax)` in seconds, per camera; `None` while the
    camera is down."""
    has_battery: bool | None
    battery: float | None
    """Percent; `None` for a camera without one."""
    can_set_temperature: bool | None
    gains: tuple[int, ...]
    binning_modes: tuple[str, ...]
    """Mode names as the driver spells them, e.g. "1x1"."""
    bin_x: int | None
    """Current binning, which `/image-history` frames do not carry."""


@dataclass(frozen=True, slots=True)
class MountModel:
    """A mount. Coordinates are in its own `epoch`, not necessarily J2000."""

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
    """This mount's own."""
    at_park: bool | None
    at_home: bool | None
    side_of_pier: str | None
    time_to_meridian_flip: float | None
    """Hours; `None` while untracked."""
    can_slew_alt_az: bool | None
    epoch: str | None
    """The epoch the mount reports in, usually JNOW."""


@dataclass(frozen=True, slots=True)
class FocuserModel:
    connected: bool
    meta: DeviceMeta
    position: int | None
    """Steps."""
    temperature: float | None
    is_moving: bool | None
    step_size: float | None
    temp_comp_available: bool | None
    temp_comp: bool | None


@dataclass(frozen=True, slots=True)
class FilterWheelModel:
    connected: bool
    meta: DeviceMeta
    selected_filter: str | None
    available_filters: tuple[str, ...]
    """Names, in the wheel's order."""
    filter_slots: Mapping[str, int]
    """Name → the wheel's own `Id`, which `change-filter` takes. Slots need not
    be numbered in list order.
    """
    filter_ids: frozenset[int]
    """Every slot's `Id`, including slots that share a name or have none."""
    is_moving: bool | None


@dataclass(frozen=True, slots=True)
class GuiderModel:
    connected: bool
    meta: DeviceMeta
    state: str | None
    """Looping | Paused | LostLock | Guiding | Stopped | Calibrating.

    `Paused` comes from PHD2's `Paused` event and ends on the next `GuideStep`
    (`Guiding`) or `LoopingExposuresStopped` (`Stopped`).
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
    """Sky position angle, degrees. Meaningful only when `synced`."""
    mechanical_position: float | None
    is_moving: bool | None
    reverse: bool | None
    synced: bool | None


@dataclass(frozen=True, slots=True)
class DomeModel:
    """A dome, validated against a simulator and not yet against hardware.

    `slewing` is the azimuth only on the simulator: its shutter moves with
    `slewing` false. A real driver may count the shutter too.
    """

    connected: bool
    meta: DeviceMeta
    azimuth: float | None
    shutter_status: ShutterState | None
    """`None` for `ShutterNone`, which a driver with no shutter reports."""
    at_park: bool | None
    at_home: bool | None
    driver_following: bool | None
    """The driver's own slaving flag, distinct from N.I.N.A.'s `following`."""
    following: bool | None
    synchronized: bool | None
    """The slit is on the scope; `None` unless following, since N.I.N.A. keeps
    the last value after following stops."""
    slewing: bool | None
    can_set_shutter: bool | None
    can_set_azimuth: bool | None
    """Also what following needs: N.I.N.A. follows by slewing the dome."""
    can_park: bool | None
    can_find_home: bool | None


@dataclass(frozen=True, slots=True)
class FlatDeviceModel:
    connected: bool
    meta: DeviceMeta
    cover_state: str | None
    light_on: bool | None
    brightness: float | None
    """Driver units, spanning `brightness_range`."""
    brightness_range: tuple[float, float] | None
    """`(MinBrightness, MaxBrightness)`; `None` when the driver reports no
    usable range, as a disconnected panel's `0 / 0` does."""
    supports_on_off: bool | None
    supports_open_close: bool | None


@dataclass(frozen=True, slots=True)
class WeatherModel:
    """A weather source.

    `channels` holds every wire channel, keyed snake_case (`cloud_cover`,
    `dew_point`, `sky_brightness`, …); `None` is a `"NaN"`, which is also how a
    channel the source cannot report looks.
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
        """Whether the range is exactly one step, so on/off.

        A disconnected device's `Min 0 / Max 0 / Step 0` is not.
        """
        if self.minimum is None or self.maximum is None or self.step_size is None:
            return False
        return self.step_size > 0 and self.maximum - self.minimum == self.step_size


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
    """One saved frame, identified by `(date, filename)`."""

    date: datetime
    """Save time; the exposure started `exposure_time` earlier."""
    filename: str
    target_name: str | None
    filter_name: str | None
    image_type: str | None
    exposure_time: float | None
    """Seconds."""
    hfr: float | None
    """`None` on a calibration frame."""
    stars: int | None
    mean: float | None
    median: float | None
    std_dev: float | None
    min: float | None
    max: float | None
    rms_arcsec: float | None
    """Total guide RMS over the exposure, arcseconds; `None` when unguided."""
    temperature: float | None
    gain: int | None
    offset: int | None
    focal_length: float | None
    generation: str | None
    """The `/application-start` in force when the frame arrived."""

    @property
    def identity(self) -> tuple[datetime, str]:
        return (self.date, self.filename)


@dataclass(frozen=True, slots=True)
class NinaEvent:
    """One event from the socket or from `/event-history` replay."""

    name: str
    time: datetime
    """Always offset-aware."""
    data: Mapping[str, Any]
    """The event's own scalar payload, as forwarded to the event bus."""
    generation: str | None
    frame: Frame | None = None
    """Set on `IMAGE-SAVE`."""
    wait_end: datetime | None = None
    """Set on `TS-WAITSTART`: when Target Scheduler expects to resume. Not in
    `data`, which keeps the wire's string for automations.
    """


@dataclass(frozen=True, slots=True)
class TargetBreakdown:
    """Light-frame totals for one target, or one filter."""

    name: str
    count: int
    integration_seconds: float
    hfr_mean: float | None
    """None when no light in this group reported an HFR."""


@dataclass(frozen=True, slots=True)
class AutoFocusState:
    """Autofocus as the events show it.

    STARTING and FINISHED do not pair up, and there is no failure event. A
    run unanswered past the profile's timeout failed; one interrupted inside
    it was aborted.
    """

    last_finished_at: datetime | None
    """The newest FINISHED, which a rejected run also sends."""
    running_since: datetime | None
    """The newest STARTING with nothing answering it yet."""
    failed: bool


@dataclass(frozen=True, slots=True)
class FocusPoint:
    """One position the autofocus sweep visited.

    `value` is HFR in pixels under STARHFR, a contrast score under
    CONTRASTDETECTION; `AutoFocusReport.method` says which.
    """

    position: int
    value: float | None
    """None where no usable stars were found, often at a sweep's ends."""
    error: float | None
    """The spread of HFR across the frame's stars, which N.I.N.A. draws as an
    error bar: a sign of tilt or curvature, not uncertainty in the point. 0
    means about one star was detected.
    """


@dataclass(frozen=True, slots=True)
class FitMinimum:
    """Where one of the report's fits puts best focus.

    `name` is the wire's key, and which keys arrive depends on the
    autofocuser. Built-in N.I.N.A. reports `TrendLineIntersection`,
    `HyperbolicMinimum`, `QuadraticMinimum` and `GaussianMaximum` whatever it
    fitted. Hocus Focus fits trend lines on every run to end its sweep, so it
    reports `TrendLineIntersection` beside the minimum of the curve its
    fitting uses, if any. `TrendLineIntersection`'s value lands far below any
    measured star, so a chart must not scale to it.
    """

    name: str
    position: int
    value: float | None
    used: bool
    """Whether the run's final focus point is built from this minimum, which
    `fitting` decides; a contrast-detection run focuses at `GaussianMaximum`.
    Independent of R² and of `CurveFit.judged`: that gaussian is used, though
    its fit is not judged.
    """


HyperbolaBlend = Literal["ramp", "logistic"]
"""How an asymmetric hyperbola weights its left branch (see `Hyperbola`)."""


@dataclass(frozen=True, slots=True)
class Hyperbola:
    """A hyperbolic fit, in one form for every autofocuser's model.

    `y = y0 + slope·u + w·(a/b)·√(u² + b²) + (1 − w)·(a/c)·√(u² + c²)`, with
    `u = x − x0` and `w` the left branch's weight: 1 with no `blend`, where
    `c` is `b`; `clamp(−u / blend_width, 0, 1)` for `ramp`; and
    `1 / (1 + e^(u / blend_width))` for `logistic`.

    Built-in N.I.N.A.'s `a·cosh(asinh((x0 − x) / b))` is the symmetric case
    with `y0` and `slope` 0. Hocus Focus adds the offset `y0`, and its
    asymmetric models a tilt or a separate right branch. Its minimum is the
    run's `HyperbolicMinimum`, which a tilt (`slope`) moves off `x0`; a blend
    does not, since both branches equal `a` only at `x0`.
    """

    x0: float
    y0: float
    a: float
    b: float
    """Never 0."""
    c: float
    """The right branch's semi-axis; equal to `b` without a blend. Never 0."""
    slope: float
    blend: HyperbolaBlend | None
    blend_width: float | None
    """Positive wherever `blend` is set."""


@dataclass(frozen=True, slots=True)
class Gaussian:
    """A contrast run's fit: `y = amplitude·e^(−(x − mean)² / (2·sigma²)) +
    offset`, peaking at `mean`.
    """

    amplitude: float
    mean: float
    sigma: float
    """Never 0."""
    offset: float


@dataclass(frozen=True, slots=True)
class CurveFit:
    """One curve the run computed through the sweep; others are omitted.

    At most one of `coefficients`, `hyperbola` and `gaussian` is set, and none
    where the equation is in a form the mapper does not recognise.
    """

    name: str
    """`Quadratic`, `LeftTrend`, `RightTrend`, `Hyperbolic` or `Gaussian`."""
    equation: str
    """As the autofocuser wrote it; the only record for an unrecognised form."""
    coefficients: tuple[float, ...] | None
    """Highest power first: `(a, b, c)` is `a·x² + b·x + c`. None where the
    equation is not a polynomial. The trend lines exclude the lowest point, so
    re-fitting the curve will not reproduce them.
    """
    hyperbola: Hyperbola | None
    gaussian: Gaussian | None
    r_squared: float | None
    """This fit's own R², unlike the worst judged one in `AutoFocusReport`."""
    judged: bool
    """Whether this curve's R² counts against the profile's threshold, which
    `fitting` decides. A hyperbolic run also computes trend lines that do not
    count, and no R² check applies to a contrast run's gaussian.
    """


@dataclass(frozen=True, slots=True)
class AutoFocusReport:
    """The newest `/equipment/focuser/last-af`.

    Built-in N.I.N.A. writes a report per attempt, Hocus Focus one per run,
    rejected runs included. It carries no failure flag, so a rejected run
    overwrites the last good one; only `r_squared` against the profile's
    `RSquaredThreshold`, and `outside_sweep`, judge it. It survives a
    restart, so date it against the session before use.
    """

    timestamp: datetime | None
    filter_name: str | None
    temperature: float | None
    """Focuser temperature at the run."""
    method: str | None
    """`STARHFR` or `CONTRASTDETECTION`."""
    fitting: str | None
    """Which curve was fitted: `TRENDPARABOLIC`, `HYPERBOLIC`, and so on."""
    autofocuser: str | None
    """Which autofocus routine ran. With `star_detector`, says whether two
    runs' HFRs are on the same scale.
    """
    star_detector: str | None
    position: int | None
    """The focus point the run's fitting chose, rounded as the autofocuser
    rounds it to move there. A rejected run never took it: the focuser goes
    back to `initial_position`.
    """
    hfr: float | None
    """The lowest HFR measured in the sweep, which compares run to run.

    Quantized by the sweep's step. None under CONTRASTDETECTION.
    """
    fitted_hfr: float | None
    """`CalculatedFocusPoint.Value`, an artifact of the fit. `TRENDLINES` uses
    the trend-line intersection, far below any measured star; `PARABOLIC` and
    `HYPERBOLIC` the curve's minimum alone; `TRENDPARABOLIC` and
    `TRENDHYPERBOLIC` the mean of the two. None under CONTRASTDETECTION,
    whose focus point is a contrast score, or where the fit put it at or
    below zero.
    """
    curve: tuple[FocusPoint, ...]
    """Every position the sweep visited, ascending, including those that
    measured nothing. Not necessarily centred on `initial_position`.
    """
    fits: tuple[CurveFit, ...]
    """The curves fitted through `curve`. Which points each used is
    undocumented, so a card cannot re-derive them.
    """
    minima: tuple[FitMinimum, ...]
    """Every `Intersections` entry with a position, including ones the
    fitting ignores, which carry `used` False (see `FitMinimum`).
    `position` and `fitted_hfr` are the point the fitting chose.
    """
    measured_points: int | None
    """How many of `curve`'s positions measured something."""
    initial_position: int | None
    """Where the focuser was before the run."""
    initial_hfr: float | None
    """The HFR measured at `initial_position`."""
    duration_seconds: float | None
    """Time since the run started, earlier attempts included."""
    r_squared: float | None
    """The worst R² among the judged curves, which is what a threshold
    judges. `None` if none of them reports one.
    """
    outside_sweep: bool
    """`position` lies outside the positions `curve` visited, which the
    autofocuser rejects whatever the R² threshold. The sweep's ends are
    inside it. N.I.N.A. checks every method, but Hocus Focus checks only
    STARHFR, so its contrast-detection runs are never flagged.
    """


@dataclass(frozen=True, slots=True)
class SessionStats:
    """The session fold's result. Every aggregate but `image_count` is over
    lights only.
    """

    session_start: datetime | None
    """None only when nothing has been observed and no clock was supplied."""
    image_count: int
    """Every frame in the session window, calibration included."""
    light_count: int
    integration_seconds: float
    hfr_mean: float | None
    hfr_best: float | None
    """The smallest HFR."""
    hfr_worst: float | None
    star_count_mean: float | None
    last_frame: Frame | None
    """The newest light."""
    recent_lights: tuple[Frame, ...]
    """The newest lights in the window, bounded, oldest first."""
    by_target: tuple[TargetBreakdown, ...]
    """Sorted by name."""
    by_filter: tuple[TargetBreakdown, ...]
    """Sorted by name; the filter name sits in `TargetBreakdown.name`."""
    autofocus: AutoFocusState


@dataclass(frozen=True, slots=True)
class SequenceNode:
    """One node of `/sequence/json`."""

    name: str
    status: str | None
    iterations: str | None
    """The wire's progress text, e.g. "3/10"."""
    target_name: str | None
    refocus_temperature: float | None
    """°C of focuser drift past which an "AF After Temperature Change"
    trigger refocuses; `None` on every other node."""
    children: tuple[SequenceNode, ...]


@dataclass(frozen=True, slots=True)
class FlatsStatus:
    """Flats started through the API; others leave it `Finished`, with `None`
    iterations.
    """

    state: str | None
    total_iterations: int | None
    completed_iterations: int | None


@dataclass(frozen=True, slots=True)
class StackState:
    """The stack `STACK-UPDATED` last reported: the target and filter
    `/livestack/image/{target}/{filter}` fetches.
    """

    target: str
    filter_name: str
    updated: datetime


@dataclass(frozen=True, slots=True)
class FlipReading:
    """`TimeToMeridianFlip` as last read while the mount tracked, and when."""

    hours: float
    read_at: datetime


@dataclass(frozen=True, slots=True)
class MeridianFlip:
    """A meridian flip N.I.N.A. has begun and not yet finished."""

    started: datetime
    """`MOUNT-BEFORE-FLIP`, raised before the guider stops and the wait."""
    slews_at: datetime | None
    """When the wait with tracking off ends and the slew begins; `None` with
    no fresh tracked reading or no profile window to place it."""


@dataclass(frozen=True, slots=True)
class LivestackStatus:
    running: bool
    raw_state: str
    """The status string as sent; its case differs from the spec's enum."""


@dataclass(frozen=True, slots=True)
class VersionInfo:
    api_version: str | None
    nina_version: str | None


@dataclass(frozen=True, slots=True)
class ProfileSettings:
    """The allowlisted slice of `/profile/show`."""

    focal_length: float | None
    """Millimetres."""
    pixel_size: float | None
    """Microns."""
    autofocus_timeout_seconds: float | None
    """How long an autofocus may run before it counts as failed."""
    r_squared_threshold: float | None
    """The R² an autofocus fit must reach. `None` where the profile sets 0 or
    below, which turns the check off.
    """
    min_minutes_after_meridian: float | None
    max_minutes_after_meridian: float | None
    use_side_of_pier: bool | None
    site_latitude: float | None
    """Degrees north, where the rig is. N.I.N.A.'s configured site rather than
    the mount's, which needs the mount connected and some drivers report as 0.
    """
    site_longitude: float | None
    """Degrees east."""
    site_elevation: float | None
    """Metres."""
    # N.I.N.A.'s own dome interlocks, which it enforces whatever Home
    # Assistant does.
    dome_close_on_unsafe: bool | None
    dome_refuse_unsafe_shutter_move: bool | None
    dome_refuse_open_without_safety_monitor: bool | None
    dome_refuse_unpark_while_shut: bool | None
    dome_park_mount_before_shutter_move: bool | None
    dome_park_before_shutter_move: bool | None
    dome_find_home_before_park: bool | None

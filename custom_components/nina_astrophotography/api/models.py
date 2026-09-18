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
A down device carries `connected`, `meta` and its capability flags and nothing
else: a disconnected driver answers zeros and template defaults for every
reading, and those are artefacts, not measurements.

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
    usb_limit_min: int | None
    usb_limit_max: int | None
    """Per-camera; `number.camera_usb_limit`'s range comes from here."""
    camera_state: str | None
    is_exposing: bool | None
    pixel_size: float | None
    """Microns. Pairs with the profile focal length for image scale."""
    has_battery: bool | None
    battery: float | None
    """Percent. A camera without a battery reports -1, which is `None` here."""
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
    step_size: float | None
    temp_comp_available: bool | None
    temp_comp: bool | None


@dataclass(frozen=True, slots=True)
class FilterWheelModel:
    connected: bool
    meta: DeviceMeta
    selected_filter: str | None
    available_filters: tuple[str, ...]
    """Names, in the order the wheel reports them — the select's options."""
    filter_slots: Mapping[str, int]
    """Name → the wheel's own `Id`, which is what `change-filter` takes.

    Carried rather than derived from the option's position: a wheel is free to
    number its slots non-contiguously, and a filter whose `Name` is not a
    string drops out of the name list and shifts every position after it. A
    wrong slot changes to the wrong filter, answers `Success: true`, and costs
    the sub — the disagreement only shows up on the next poll.
    """
    is_moving: bool | None


@dataclass(frozen=True, slots=True)
class GuiderModel:
    connected: bool
    meta: DeviceMeta
    state: str | None
    """Looping | LostLock | Guiding | Stopped | Calibrating. `switch.guider` is
    on for every state but `Stopped` — the guider is running — which is why
    `sensor.guider_status` is retained (§5.2.3): the switch cannot tell a lost
    lock from a settled one.
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
    temperature, wind_direction, wind_gust, wind_speed. Every wire channel is
    present; `None` means the source emitted `"NaN"` for it — which is how a
    channel this source cannot report looks, poll after poll.
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
        """A one-step range is an on/off channel, and belongs on `switch`.

        A zero step is not one step: `Min 0 / Max 0 / Step 0` satisfies the
        arithmetic and is what a DISCONNECTED device reports, so without the
        guard it mints a switch whose on and off values are both 0.
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
    min: float | None
    max: float | None
    rms_arcsec: float | None
    """Total guide RMS over the exposure, in arcseconds — comparable across
    rigs, the same convention as `GuiderModel.rms_total`. `RmsText` carries the
    pixel figure first and the arcsecond figure in brackets; a total of 0 is no
    guiding, not perfect guiding, and is already `None` here.
    """
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
    wait_end: datetime | None = None
    """Set on `TS-WAITSTART`: when Target Scheduler expects to resume.

    Typed here rather than left in `data` because `data` is forwarded verbatim
    onto the Home Assistant event bus, where a datetime would replace the wire
    string automations read.
    """


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
    than the profile's autofocus timeout (§4.4); a run interrupted inside that
    window — the sky turning unsafe, the sequence ending, a park, a disconnect,
    or the sequencer moving on to the next exposure — was aborted, not failed.
    """

    last_finished_at: datetime | None
    """The newest FINISHED. A FINISHED is the report, not a verdict: an
    autofocus that found no focus still reports, so the verdict comes from
    `AutoFocusReport.r_squared` against the profile's `RSquaredThreshold`.
    """
    running_since: datetime | None
    """The newest STARTING with nothing answering it yet."""
    failed: bool


@dataclass(frozen=True, slots=True)
class FocusPoint:
    """One position the autofocus sweep visited.

    `value` is HFR in pixels only under a STARHFR run; a CONTRASTDETECTION run
    measures a contrast score at the same positions, and
    `AutoFocusReport.method` is what says which.
    """

    position: int
    value: float | None
    """None where the sweep measured nothing here — the star detector found no
    usable stars, which out at the ends of a sweep means the stars bloated past
    its cut. The position is kept so the sweep's real range survives, and so a
    chart breaks its line rather than drawing a chord across the failure.
    """
    error: float | None
    """The spread of HFR ACROSS THE STARS in that frame, which N.I.N.A.'s own
    chart draws as an error bar.

    Not the uncertainty on the V: with hundreds of stars the error on the mean
    is smaller by √N. A fat bar means the field has a spread of star sizes —
    tilt, field curvature, elongation — so it reads as "check the optics",
    never as "distrust this point". A 0 on a measured point is near enough one
    detected star, which is a run to distrust.
    """


@dataclass(frozen=True, slots=True)
class FitMinimum:
    """Where one of the report's fits puts best focus.

    `name` is the wire's own key, because the second entry is named after
    whichever curve the profile fitted — `QuadraticMinimum` on a TRENDPARABOLIC
    run — so it is read as "the entry that is not `TrendLineIntersection`"
    rather than by a literal name. (The published spec calls it
    `HyperbolicMinimum`; the rig disagrees, and the rig wins.)

    `TrendLineIntersection`'s value is not a star size a system can produce:
    the two trend lines extrapolate the V's wings past each other, so it lands
    far under anything measured (0.333 px on a captured run). A chart must not
    let it set the y axis.
    """

    name: str
    position: int
    value: float | None


@dataclass(frozen=True, slots=True)
class CurveFit:
    """One curve N.I.N.A. fitted through the sweep, as a chart would draw it.

    Only fits the run actually used are carried; N.I.N.A. sends an empty
    equation for the rest.
    """

    name: str
    """`Quadratic`, `LeftTrend`, `RightTrend`, `Hyperbolic` or `Gaussian`."""
    equation: str
    """As N.I.N.A. wrote it. Kept because `coefficients` is a best-effort parse
    of a form only the polynomial fits have been observed in — for anything
    else this string is the only record of what the fit actually was.
    """
    coefficients: tuple[float, ...] | None
    """Highest power first, so `(a, b, c)` means `a·x² + b·x + c` — evaluate it
    and the fitted line plots. None where the equation is not a polynomial.

    The trend lines are fitted to the points on each side EXCLUDING the lowest
    measured one, so re-fitting the published curve in a chart will not
    reproduce them.
    """
    r_squared: float | None
    """This fit's own R², which is what labels this line in a legend.

    `AutoFocusReport.r_squared` is the WORST across the run, which is the right
    number for a pass/fail threshold and the wrong one for a chart.
    """


@dataclass(frozen=True, slots=True)
class AutoFocusReport:
    """The newest `/equipment/focuser/last-af`.

    **Success only, and not even that.** The report file is written per
    ATTEMPT, before the verdict, and the endpoint returns the newest — so a run
    N.I.N.A. rejected overwrites the last good one carrying no failure flag.
    `r_squared` against the profile's `RSquaredThreshold` is the only judge
    there is (§4.4).

    The report also survives a restart, so it must be dated against the session
    before it is believed: a bad run from three nights ago is not tonight's
    problem.
    """

    timestamp: datetime | None
    filter_name: str | None
    temperature: float | None
    """Focuser temperature at the run — the other half of a temp-comp slope."""
    method: str | None
    """`STARHFR` or `CONTRASTDETECTION`."""
    fitting: str | None
    """Which curve was fitted: `TRENDPARABOLIC`, `HYPERBOLIC`, and so on."""
    autofocuser: str | None
    """Which autofocus routine ran; `star_detector` measured the stars.

    Both are plugin settings — Hocus Focus rather than the built-in detector,
    say — and HFR is on a different SCALE per detector, so two readings taken
    under different ones are not comparable however close their numbers look.
    """
    star_detector: str | None
    position: int | None
    """Where the run left the focuser."""
    hfr: float | None
    """The LOWEST HFR measured across the sweep, and the only comparable one.

    Measured, so it is independent of the fitting the profile selects, which
    `fitted_hfr` is not. Quantized by the sweep's step: the curve's true
    minimum lies between two measured points.

    None for a CONTRASTDETECTION run, whose focus points carry a contrast
    score rather than pixels.
    """
    fitted_hfr: float | None
    """`CalculatedFocusPoint.Value` — a curve artifact, not an achieved HFR.

    Under a `TREND*` fitting N.I.N.A. sets it to the MEAN of the trendline
    intersection and the quadratic or hyperbolic minimum, and the trendline
    intersection extrapolates the V's wings to a size no star on the system
    can reach — so it reads far below anything the camera measured (1.09 px
    against a best measured 1.55 on one captured run). Its bias also changes
    with the profile's `AutoFocusCurveFitting`, which is why it is a
    diagnostic and `hfr` is what a statistic keys on.
    """
    curve: tuple[FocusPoint, ...]
    """The sweep itself, ascending in focuser position — the V to plot.

    Every position the sweep visited, including the ones that measured nothing
    (`FocusPoint.value` None), so its length is what the run cost and
    `measured_points` is what it got. Empty rather than None where the report
    has no `MeasurePoints`: an absent sweep and an empty one draw the same.

    The sweep is NOT necessarily centred on `initial_position` — one captured
    run starts at the third of nine points — so nothing may assume the
    starting marker lands mid-curve.
    """
    fits: tuple[CurveFit, ...]
    """The curves N.I.N.A. fitted through `curve`, for a chart to overlay.

    Empty where the report names none. A card cannot re-derive these from the
    measured points: which points each fit used is undocumented and varies with
    the fitting and the autofocus routine.
    """
    minima: tuple[FitMinimum, ...]
    """Every entry of `Intersections` — the markers N.I.N.A.'s own chart draws.

    `position`/`fitted_hfr` is where the run ended up, and it is the
    componentwise MEAN of these two, so they are the explanation behind it:
    when a run goes wrong, which one dragged the result is the diagnostic.
    """
    measured_points: int | None
    """How many of the sweep's positions actually measured something.

    Less than `len(curve)` where frames failed; `duration_seconds` bought the
    failures too.
    """
    initial_position: int | None
    """Where the focuser was before the run — `position` less this is the move."""
    initial_hfr: float | None
    """The measured HFR at `initial_position`, under `hfr`'s method rule."""
    duration_seconds: float | None
    """What the run cost the session, from the report's .NET TimeSpan.

    Per ATTEMPT, as the whole report is: a run that failed twice before it
    succeeded cost the night more than this says.
    """
    r_squared: float | None
    """The WORST fit in the report, which is what a threshold must judge.

    N.I.N.A. computes an R² only for the fittings it actually used and sends
    `"NaN"` for the rest — a `TRENDPARABOLIC` run carries Quadratic, LeftTrend
    and RightTrend and a `"NaN"` Hyperbolic — so taking the minimum of what
    survives the `"NaN"` rule needs no table of which fitting uses which.
    """


@dataclass(frozen=True, slots=True)
class SessionStats:
    """The session fold's result (§5.2.4).

    Every aggregate but `image_count` is over LIGHT frames only. Flats report a
    Mean ADU two orders of magnitude above a light's and an HFR of zero, which
    is what made `Last Image Mean ADU` read 33,139 after a dawn flat run.
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
class StackState:
    """The stack `STACK-UPDATED` last reported.

    `/livestack/image/{target}/{filter}` needs a pair to fetch, and the event
    names the one currently accumulating. `/livestack/image/available` lists
    every pair the plugin holds without saying which is current, and the event
    is already folded, so nothing extra is polled for this.

    `StackCount` rides the same event and is deliberately absent: nothing
    consumes it, and this module is closed to fields nothing consumes.
    """

    target: str
    filter_name: str
    updated: datetime


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

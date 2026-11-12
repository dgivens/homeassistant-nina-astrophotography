# Entity reference

How the integration's entities behave, for anyone writing automations or
cards against them. The [README](../README.md) covers installation and the
short list of things that can hurt you; this covers the rest.

Entity ids below are written `<domain>.<instance>_<name>`. With the default
instance name `N.I.N.A.` the prefix is `n_i_n_a`, so
`binary_sensor.<instance>_imaging` is `binary_sensor.n_i_n_a_imaging`.

## Contents

- [Devices](#devices)
- [Availability](#availability)
- [Entities by device](#entities-by-device)
- [Sessions](#sessions)
- [Is the rig working?](#is-the-rig-working)
- [The imaging stall alert blueprint](#the-imaging-stall-alert-blueprint)
- [Weather](#weather)
- [Flats](#flats)
- [Autofocus](#autofocus)
- [The autofocus curve attributes](#the-autofocus-curve-attributes)
- [Other attributes](#other-attributes)
- [Error events](#error-events)
- [Dome](#dome)
- [Livestack](#livestack)

## Devices

Each config entry creates one hub device and one child device per type of
equipment: Camera, Mount, Focuser, Filter Wheel, Guider, Rotator, Dome, Flat
Panel, Weather, Safety Monitor and Switch. The driver's name and version are on
the device page, not in entity attributes.

A device is created the first time N.I.N.A. reports that equipment, and is not
removed when the equipment disconnects. To get rid of equipment you no longer
own, delete its device from the device page.

The integration remembers which devices it has seen only while it is running.
After a Home Assistant restart, a device that is disconnected shows its
entities as `unavailable` until N.I.N.A. reports it again.

## Availability

When equipment disconnects in N.I.N.A., its entities become `unavailable`.
There are no per-device `*_connected` sensors. To trigger on a disconnect, use
`to: "unavailable"` on any of that device's entities.

The safety monitor is the exception: it keeps
`binary_sensor.<instance>_safety_monitor_connected`. Availability can't tell
"the monitor stopped reporting" apart from "Home Assistant is restarting", and
a roof-close automation needs to know the difference.

`binary_sensor.<instance>_safety_monitor_unsafe` is `on` when conditions are
unsafe. This follows Home Assistant's `safety` device class, where `on` means
there is a problem. Trigger an abort on `to: "on"`.

If N.I.N.A. itself stops answering for 30 seconds, every entity of that rig
goes `unavailable`. A shorter drop, such as one missed poll over a remote link,
keeps the last readings, so it leaves no gap in history and fires no
`unavailable` trigger. Change the 30 seconds under **Settings → Devices &
Services → N.I.N.A. Astrophotography → Configure → Outage Grace Period**, from
0 (unavailable on the first missed poll) to 300.

While those readings are held they are not current. `binary_sensor.<instance>_reachable`
says so: it turns `off` on the first missed poll and stays available through
the whole outage. Trigger on it, with a `for:` delay of your choosing, rather
than on another entity going `unavailable`, which waits out the grace period
first.

## Entities by device

A typical rig has about 100 entities. A dome adds up to eleven, depending on
what its driver supports (see [Dome](#dome)). Weather channels appear only for
the readings your source actually provides.

| Device | Entities |
|---|---|
| Camera | temperature, cooler power, gain, offset, state, exposure end; target temperature and USB limit (`number`); cooler and dew heater (`switch`); exposing (`binary_sensor`); abort exposure (`button`) |
| Mount | RA, declination, altitude, azimuth, sidereal time, side of pier, time to meridian flip; at park, at home, meridian flip (`binary_sensor`); tracking rate (`select`); park, unpark, find home (`button`) |
| Focuser | position, temperature, step size; the last autofocus run (see [Autofocus](#autofocus)); position (`number`); moving, autofocus failed (`binary_sensor`); autofocus (`button`) |
| Filter Wheel | filter (`select`); moving (`binary_sensor`) |
| Guider | RMS total, RA and declination, status; guider (`switch`); clear calibration (`button`) |
| Rotator | position, mechanical position (`number`); reverse (`switch`); moving, synced (`binary_sensor`) |
| Flat Panel | cover state; brightness (`number`); light (`light`); cover (`switch`) |
| Weather | temperature, humidity, dew point, pressure, wind speed/direction/gust, rain rate, sky brightness, sky temperature, cloud cover, sky quality, star FWHM |
| Safety Monitor | unsafe, connected (`binary_sensor`) |
| Dome | shutter status; azimuth (`number`); following (`switch`); at park, at home, slewing, synchronized (`binary_sensor`); open, close, park, home (`button`) |
| Switch | one entity per channel the driver reports: a read-only channel is a `sensor`, an on/off channel a `switch`, a range a `number` |
| Hub | weather source, site latitude and longitude; session image count, integration time, average/best/worst HFR, average stars, session start; last image HFR, star count, mean ADU, exposure, RMS, target, filter; sequence target and progress; flats state and iterations; last frame and livestack (`image`); errors (`event`); reachable, sequencer running, imaging, sequence waiting (`binary_sensor`); wait ends at, last frame at; sequence start/stop (`button`); livestack (`switch`) |

The switch device's channels are named by its driver, so their entity ids are
`<domain>.<instance>_switch_<channel name>`: a channel called `OTA` is
`switch.<instance>_switch_ota`, and a read-only one called `Voltage` is
`sensor.<instance>_switch_voltage`. A channel with no name is
`Channel <Id>`, giving `<domain>.<instance>_switch_channel_<Id>`. A writable
channel that is neither on/off nor has a range gets no entity, and a channel
the driver stops reporting reads `unavailable`.

These are disabled by default; enable them from the entity's settings page:

- the three `flats_*` sensors (see [Flats](#flats))
- `sequence_progress` (see [Is the rig working?](#is-the-rig-working))
- `session_start` (see [Sessions](#sessions))
- `focuser_autofocus_r2` and `focuser_autofocus_fitted_hfr` (see
  [Autofocus](#autofocus))
- `sensor.<instance>_focuser_position`, which repeats
  `number.<instance>_focuser_position` with a state class, for charting
  position against temperature
- `focuser_step_size`
- the moving sensors of the focuser, filter wheel and rotator
- the configuration controls `number.<instance>_camera_usb_limit`,
  `number.<instance>_rotator_mechanical_position` and
  `switch.<instance>_rotator_reverse`; the mechanical position adds a line to
  the observatory card
- the dome's `binary_sensor.<instance>_dome_at_home`,
  `button.<instance>_dome_home` and `number.<instance>_dome_azimuth`:
  N.I.N.A. slaves the dome to the mount, and moving it by hand fights that

## Sessions

A session is everything since the most recent noon on the rig's clock. That
matches the boundary N.I.N.A.'s image history and Target Scheduler use. Session
statistics cover all targets, filters and exposure lengths in that window, and
integration time adds up the actual exposure lengths.

You can change the boundary hour under **Settings → Devices & Services →
N.I.N.A. Astrophotography → Configure → Session Rollover Hour**. You need to if
the imaging PC's clock is set to UTC, which is common on hosted rigs. N.I.N.A.
timestamps are in the PC's local time, so a UTC clock at a site five hours
behind UTC puts "noon" at 07:00 site time, in the middle of the dawn flats, and
splits the night in two. Set the hour to midday at the site.

Until the mount has connected at least once, the integration doesn't know the
rig's time zone and uses noon in Home Assistant's time zone instead.

`sensor.<instance>_session_start` (disabled by default) shows the boundary the
statistics are counting from. It is not when N.I.N.A. started, and it doesn't
move when N.I.N.A. or the PC restarts. If it shows an hour other than your
rollover hour, the rig's clock offset isn't being picked up.

## Is the rig working?

Two sensors answer different questions, and on a Target Scheduler rig they can
disagree for hours:

- **`binary_sensor.<instance>_sequencer_running`**: the sequencer is running.
  It stays `on` while the sequence waits for darkness, for a target to rise,
  for the moon to move away, or for unsafe conditions to clear.
- **`binary_sensor.<instance>_imaging`**: frames are being taken. It is `on`
  when the image count is rising, the camera is exposing, or a frame was saved
  in the last five minutes.

Use *sequencer running* to tell a working night from a stopped one, and
*imaging* to see whether it is taking pictures right now.

Two more entities explain why frames might not be arriving:

- `binary_sensor.<instance>_sequence_waiting` is `on` while Target Scheduler
  waits for a target's start window, or while the sequence runs one of its own
  wait instructions: Wait for Time, Wait for Time Span, or a wait for the
  target, sun or moon to reach an altitude. `sensor.<instance>_wait_ends_at`
  says until when, for a scheduler wait or a Wait for Time; the others name no
  end. The wait doesn't say why: darkness, moon separation, target altitude and
  a meridian window all look the same. An install from 2.5.1 or earlier keeps
  the id `binary_sensor.<instance>_scheduler_waiting`.

  It reads whether a wait was running when the sequence was last read, which
  is every 30 seconds while imaging and every 5 minutes otherwise. A wait of a
  few seconds shows on some reads and not others, so its history is a sample,
  not a record of every wait. Its attributes describe the wait:

  | Attribute | Meaning |
  |---|---|
  | `kind` | `scheduler`, `time`, `time_span` or `altitude` |
  | `started_at` | when a read first showed it, up to one read after it began |
  | `ends_at` | its end, for a scheduler wait or a Wait for Time |
  | `span_seconds` | a Wait for Time Span's length |
  | `recent_waits` | the last ten that ended, newest first, each with `kind`, `started_at`, `ended_at` and `span_seconds`; not recorded, and empty after a restart |

  A wait still showing as running after it must have ended is over: a Wait for
  Time at its end, an altitude wait after twelve hours. A span still showing
  past its length plus five minutes is taken as the next pass of a loop.

  A wait for safe conditions is a loop that repeats until the monitor reads
  safe. If the loop holds a Wait for Time Span, this blinks `on` while the span
  runs. Watch `safety_monitor_unsafe` for that.
- `sensor.<instance>_last_frame_at` is when the newest frame of any type was
  saved, flats included. It is `unknown` after every N.I.N.A. restart until the
  first frame, because N.I.N.A.'s image history is cleared on restart. It is
  the time the frame was saved, so it is one exposure behind when the exposure
  started.

### Writing your own stall check

Gaps between frames vary more than you'd expect. On real nights:

| Gap | Cause |
|---|---|
| 31.5 min between lights | a normal night |
| 116 min with no frames | conditions went unsafe and the sequence waited until dawn |
| 11.6 min from the end of a wait to the first frame | slew, rotation, filter change, guider settle |

A reasonable rule is: no frame for your longest exposure plus about 30 minutes,
while the sequencer is running, the scheduler isn't waiting and conditions are
safe, and `last_frame_at` isn't `unknown`. A simpler template will raise false
alarms. The blueprint below already does this.

`sensor.<instance>_sequence_progress` is disabled by default because it reads
`unknown` on a Target Scheduler rig: the scheduler picks targets during the
night and has no total to measure progress against. Enable it only if you run a
plain Advanced Sequencer sequence. The observatory card hides its progress bar
when this sensor has no value.

## The imaging stall alert blueprint

`imaging_stall_alert.yaml` sends a notification when frames stop for a reason
that needs you. It only notifies: it never stops, parks or closes anything.

It fires in three cases:

| Case | Fires when |
|---|---|
| Unreachable | *rig reachable* has been `off` for 2 minutes, meaning N.I.N.A. or its API is down. Without that input, *sequencer running* being `unavailable` for 2 minutes, which starts only after the outage grace period |
| Parked | the mount parks while the sequencer is still running |
| Quiet | *imaging* has been off for 20 minutes, or no frame has been saved for your longest exposure (default 600 s) plus 30 minutes. Checked every minute. |

Pick the rig's *Reachable* sensor for *rig reachable*, in this blueprint and in
`weather_abort.yaml`. It is optional so that automations made from the older
blueprints keep loading, but without it a lost rig is reported one outage grace
period later.

The quiet case doesn't fire while the sequencer is stopped, while the sequence
is waiting, for 15 minutes after a wait ends, or in daylight. A Wait for Time
Span shorter than the quiet period counts as neither: it paces a retry loop,
which is how a stall often looks. Its timers start
at the latest of the sequencer starting, conditions turning safe, the sun
setting and the quiet hours ending. So neither the last frame of the previous
night nor an hour spent waiting for dark triggers an alert the moment the rig
is let work. All of these times are blueprint inputs.

It also stays quiet in these situations you should know about:

- **While conditions are unsafe.** The rig waiting out bad weather is working
  correctly, and `weather_abort.yaml` handles that case. If your rig has a
  safety monitor, fill in the safety input; if you leave it empty you'll get an
  alert during every weather hold.
- **In daylight,** because `night_only` is on by default. Turn it off for solar
  imaging. It uses the sun at the rig if you wire the site inputs (see below),
  and `sun.sun` otherwise; with neither it doesn't suppress anything.
- **During quiet hours,** if you set them, for a rig you shut down by day.
  `mute_mode` picks the window: between two times, which may cross midnight,
  or while the sun is up — from when the rising sun passes one altitude until
  the setting sun drops below another. The defaults are -12° (the end of
  nautical twilight) and +3° (roughly 20–30 minutes before sunset). The window
  covers the unreachable alert too, and a rig still unreachable when it closes
  is reported then. Fixed times are Home Assistant's local time, which is not
  the rig's if it is hosted in another time zone.

For a hosted rig, wire the optional site latitude and longitude inputs to the
rig's `site_latitude` and `site_longitude` sensors. Both sun gates, night only
and sun quiet hours, then use the sun where the rig is instead of where Home
Assistant is. Until N.I.N.A. reports a site, Home Assistant's location stands
in.

The alert is a persistent notification plus a message to the notify entity you
choose. It includes how long it has been quiet, the last frame's target and
filter, the camera state, temperature and cooler power, the guider, whether the
mount is parked or at home, autofocus, and the latest error if it came after
the sequence started. It repeats every 60 minutes, at most twice (set reminders
to 0 to turn this off). When a frame arrives or the sequencer stops, it
dismisses the notification and says which happened. A sequence that finishes
looks the same as one stopped by hand, so the message doesn't claim the night
completed.

Limitations:

- If Home Assistant restarts while an alert is open, the notification and the
  follow-up "cleared" message are both lost.
- After a restart the quiet case waits the full quiet period (20 minutes by
  default) before it can fire, because its timers restart with Home Assistant.
- A rig taking bad frames is not stalled; this blueprint won't notice it.
  Guiding problems are covered by `guiding_alert.yaml`. A lost guide star that
  stops frames will show up here as a stall, with the guider state in the
  message.

## Weather

A weather channel's entity is created the first time the source reports a real
value for it. If you set up the integration in daylight, you may see no weather
entities until the source starts reporting. Once created, they stay.

A channel reads `unknown` while its source has no value for it, and
`unavailable` when you've switched to a different source that doesn't provide
that channel at all.

A source that reports temperature and humidity but no dew point gets
`sensor.<instance>_weather_dew_point` computed from those two with the Magnus
formula, which adds under 0.35 °C to the error of the humidity reading itself.
The weather card's dew alert and any automation on the sensor then work as
they would with a dew point sensor.
The source's own dew point is used whenever it reports one.

Don't use weather readings to decide it's safe to image. Forecast-based
sources such as OpenMeteo are gridded forecasts updated every 10 minutes, and
can report 0% cloud while you're under one. Use
`binary_sensor.<instance>_safety_monitor_unsafe` to abort. Weather readings are
fine for holding back a resume after an abort.

## Flats

The `flats_*` sensors only track flats started through the Advanced API's
`/flats` endpoints, and this integration has no action that starts them. A
Target Scheduler flat run or N.I.N.A.'s flat wizard leaves them reading
`Finished` with unknown iteration counts the whole time, so they ship disabled.
They are polled every 5 minutes. Enable them only if something else starts
flats through the API.

How a flat run shows up elsewhere:

- `sensor.<instance>_session_image_count` includes flats. Its `light_count`
  attribute doesn't. Integration time and the HFR and star statistics count
  lights only.
- The `last_image_*` sensors keep showing the last light frame during a flat
  run.
- `sensor.<instance>_last_frame_at` includes flats, and
  `binary_sensor.<instance>_imaging` is `on` while flats are exposing.
- On many rigs the flat panel is only connected for the flat run, so its
  entities first appear then, and after a Home Assistant restart they are
  `unavailable` until it connects again. While N.I.N.A. is using the panel,
  don't let a scene or automation change its light or brightness; it will
  spoil the flats.

## Autofocus

The focuser's `last_autofocus` sensor and the `autofocus_*` sensors next to it
show N.I.N.A.'s report from the most recent autofocus run:

| Sensor | Meaning |
|---|---|
| `last_autofocus` | when the run happened |
| `autofocus_starting_position`, `autofocus_position` | focuser position (steps) before and after |
| `autofocus_starting_hfr` | HFR measured before the sweep |
| `autofocus_hfr` | the best HFR measured during the sweep |
| `autofocus_temperature` | focuser temperature at the run |
| `autofocus_duration` | how long it took |
| `autofocus_filter` | the filter used |
| `autofocus_r2`, `autofocus_fitted_hfr` | diagnostics, disabled by default |

Things to know when reading them:

- **`autofocus_hfr` is a measured value, not N.I.N.A.'s calculated focus
  point.** With a `TREND*` curve fitting, the calculated value extrapolates,
  wholly or partly, from the trend lines and can be smaller than any star
  your optics produce (1.09 px against a best measured 1.55 px on one run). That
  value is `autofocus_fitted_hfr`, and the `fitted_hfr` attribute of
  `sensor.<instance>_focuser_last_autofocus`.
- **The best measured HFR can be worse than the starting HFR on a run that
  improved focus.** N.I.N.A. moves to a fitted position between two sweep
  steps, and never measures HFR there. So don't treat the two as a reliable
  before-and-after.
- **A rejected run still replaces the previous report.** The report doesn't
  say whether N.I.N.A. accepted it. Use
  `binary_sensor.<instance>_focuser_autofocus_failed`, which compares R² with
  your profile's `RSquaredThreshold` and checks the focus position against
  the sweep, for a report from the current session.
- **A run whose focus position falls outside the positions it measured is
  rejected whatever its R².** A position on the sweep's first or last step is
  inside it. N.I.N.A. checks this under every autofocus method; Hocus Focus
  checks it on `STARHFR` runs only. `autofocus_failed` reports it as
  `out_of_range`.
- **An `RSquaredThreshold` of 0 or below turns the R² check off**, in N.I.N.A.
  and in Hocus Focus alike, so `autofocus_failed` rejects no run on its R².
  It still catches a focus position outside the sweep. N.I.N.A.'s own
  autofocus then measures HFR at the new position instead, and rejects a run
  more than 15% worse than where it started. That measurement is not in the
  report, so `autofocus_failed` cannot see that rejection.
- **A run that hangs writes no report**, so the sensors keep showing the
  previous run. The failed sensor catches this too.
- **The report survives restarts**, so the autofocus sensors can show a run
  days old. `autofocus_failed` ignores a report older than the session start,
  so a previous night's failure doesn't leave it `on`. For the others, check
  `last_autofocus`.
- **A report charts one attempt's sweep.** A failed attempt is retried, and
  the curve, R² and focus position in the report are the last attempt's.
  N.I.N.A. writes a report for every attempt, so with its own autofocus
  `autofocus_failed` can turn `on` for a failed attempt and back `off` when
  the retry succeeds. Hocus Focus writes one for the whole run, and Hocus
  Focus 4 retries once more, centred on the computed position, after an
  attempt whose focus falls outside its sweep or whose final HFR fails its
  HFR improvement threshold. `autofocus_duration` counts
  from the start of the run, earlier attempts included, and
  `autofocus_starting_position` is where the focuser stood before the first.
- On a `CONTRASTDETECTION` run the HFR sensors read `unknown`, because that
  method measures contrast rather than star size. So does `autofocus_r2`: N.I.N.A.
  applies no R² threshold to a contrast run, so `autofocus_failed` never rejects
  one on its R². Positions and duration still work.

`autofocus_failed` has these attributes:

| Attribute | Meaning |
|---|---|
| `reason` | `hung`, `rejected`, `out_of_range`, or `null` when the last run failed none of those ways. A hung run usually means a sequence problem. A rejected one failed the R² check, and means the focus range or star detection needs adjusting. An out-of-range one put focus outside the positions it measured: start the run nearer focus, or widen the sweep with a larger step size or more steps. A run failing both the R² and the range check reads `rejected`, the check N.I.N.A. runs first. Only for `hung` do the other autofocus sensors show a different run from the one that failed. |
| `r_squared` | the R² used for the decision: the worst among the judged curves |
| `r_squared_threshold` | your profile's `RSquaredThreshold`, or `null` when it is 0 or below and the check is off, or before the profile has been read |
| `refocus_temperature_delta` | the °C of focuser drift past which your sequence's "AF After Temperature Change" trigger refocuses, or `null` with no such trigger. With several, the smallest: which one is in scope cannot be told. The autofocus card flags drift against it. |

If you check R² yourself, compare against this `r_squared` attribute, not
values from the `fits` attribute below; they can differ slightly.

`sensor.<instance>_focuser_last_autofocus` says how the run was measured:

| Attribute | Meaning |
|---|---|
| `method` | `STARHFR` or `CONTRASTDETECTION` |
| `fitting` | the curve fitting the run used, such as `TRENDHYPERBOLIC` |
| `autofocuser` | the autofocus routine that ran, such as `Hocus Focus` |
| `star_detector` | the star detection that measured the HFRs |

Compare HFRs between two runs only when their `autofocuser` and
`star_detector` match. Hocus Focus's star detection and N.I.N.A.'s built-in
one measure HFR on different scales.

`sensor.<instance>_focuser_temperature` minus
`sensor.<instance>_focuser_autofocus_temperature` is the temperature change
N.I.N.A.'s "autofocus after temperature change" trigger watches. A template
sensor over the two will show how close you are to the next refocus.

## The autofocus curve attributes

This section is for writing your own chart. `nina-autofocus-card` already draws
all of this.

`sensor.<instance>_focuser_last_autofocus` has a `curve` attribute with one row
per focuser position the sweep visited, sorted by position:

```yaml
curve:
  - position: 2212
    value: 6.767517920907358
    error: 0.3301867392819892
  - position: 2247
    value: 4.851116817456493
    error: 0.2779231723941218
  # …
```

- `value` is HFR in pixels for a `STARHFR` run and a contrast score for
  `CONTRASTDETECTION`. The `method` attribute says which.
- `value` is `null` when that frame measured nothing, usually because the stars
  were too bloated at the end of the sweep. The row is kept so a chart can
  break its line there. Nulls at only one end suggest the sweep is too wide.
  `measured_points` counts the non-null rows.
- `error` is the spread of star sizes in that frame, which N.I.N.A. draws as an
  error bar. A large spread points at tilt, field curvature or elongation, not
  at an unreliable point.

Don't assume:

- the sweep is centred on `autofocus_starting_position`
- `autofocus_starting_hfr` equals the curve's value at that position (they're
  separate exposures, so a starting-HFR marker will sit slightly off the curve)
- the final position is on the curve (it usually falls between two steps)

The same sensor carries the fitted curves:

```yaml
fits:
  - name: Quadratic
    equation: "y = 0.0003058854621319121 * x^2 + -1.4293365331583652 * x + 1671.5984427459177"
    coefficients: [0.0003058854621319121, -1.4293365331583652, 1671.5984427459177]
    hyperbola: null
    gaussian: null
    r_squared: 0.9710548595560263
    judged: true
  - name: LeftTrend
    coefficients: [-0.04727009756935714, 111.1161540435258]
    r_squared: 0.9902518159347956
    judged: true
  # …RightTrend

minima:
  - name: TrendLineIntersection
    position: 2344
    value: 0.3330580830396599
    used: true
  - name: QuadraticMinimum
    position: 2336
    value: 1.8534560537596008
    used: true

fitted_hfr: 1.0932570683996303
```

- `coefficients` are highest power first: `[a, b, c]` is `a·x² + b·x + c`.
  A hyperbolic or gaussian fit has `coefficients: null` and its parameters in
  `hyperbola` or `gaussian` instead:

  ```yaml
  - name: Hyperbolic
    equation: "y = 2.8/48 * √((x - 2336)² + 48²) + -1"
    coefficients: null
    hyperbola: {x0: 2336, y0: -1, a: 2.8, b: 48, c: 48, slope: 0, blend: null, blend_width: null}
    gaussian: null
  ```

- `hyperbola` is one form for every autofocuser's model, with `u = x − x0`:
  `y = y0 + slope·u + w·(a/b)·√(u² + b²) + (1 − w)·(a/c)·√(u² + c²)`. The
  weight `w` on the left branch is 1 when `blend` is `null`, and then `c`
  equals `b`. It is `clamp(−u / blend_width, 0, 1)` for `blend: ramp` and
  `1 / (1 + e^(u / blend_width))` for `blend: logistic`. Built-in N.I.N.A.
  writes `a * cosh(asinh((x0 - x) / b))`, which is published with `y0` and
  `slope` at 0. Hocus Focus's Symmetric model sets `y0`, Tilted Hyperbola
  `slope`, and Uneven Blend and Smooth Blend a separate right branch `c` with
  a `ramp` or `logistic` blend.
- `gaussian` is `y = amplitude·e^(−(x − mean)² / (2·sigma²)) + offset`, which
  peaks at `mean`.
- An equation in a form the integration doesn't recognise has all three
  `null`, and `equation` is the only record. The autofocus card lists such a
  fit with its R² and marks it `not plotted`. Fits the run didn't compute are
  left out.
- Each fit's `r_squared` is for that fit alone, which is what a chart legend
  wants. The `autofocus_r2` sensor is the worst fit with `judged: true`, which
  is what a pass/fail threshold wants.
- `judged` says whether that fit's R² counts toward the verdict, which
  depends on `fitting`. A `HYPERBOLIC` run can also report trend lines. They
  have `judged: false`, and a low R² on them doesn't reject the run. A
  contrast-detection run, whose `fitting` is `GAUSSIAN`, has every fit
  `judged: false`.
- `judged` comes from the report alone, so it doesn't know whether the
  profile's R² check is on. When
  `binary_sensor.<instance>_focuser_autofocus_failed` has
  `r_squared_threshold: null`, either the check is off or the profile hasn't
  been read yet. The two look the same, so the autofocus card marks every fit
  `not judged`, whatever `judged` says. The minima keep their `used`, which
  R² doesn't touch.
- `minima` lists the minima the autofocus routine computed, and which ones
  depends on the routine. The example above is a Hocus Focus run. Hocus Focus
  fits trend lines on every run to decide when the sweep ends, so it lists
  `TrendLineIntersection` beside the minimum of the curve your fitting uses,
  if any. Built-in N.I.N.A. lists all four (`TrendLineIntersection`,
  `HyperbolicMinimum`, `QuadraticMinimum`, `GaussianMaximum`) whatever it
  fitted. Read the final focus point from `fitted_hfr` and
  `autofocus_position` rather than working it out from `minima`. N.I.N.A.
  picks it by `fitting`:

  | `fitting` | Final focus point |
  |---|---|
  | `TRENDLINES` | the trend-line intersection |
  | `PARABOLIC` | the quadratic minimum |
  | `HYPERBOLIC` | the hyperbolic minimum |
  | `TRENDPARABOLIC` | the mean of the trend-line intersection and the quadratic minimum |
  | `TRENDHYPERBOLIC` | the mean of the trend-line intersection and the hyperbolic minimum |

  `fitted_hfr` is `null` on a contrast-detection run, whose focus point is
  the gaussian maximum of a contrast score, and wherever the fit put it at
  or below zero.
- A minimum's `used` says whether the final focus point is built from it,
  by the table above. `used: false` marks a minimum the run ignored, such as
  the intersection on a `HYPERBOLIC` run. A contrast-detection run, whose
  `fitting` is `GAUSSIAN`, uses `GaussianMaximum`. `used` has nothing to do
  with R²: that gaussian is used, but its fit is `judged: false`. A
  `fitting` this integration doesn't recognise marks every minimum `used`.
- Don't scale your y-axis to include `TrendLineIntersection`. It is where the
  extrapolated trend lines cross, well below any real star size (0.333 px
  above, against 1.552 px measured). Scale to the measured points.

Home Assistant can't chart an attribute by itself, so a chart needs a custom
card, an ApexCharts `data_generator`, or a template. For history, chart
`sensor.<instance>_focuser_autofocus_hfr`, which records one value per run.

## Other attributes

- `sensor.<instance>_session_avg_hfr` has `by_target` and `by_filter`
  attributes: count, integration hours and mean HFR for each.
- `sensor.<instance>_mount_time_to_meridian_flip` has `flip_fires_at_minutes`,
  the reading at which the flip window opens: N.I.N.A. flips at the first item
  boundary from then on. It is `MaxMinutesAfterMeridian − MinutesAfterMeridian`
  from your profile, not zero, so base warning thresholds on it rather than a
  fixed number. The sensor counts down to the latest flip; the cards print both
  ends, so with Min 5 and Max 15 a reading of 22 shows as "Flip in 12–22 min",
  and a reading of 6 as "≤ 6 min".

  The range is when the mount slews, not when imaging stops. With *Pause
  before meridian* set, N.I.N.A. stops imaging Min + Pause minutes before the
  earliest end, at meridian − Pause, and waits; the flip itself still comes at
  the earliest end. N.I.N.A. also stops early when the next exposure would not
  finish by the latest end.

  While N.I.N.A. waits for meridian + Min it turns tracking off, so the
  countdown reads `unknown` for the whole wait.
  `binary_sensor.<instance>_mount_meridian_flip` covers that. It turns `on` at
  `MOUNT-BEFORE-FLIP`, before the guider stops and the wait begins, and `off`
  at `MOUNT-AFTER-FLIP`. It also turns `off` when the sequence finishes or the
  mount is parked, homed or disconnected. Its `slews_at` attribute estimates
  when the wait ends and the slew starts, from the last countdown read while
  the mount was tracking. It is `null` when no such reading or profile is
  available, as after a Home Assistant restart in mid-wait. A cancelled flip
  also sends `MOUNT-AFTER-FLIP`, so the sensor turning `off` does not prove the
  mount flipped.

- `sensor.<instance>_last_image_mean_adu` has `recent_frames`: the newest
  frames of every type, newest first, each with its target, filter, exposure,
  HFR, star count, guide RMS and N.I.N.A.'s min, median, mean and max ADU. The
  image panel card draws its ADU range from these, on an axis to the camera's
  full scale, which it also reads from `recent_lights`. They are statistics,
  not a histogram like the one in N.I.N.A.'s Statistics panel: the Advanced
  API publishes none. Building one means fetching the whole raw frame a second
  time, which a remote observatory is already sending elsewhere. Issue #178
  tracks doing it as an option.

- `sensor.<instance>_last_image_hfr` has `recent_lights`: the session's
  newest 60 lights, oldest first, each with its target, filter, exposure, HFR,
  star count, and mean and max ADU. The frame statistics card draws its charts
  from these.

  Both cards read the camera's full scale from their frames' max: a camera
  that does not scale its data to 16 bits saturates at or below 4095 or 16383.
  N.I.N.A.'s bit depth is no help, since for ASCOM and DSLR cameras it is a
  profile setting the user types in.

## Error events

`event.<instance>_error` fires `platesolve_failed`, `camera_download_timeout`
and `autofocus_timeout`. Coverage is incomplete:

- N.I.N.A. produces its error events by matching log lines. The plate-solve
  match only recognises ASTAP, so failures from other solvers don't appear.
- N.I.N.A.'s own autofocus error event doesn't fire in the current plugin, so
  `autofocus_timeout` is this integration's own check for a run that never
  finished.

## Dome

The dome entities are tested against a simulated dome, not real dome hardware.
If you have a dome, please report what works and what doesn't on the
[issue tracker](https://github.com/dgivens/homeassistant-nina-astrophotography/issues).

A dome gets only the entities its driver supports:

| Driver reports | Entities |
|---|---|
| always | shutter status |
| `CanSetShutter` | open, close |
| `CanPark` | park, at park |
| `CanFindHome` | home, at home |
| `CanSetAzimuth` | azimuth, slewing, synchronized, following |

So a roll-off roof with no azimuth, park or home gets the shutter status, open
and close. Slewing reports the dome turning, not the shutter moving, so a roof
has none.

`sensor.<instance>_dome_shutter_status` reads `open`, `closed`, `opening`,
`closing` or `error`. A driver with no shutter reads `unknown`. A roof-close
automation should wait for `closed` rather than trust the close command: N.I.N.A.
answers it before the roof moves. `session_shutdown.yaml` and
`weather_abort.yaml` do this when you give them the shutter status.

The shutter status also carries N.I.N.A.'s own dome interlocks from your
profile, which N.I.N.A. enforces whatever Home Assistant does. Each is `true`
or `false`, or `null` until the profile has been read:

| Attribute | N.I.N.A. setting |
|---|---|
| `close_on_unsafe` | closes the shutter when the safety monitor reports unsafe |
| `refuse_unsafe_shutter_move` | refuses to open the shutter while unsafe |
| `refuse_open_without_safety_monitor` | refuses to open the shutter with no safety monitor connected |
| `refuse_unpark_while_shut` | refuses to unpark the mount with the shutter shut |
| `park_mount_before_shutter_move` | parks the mount before moving the shutter |
| `park_dome_before_shutter_move` | parks the dome before moving the shutter |
| `find_home_before_park` | homes the dome before parking it |

The integration refuses some dome commands itself:

- Opening the dome is refused while the safety monitor reports unsafe, from
  the button and the `dome_open` action alike, whatever
  `refuse_unsafe_shutter_move` says. A monitor that is absent or not
  reporting refuses nothing.
- Homing the dome or setting its azimuth is refused while it follows the
  mount. N.I.N.A. would quietly turn following off, which takes the slit off
  the scope.

## Livestack

`switch.<instance>_livestack` exists whether or not the Livestack plugin is
installed. Without the plugin it reads `off`, and turning it on raises an
error.

`image.<instance>_livestack` is created the first time the plugin reports a
stack update (`STACK-UPDATED`). It shows the stack that updated last, and its
`target` and `filter` attributes say which: a mono rig keeps one stack per
filter, and the image follows whichever updated most recently. Stacks don't
survive a N.I.N.A. restart, so after one the image reads `unknown`, with both
attributes `null`, until the next stack update.

Its `stacks` attribute lists every stack updated this session, newest first,
one per target and filter: `target`, `filter`, `updated`, `monochrome`, and
the frame count — `count` for a mono stack, or `red_count`, `green_count` and
`blue_count` for a colour one, where a channel with no frame yet is `null`.
The list starts with the [session](#sessions), so last night's stacks drop
off it at the rollover hour even though the plugin keeps them until N.I.N.A.
restarts. The attribute is not recorded. `custom:nina-livestack-card` shows
them.

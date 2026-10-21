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
- [Dome and Livestack](#dome-and-livestack)

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

If N.I.N.A. itself is unreachable, every entity of that rig goes `unavailable`.

## Entities by device

A typical rig has about 100 entities. A dome adds ten. Weather channels appear
only for the readings your source actually provides.

| Device | Entities |
|---|---|
| Camera | temperature, cooler power, gain, offset, state; target temperature and USB limit (`number`); cooler and dew heater (`switch`); exposing (`binary_sensor`); abort exposure (`button`) |
| Mount | RA, declination, altitude, azimuth, sidereal time, side of pier, time to meridian flip; at park, at home (`binary_sensor`); tracking rate (`select`); park, unpark, find home (`button`) |
| Focuser | position, temperature, step size; the last autofocus run (see [Autofocus](#autofocus)); position (`number`); moving, autofocus failed (`binary_sensor`); autofocus (`button`) |
| Filter Wheel | filter (`select`); moving (`binary_sensor`) |
| Guider | RMS total, RA and declination, status; guider (`switch`); clear calibration (`button`) |
| Rotator | position, mechanical position (`number`); reverse (`switch`); moving, synced (`binary_sensor`) |
| Flat Panel | cover state; brightness (`number`); light (`light`); cover (`switch`) |
| Weather | temperature, humidity, dew point, pressure, wind speed/direction/gust, rain rate, sky brightness, sky temperature, cloud cover, sky quality, star FWHM |
| Safety Monitor | unsafe, connected (`binary_sensor`) |
| Dome | shutter status; azimuth (`number`); following (`switch`); at park, at home, slewing (`binary_sensor`); open, close, park, home (`button`) |
| Switch | one entity per channel the driver reports: a read-only channel is a `sensor`, an on/off channel a `switch`, a range a `number` |
| Hub | weather source; session image count, integration time, average/best/worst HFR, average stars, session start; last image HFR, star count, mean ADU, exposure, RMS, target, filter; sequence target and progress; flats state and iterations; last frame and livestack (`image`); errors (`event`); sequencer running, imaging, scheduler waiting (`binary_sensor`); wait ends at, last frame at; sequence start/stop (`button`); livestack (`switch`) |

These are disabled by default; enable them from the entity's settings page:

- the three `flats_*` sensors (see [Flats](#flats))
- `sequence_progress` (see [Is the rig working?](#is-the-rig-working))
- `session_start` (see [Sessions](#sessions))
- the autofocus R² and fitted HFR sensors
- a few other diagnostics

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

- `binary_sensor.<instance>_scheduler_waiting` is `on` while Target Scheduler
  is waiting, and `sensor.<instance>_wait_ends_at` says until when. The wait
  doesn't say why: darkness, moon separation, target altitude and a meridian
  window all look the same.

  A wait for safe conditions is *not* a scheduler wait. It is a loop inside the
  N.I.N.A. sequence, so `scheduler_waiting` stays `off`. Watch
  `safety_monitor_unsafe` for that.
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
| Unreachable | *sequencer running* has been `unavailable` for 2 minutes, meaning N.I.N.A. or its API is down |
| Parked | the mount parks while the sequencer is still running |
| Quiet | *imaging* has been off for 20 minutes, or no frame has been saved for your longest exposure (default 600 s) plus 30 minutes. Checked every minute. |

The quiet case doesn't fire while the sequencer is stopped, while the scheduler
is waiting, for 15 minutes after a wait ends, or in daylight. Its timers start
no earlier than the sequencer did, so the last frame of the previous night
doesn't trigger an alert as soon as tonight's sequence starts. All of these
times are blueprint inputs.

It also stays quiet in two situations you should know about:

- **While conditions are unsafe.** The rig waiting out bad weather is working
  correctly, and `weather_abort.yaml` handles that case. If your rig has a
  safety monitor, fill in the safety input; if you leave it empty you'll get an
  alert during every weather hold.
- **In daylight,** because `night_only` is on by default. Turn it off for solar
  imaging. It uses `sun.sun`; without that entity it doesn't suppress anything.

The alert is a persistent notification plus a message to the notify entity you
choose. It includes how long it has been quiet, the last frame's target and
filter, the camera state, temperature and cooler power, the guider, whether the
mount is parked or at home, autofocus, and the latest error. It repeats every
60 minutes, at most twice (set reminders to 0 to turn this off). When a frame
arrives or the sequencer stops, it dismisses the notification and says which
happened. A sequence that finishes looks the same as one stopped by hand, so
the message doesn't claim the night completed.

Limitations:

- If Home Assistant restarts while an alert is open, the notification and the
  follow-up "cleared" message are both lost.
- The quiet case is also muted for `settle_minutes` after a restart.
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
  point.** With a `TREND*` curve fitting, the calculated value partly
  extrapolates from the trend lines and can be smaller than any star your
  optics produce (1.09 px against a best measured 1.55 px on one run). That
  value is `autofocus_fitted_hfr`.
- **The best measured HFR can be worse than the starting HFR on a run that
  improved focus.** N.I.N.A. moves to a fitted position between two sweep
  steps, and never measures HFR there. So don't treat the two as a reliable
  before-and-after.
- **A rejected run still replaces the previous report.** The report doesn't
  say whether N.I.N.A. accepted it. Use
  `binary_sensor.<instance>_focuser_autofocus_failed`, which compares R² with
  your profile's `RSquaredThreshold`.
- **A run that hangs writes no report**, so the sensors keep showing the
  previous run. The failed sensor catches this too.
- **The report survives restarts.** It may be days old; check
  `last_autofocus`.
- **Each report covers one attempt.** N.I.N.A. retries a rejected run and only
  the last attempt is reported, so `autofocus_duration` understates the time a
  bad run cost.
- On a `CONTRASTDETECTION` run the HFR sensors read `unknown`, because that
  method measures contrast rather than star size. Positions and duration still
  work.

`autofocus_failed` has these attributes:

| Attribute | Meaning |
|---|---|
| `reason` | `hung`, `rejected`, or absent. A hung run usually means a sequence problem; a rejected one means the focus range or star detection needs adjusting. Only for `hung` do the other autofocus sensors show a different run from the one that failed. |
| `r_squared` | the R² used for the decision: the worst value in the run's `RSquares` |
| `r_squared_threshold` | your profile's `RSquaredThreshold` |

If you check R² yourself, compare against this `r_squared` attribute, not
values from the `fits` attribute below; they can differ slightly.

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
    r_squared: 0.9710548595560263
  - name: LeftTrend
    coefficients: [-0.04727009756935714, 111.1161540435258]
    r_squared: 0.9902518159347956
  # …RightTrend

minima:
  - name: TrendLineIntersection
    position: 2344
    value: 0.3330580830396599
  - name: QuadraticMinimum
    position: 2336
    value: 1.8534560537596008
```

- `coefficients` are highest power first: `[a, b, c]` is `a·x² + b·x + c`.
  For fits other than polynomials (hyperbolic, gaussian) `coefficients` is
  `null` and `equation` is the only record. Fits the run didn't use are left
  out.
- Each fit's `r_squared` is for that fit alone, which is what a chart legend
  wants. The `autofocus_r2` sensor is the worst fit, which is what a
  pass/fail threshold wants.
- `minima` lists the minima N.I.N.A. computed. Pick the second by position in
  the list, not by name; its name depends on the curve fitting in your profile.
  The final focuser position is the average of the two.
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
  the reading at which N.I.N.A. actually flips. It is
  `MaxMinutesAfterMeridian − MinMinutesAfterMeridian` from your profile, not
  zero, so base warning thresholds on it rather than a fixed number.

## Error events

`event.<instance>_error` fires `platesolve_failed`, `camera_download_timeout`
and `autofocus_timeout`. Coverage is incomplete:

- N.I.N.A. produces its error events by matching log lines. The plate-solve
  match only recognises ASTAP, so failures from other solvers don't appear.
- N.I.N.A.'s own autofocus error event doesn't fire in the current plugin, so
  `autofocus_timeout` is this integration's own check for a run that never
  finished.

## Dome and Livestack

The dome entities were built from the API specification and have not been
tested with real dome hardware. If you have a dome, please report what works
and what doesn't on the
[issue tracker](https://github.com/dgivens/homeassistant-nina-astrophotography/issues).

`switch.<instance>_livestack` exists whether or not the Livestack plugin is
installed. Without the plugin it reads `off`, and turning it on raises an
error.

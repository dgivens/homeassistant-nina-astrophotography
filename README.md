> [!NOTE]
> **AI-Assisted Development**
>  
> [![AI Assisted](https://img.shields.io/badge/built%20with-Claude%20AI-7b8de8?style=flat-square&logo=anthropic)](https://claude.ai) All code has been reviewed, tested against a live N.I.N.A. instance, and is maintained by a human author. AI assistance was used to accelerate development — the design decisions, testing, and ongoing maintenance are my own.

# N.I.N.A. Astrophotography – Home Assistant Integration

> **This is a maintained fork.** The original
> [C3X0Astro/homeassistant-nina-astrophotography](https://github.com/C3X0Astro/homeassistant-nina-astrophotography)
> was published on 2026-03-20 and has had no commits since. This fork has been
> modified from that version, beginning 2026-09-01, to correct a number of
> defects in the API client, sensors and blueprints — see `CHANGELOG.md`.
> Distributed under GPL-3.0, as the original is.

Connect [N.I.N.A. (Nighttime Imaging 'N' Astronomy)](https://nighttime-imaging.eu)
to Home Assistant through the
**[Advanced API plugin](https://github.com/christian-photo/ninaAPI)** (v2).
Monitor the rig in real time and control it from automations, dashboards and
scripts.

> **Upgrading from 1.4.x?** Read [Upgrading to 2.0](#upgrading-to-20) first.

---

## Prerequisites

1. **N.I.N.A. 3.x** on your imaging PC (Windows).
2. **Advanced API plugin** installed and enabled inside N.I.N.A.:
   - N.I.N.A. → *Plugins* → search "Advanced API" → Install.
   - *Options → Advanced API*: confirm the port (default **1888**) and that the
     service is enabled.
3. Home Assistant must be able to reach the imaging PC (same LAN, or a VPN).

The API has **no authentication of any kind**. Anything that can reach the port
can move the mount, so keep it off the open internet.

---

## Installation

### HACS (recommended)

Add this repository as a custom repository in HACS and download it from there.

### Manual

1. Copy the `nina_astrophotography` folder into your HA `custom_components`
   directory:
   ```
   config/
   └── custom_components/
       └── nina_astrophotography/    ← this folder
   ```
2. Restart Home Assistant.
3. **Settings → Devices & Services → Add Integration** → **N.I.N.A.
   Astrophotography**.
4. Enter the IP or hostname of the imaging PC, the API port (default `1888`) and
   a name for the instance.

### Removing it

**Settings → Devices & Services → N.I.N.A. Astrophotography → ⋮ → Delete.**
That removes the entry, its devices and its entities. If you copied the Lovelace
cards into `www/`, delete those files and their dashboard resources too.

---

## The device model

The instance name is the one thing worth choosing carefully: it titles the
config entry, names the hub device, and prefixes every entity id.

Each instance creates **one hub device** and **one child device per piece of
equipment** — Camera, Mount, Focuser, Filter Wheel, Guider, Rotator, Dome, Flat
Panel, Weather, Safety Monitor, Switch. Driver name and version live in the
**device registry**, on the device page, rather than in entity attributes.

A device appears the first time N.I.N.A. reports it and stays thereafter:
equipment is routinely disconnected, and a device that came and went would take
its entity ids with it. To retire equipment you have sold, delete the device
from its device page.

**Two rigs coexist.** Give the second instance its own name, and every device
and entity is prefixed with it. Actions take a device target so they reach the
rig you mean — see [Actions](#actions).

## Availability

**A disconnected device makes its entities `unavailable`, not `off`.** There is
no `*_connected` binary sensor for equipment any more; availability carries it.
An automation that needs to know triggers on `to: "unavailable"` on any of that
device's entities.

**The safety monitor is the exception**, and keeps
`binary_sensor.<instance>_safety_monitor_connected`. Availability cannot
distinguish "the monitor has stopped reporting" from "Home Assistant is
restarting", and a roof-close automation has to tell those apart.

**`binary_sensor.<instance>_safety_monitor_unsafe` is `on` when conditions are
UNSAFE.** That is Home Assistant's `SAFETY` device class convention — on means
problem. An abort automation triggers on `to: "on"`; one written against `off`
fires when the sky *clears*.

## Sessions

A session is **everything since the most recent local noon on the rig** — the
boundary N.I.N.A.'s own image-history dockable and Target Scheduler use. It
spans targets, filters and exposure lengths, and integration time sums the
actual exposures rather than multiplying a count by a nominal length.

Change the boundary under **Settings → Devices & Services → N.I.N.A. →
Configure** if the imaging PC's Windows clock runs UTC, which is common on
hosted rigs. Every N.I.N.A. timestamp is local to that clock, so on a site at
UTC−05:00 the noon default lands at 07:00 site time — in the middle of the dawn
flat run, splitting one night across two sessions. Set it to an hour that is
genuinely midday on site.

Until the mount has connected once the rig's clock is unknown, and the boundary
falls at noon in **Home Assistant's** zone instead.

---

## Entities

Entity ids are `<domain>.<instance>_<name>` — with the default instance name
`N.I.N.A.`, `sensor.n_i_n_a_mount_altitude`. The reference rig registers 103
entities, two of them its switch hub's channels. A dome adds ten more, and a
weather source reporting cloud cover, sky quality or star FWHM adds one each.

| Device | Entities |
|---|---|
| Camera | temperature, cooler power, gain, offset, state; target temperature and USB limit (`number`); cooler and dew heater (`switch`); exposing (`binary_sensor`); abort exposure (`button`) |
| Mount | RA, declination, altitude, azimuth, sidereal time, side of pier, time to meridian flip; at park, at home (`binary_sensor`); tracking rate (`select`); park, unpark, find home (`button`) |
| Focuser | position, temperature, step size; the last autofocus run — time, starting and final position, starting and best measured HFR, temperature, duration, filter, R² and the fitted HFR; position (`number`); moving, autofocus failed (`binary_sensor`); autofocus (`button`) |
| Filter Wheel | filter (`select`); moving (`binary_sensor`) |
| Guider | RMS total, RA and declination, status; guider (`switch`); clear calibration (`button`) |
| Rotator | position, mechanical position (`number`); reverse (`switch`); moving, synced (`binary_sensor`) |
| Flat Panel | cover state; brightness (`number`); light (`light`); cover (`switch`) |
| Weather | temperature, humidity, dew point, pressure, wind speed/direction/gust, rain rate, sky brightness, sky temperature, cloud cover, sky quality, star FWHM |
| Safety Monitor | unsafe, connected (`binary_sensor`) |
| Dome | shutter status; azimuth (`number`); following (`switch`); at park, at home, slewing (`binary_sensor`); open, close, park, home (`button`) |
| Switch | one entity per channel the driver reports, by shape: read-only becomes a `sensor`, an on/off channel a `switch`, a range a `number` |
| Hub | weather source; session image count, integration time, average/best/worst HFR, average stars, session start; last image HFR, star count, mean ADU, exposure, RMS, target, filter; sequence target and progress; flats state and iterations; last frame and livestack (`image`); errors (`event`); sequencer running, imaging and scheduler waiting (`binary_sensor`); wait ends at, last frame at; sequence start/stop (`button`); livestack (`switch`) |

Some entities ship **disabled by default**: the three `flats_*` sensors (see
[Flats](#flats)), `sequence_progress`, and diagnostics you are unlikely to want
on a dashboard. Enable them from the entity page.

`binary_sensor.<instance>_sequencer_running` and
`binary_sensor.<instance>_imaging` answer different questions, and on a Target
Scheduler rig they disagree for hours at a time. **Sequencer running** is the
sequencer: it stays `on` through a wait for full dark, for a target to clear
the horizon, for moon separation, or for a safety loop to find conditions safe.
**Imaging** is frames arriving — a rising image count, a camera exposing, or an
`IMAGE-SAVE` in the last five minutes.

Use *sequencer running* to tell a working night from a stopped sequencer, and
*imaging* to tell whether it is taking pictures right now.

`binary_sensor.<instance>_sequence_running` is **gone**, and neither new entity
claims its `unique_id`: it reported the imaging heuristic under a name that
promised the sequencer, so repointing it silently would have changed what every
automation using it meant. The old row goes unavailable on upgrade — delete it,
and point each automation at whichever of the two it actually wanted. The
shipped **session shutdown** blueprint wants *sequencer running*: on *imaging*
it would shut the rig down during any wait.

### Knowing the rig is working

Three entities describe why frames may not be arriving:

- **`binary_sensor.<instance>_sequencer_running`** — the sequencer is executing.
- **`binary_sensor.<instance>_scheduler_waiting`** — Target Scheduler is
  waiting, with **`sensor.<instance>_wait_ends_at`** saying until when. The
  event carries a time and no reason, so darkness, moon separation, target
  altitude and a meridian window all look the same here. A **safety** wait is
  not one of them: when the sequence loops waiting for conditions to clear,
  that is a N.I.N.A. container and this entity stays `off` —
  `binary_sensor.<instance>_safety_monitor_unsafe` is what covers it.
- **`sensor.<instance>_last_frame_at`** — when the newest frame of any type was
  saved, dawn flats included. It is `unknown` until the first frame of the
  process.

**Detecting a stall needs more care than it looks**, and the recorded nights
say why:

| Observed | Where |
|---|---|
| **31.5 min** between consecutive lights | a normal night, nothing wrong |
| **116 min** with no frame at all | conditions went unsafe at 04:26 and the sequence looped until dawn |
| **11.6 min** after a wait ends before the first frame | slew, rotation, filter change, guider settle |

The safety case is the one that catches people: `scheduler_waiting` is `off`
throughout, because the loop is a N.I.N.A. container rather than a Target
Scheduler wait. `Date` on a frame is when it was *saved*, so the clock also
starts a full exposure behind.

So a usable rule is *longest exposure + ~30 minutes*, only while running, not
waiting and safe, and guarded for `last_frame_at` being `unknown` — which it is
after every N.I.N.A. restart, since the image history is process-scoped. A
one-line template condition is how you get woken at 5am by a passing cloud.

The **imaging stall alert** blueprint (`imaging_stall_alert.yaml`) is that rule,
done carefully. It is notify-only: it never stops, parks or closes anything. It
watches three shapes of stall:

| Arm | Fires when |
|---|---|
| **Unreachable** | *sequencer running* has been `unavailable` for 2 minutes — N.I.N.A. or its API is gone. No other gate applies, since every entity of the rig is down with it. |
| **Parked** | the mount parks while the sequencer is still running. |
| **Quiet** | checked every minute: *imaging* has been off for 20 minutes, **or** no frame has been saved for longest exposure (default 600 s) + 30 minutes. |

The quiet arm stays silent while the sequencer is stopped, while the scheduler
is waiting, for 15 minutes after a wait ends, and in daylight. Every clock
starts no earlier than the sequencer did, so last night's final frame does not
raise an alert the minute tonight's sequence starts. All of these are inputs.

Two suppressions to know about:

- **An unsafe rig does not alert.** Looping on unsafe conditions is the rig
  behaving correctly, and `weather_abort` is the blueprint that speaks. Leave the
  safety input empty only if the rig has no safety monitor. On a rig that has
  one, an empty input means an alert through every weather hold.
- **`night_only` is on by default**, so the daytime wait for darkness is not a
  stall. Turn it off if you image the sun. It reads `sun.sun`; without that
  entity it does not suppress anything.

Guiding has its own blueprint, `guiding_alert.yaml`, and this one does not
duplicate it: a lost guide star that stops the frames shows up here as a stall,
with the guider state in the message.

The alert is a persistent notification plus a message to your notify entity. It
reads from bed: minutes quiet, the last frame's target and filter, camera state,
temperature and cooler power, guider, mount park and home, autofocus, the newest
error. It reminds you every 60 minutes, at most twice (set reminders to 0 for
none). After that it stays quiet
but keeps waiting, so when a frame lands or the sequencer stops it dismisses the
notification and says which of the two happened. A clear is never sent without
an alert before it. A sequence that finishes looks the same as one stopped by
hand, so the message does not claim the night completed.

Limits: a Home Assistant restart while an alert is open loses both the
notification and the clear, because persistent notifications and a pending wait
do not survive it. The settle gate also mutes the quiet arm for
`settle_minutes` after a restart. A rig that is imaging but producing bad frames
is not a stall, and this blueprint does not see it.

`sensor.<instance>_sequence_progress` is disabled because it reads `unknown` on
a Target Scheduler rig: the scheduler chooses targets as the night goes and
publishes no count to measure progress against. Enable it only if you run a
plain Advanced Sequencer sequence with looping containers. The observatory card
omits its progress bar while the sensor has no value.

`sensor.<instance>_session_start` is one of those diagnostics. It is not when
N.I.N.A. started: it is the boundary the session statistics count from, the
most recent `rollover_hour` (noon by default) in the rig's local time, so it
reads the same time every day and does not move when N.I.N.A. or the PC
restarts. Enable it if a night's statistics look split in two — any hour other
than your `rollover_hour` means the rig's clock offset is not being picked up.

`sensor.<instance>_session_avg_hfr` carries `by_target` and `by_filter`
attributes: a per-target and per-filter breakdown of count, integration hours
and mean HFR.

`sensor.<instance>_mount_time_to_meridian_flip` carries
`flip_fires_at_minutes` — the reading at which N.I.N.A. actually flips. It is
`(MaxMinutesAfterMeridian − MinMinutesAfterMeridian)`, **not zero**, and both
come from the profile, so a warning threshold written as a bare number is not
portable between rigs.

## Weather

Weather channels appear **on their first real reading**, so configuring the
integration in daylight yields no weather entities until the source starts
reporting. They persist once created.

A channel reads **`unknown`** while the source that created it reports no value
(`"NaN"`), and **`unavailable`** once a different source is active that cannot
provide it — two sources on the same rig are routinely disjoint in both
directions.

**Weather is telemetry, not an abort authority.** A forecast-backed
`ObservingConditions` source — OpenMeteo is a 10-minute gridded forecast — reads
0% cloud while you sit under a cloud. Abort belongs to
`binary_sensor.<instance>_safety_monitor_unsafe`. Weather channels are worth
watching, and worth using to hold a *resume* back; never to authorise imaging.

## Dome

The dome entities are **derived from the specification and untested against
hardware** — nobody involved has a dome. They are shipped rather than withheld
because a dome owner can then report what is wrong. If you have one, findings
are welcome on the
[issue tracker](https://github.com/dgivens/homeassistant-nina-astrophotography/issues).

## Livestack

`switch.<instance>_livestack` exists whether or not the Livestack plugin is
installed. Without it the switch reads `off`, and turning it on fails with an
error rather than silently doing nothing.

## Flats

**The `flats_*` sensors only see flats started through the API**, and this
integration has no action that starts them. A Target Scheduler flat run or the
flat wizard leaves the state `Finished` with both iteration counts `unknown`
straight through, so all three ship **disabled**. `/flats/status` also has no
event, so they are polled every 5 minutes. Enable them only if something else
starts flats through the API.

What a flat run does to the rest of the rig's entities:

- **`sensor.<instance>_session_image_count` counts the flats**; its
  `light_count` attribute does not. Integration time and the HFR and star
  statistics are over lights only.
- **The `last_image_*` sensors keep the last light frame**, so a calibration
  run does not overwrite your imaging readouts.
- **`sensor.<instance>_last_frame_at` counts flats**, and
  **`binary_sensor.<instance>_imaging`** is `on` while they are exposing, so a
  flat run reads as the rig working.
- **The flat panel's entities appear the first time N.I.N.A. connects the
  panel**, which on many rigs is only the flat run. After a Home Assistant
  restart they read `unavailable` until it connects again. While it is
  connected, a scene or automation that touches the panel's light or brightness
  competes with N.I.N.A.'s own brightness control and spoils that flat set.

## Autofocus

`sensor.<instance>_focuser_last_autofocus` and the `autofocus_*` sensors beside
it publish N.I.N.A.'s last autofocus report — its time, where the run started
and finished in steps, the HFR before and during the sweep, the focuser
temperature at the run, how long it took, and the filter it was measured
through. R² and the fitted HFR are diagnostics, disabled by default.

**`autofocus_hfr` is the lowest HFR the sweep actually measured**, not the
`CalculatedFocusPoint` N.I.N.A. moved to. Under a `TREND*` curve fitting that
calculated value is the mean of the trendline intersection and the quadratic
minimum, and the intersection extrapolates to a star size the optics cannot
produce — on a captured run it read 1.09 px against a best measured 1.55 px.
Its offset also changes if you change the curve fitting in your profile, which
is why it is the disabled `autofocus_fitted_hfr` and not the headline number.
Against `autofocus_starting_hfr`, which is also measured, the pair is the
closest thing to a before-and-after the report offers — but it is not one.
Both are measured at sweep steps, while the run moves to a fitted minimum
between two steps whose HFR is never measured, so the "after" can read worse
than the "before" on a run that improved focus. On a captured run it does:
1.552 px against a starting 1.519 px.

Four things the report itself cannot tell you:

- **A rejected run replaces the last good one.** N.I.N.A. writes the report
  before it decides whether the run was any good, and the file carries no
  verdict. `binary_sensor.<instance>_focuser_autofocus_failed` is that
  judgement, made by comparing R² with your profile's `RSquaredThreshold`.
- **A run that hangs writes no report at all**, so these sensors keep showing
  the previous one. `last_autofocus` is how old it is; the failed flag catches
  the hang separately, as a start nothing answered.

  The flag carries what it judged, because `on` alone is not actionable:

  | attribute | |
  |---|---|
  | `reason` | `hung`, `rejected`, or absent. **This is the one to branch on** — a hung run wants the sequence looked at, a rejected one the focus range or the star detector. And only `hung` means the report every other autofocus sensor is showing belongs to a *different* run. |
  | `r_squared` | the R² the judgement used — the worst of the run's `RSquares` |
  | `r_squared_threshold` | your profile's `RSquaredThreshold` |

  Compare against `r_squared` rather than a value of your own: the run's R² is
  the worst of `RSquares`, which is not quite the worst of the equations
  `fits` can be parsed from, and a verdict read off the other one can
  contradict the flag it sits beside.
- **The report outlives a restart and the night.** A value here can be from
  three nights ago. Date it against `last_autofocus` before believing it.
- **Everything here is per attempt.** N.I.N.A. retries a rejected run, and only
  the last attempt's report survives — so `autofocus_duration` undercounts what
  a troublesome run cost the night.

`sensor.<instance>_focuser_temperature` minus
`sensor.<instance>_focuser_autofocus_temperature` is the ΔT that N.I.N.A.'s own
"autofocus after temperature change" trigger is watching, since that trigger
measures from the last run. A template sensor over the two gives you a "next
autofocus in X °C" gauge.

`autofocus_hfr` and `autofocus_starting_hfr` read `unknown` on a
`CONTRASTDETECTION` run: that method measures a contrast score rather than
star sizes, so its numbers are not pixels and are not comparable with the rest.
The positions and the duration are unaffected.

### Plotting the V-curve

`sensor.<instance>_focuser_last_autofocus` carries the whole sweep in its
`curve` attribute — one row per position the run visited, ascending in focuser
position:

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

`value` is HFR in pixels under a `STARHFR` run and a contrast score under
`CONTRASTDETECTION`; the `method` attribute beside it says which.

**A `value` of `null` means that frame measured nothing** — the star detector
found nothing usable, which out at the ends of a sweep means the stars bloated
past its cut. The position is kept, so the sweep's real range survives and a
chart breaks its line at the failure instead of drawing a chord across it. Two
nulls on one side only is the signature of a sweep that is too wide for your
focal ratio, which is worth seeing rather than being smoothed away.
`measured_points` counts the rows that measured something, so it is less than
the curve's length on a run that lost frames.

**`error` is the spread of star sizes across that frame**, not the uncertainty
on the V. N.I.N.A. draws it as the point's error bar. A fat bar means the field
has a range of star sizes — tilt, field curvature, elongation — so it reads as
"check the optics", not "distrust this point". On a y axis spanning the whole
V these bars are nearly invisible except near the vertex; a shaded band reads
better than caps.

Three things a card should not assume:

- **The sweep is not necessarily centred on `autofocus_starting_position`.** On
  one captured run the starting position is the third of nine points.
- **`autofocus_starting_hfr` is not the curve's value at that position.** They
  are two separate exposures — 1.519 px against the sweep's 1.552 px at the
  same step on a captured run — so a "starting HFR" marker will sit visibly off
  the curve. That is correct, not a bug.
- **The final position usually isn't on the curve at all.** N.I.N.A. moves to
  the fitted minimum, which falls between two steps, and the HFR there was
  never measured.

#### The fitted overlay

The same attribute set carries what N.I.N.A.'s own autofocus chart draws on
top of the points:

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

`coefficients` is highest power first, so `[a, b, c]` evaluates as
`a·x² + b·x + c` and plots directly. N.I.N.A. sends the fit as an equation
string; it is parsed here once rather than in JavaScript on every render, and
`equation` is kept beside it because only the polynomial forms have been
observed — a hyperbolic or gaussian fit yields `coefficients: null` and the
string is then the only record of it. Fits the run did not use are omitted.

`r_squared` here is **per fit**, which is what labels one line in a legend.
`sensor.<instance>_focuser_autofocus_r_squared` is the *worst* fit of the run,
which is the right number for a pass/fail threshold and the wrong one for a
chart.

`minima` is every marker N.I.N.A. computed. Read the second one by position in
the list rather than by name: it is named after whichever curve your profile
fits, so a `TRENDPARABOLIC` run calls it `QuadraticMinimum` and a hyperbolic
one will not. The final position — `sensor.<instance>_focuser_autofocus_position`
— is the componentwise **mean** of the two, so when a run lands somewhere odd,
which marker dragged it is the diagnostic.

**Do not let `TrendLineIntersection` set your y axis.** The two trend lines
extrapolate the V's wings until they cross, which is well below any star the
optics can produce — 0.333 px on the run above, against a best measured
1.552 px. Clamp the axis to the measured points.

An attribute, not entities: a curve is not a series, and there is no useful
statistic over "the fourth point of whatever run happened last".
`sensor.<instance>_focuser_autofocus_hfr` is the series — one number per run,
recorded — and the curve is the shape of the single run behind it. Nothing in
Home Assistant charts an attribute natively, so it needs a custom card, an
ApexCharts `data_generator`, or a template. [`nina-autofocus-card`](#lovelace-cards)
is the one that ships; everything above is what you need to know to write
your own.

## Errors

`event.<instance>_error` fires `platesolve_failed`, `camera_download_timeout`
and `autofocus_timeout`. It is **best-effort and solver-specific**: N.I.N.A.'s
`ERROR-*` events are log-file regex scrapes, and `ERROR-PLATESOLVE` matches
ASTAP only, so a failure from another solver produces nothing. The autofocus
arm is this integration's own timeout verdict rather than N.I.N.A.'s
`ERROR-AF`, which appears dead in the plugin.


---

## Actions

Call these from automations, scripts, or **Developer Tools → Actions**.

Every action takes an optional **rig**, picked as a device — the hub, or any of
that rig's equipment. With one instance configured you can leave it off; with
two, an untargeted call is refused rather than guessed at, even when only one
of them is currently loaded. From YAML you may also identify the rig by one of
its entities, or by an area holding them.

| Action | Description | Parameters |
|---|---|---|
| `camera_cool` | Cool the sensor | `temperature` (°C), `minutes` |
| `camera_warm` | Warm the sensor | `minutes` |
| `camera_capture` | Single exposure | `duration` (s), `gain`, `save` |
| `camera_abort_capture` | Abort the exposure | — |
| `mount_slew` | Slew to coordinates | `ra_degrees`, `dec_degrees` (**J2000, degrees**) |
| `mount_park` / `mount_unpark` | Park / unpark | — |
| `mount_set_tracking` | Sidereal tracking on or off | `enabled` |
| `focuser_move` | Absolute move | `position` (steps) |
| `focuser_auto_focus` | Run an autofocus | — |
| `filterwheel_change_filter` | Change filter | `filter_index` |
| `guider_start` | Start guiding | `force_calibration` |
| `guider_stop` | Stop guiding | — |
| `dome_open` / `dome_close` / `dome_park` | Dome control | — |
| `sequence_start` / `sequence_stop` | Sequence control | — |
| `sequence_load` | Load a sequence | `sequence_name` |

**`mount_slew` takes J2000 degrees**, and sends them through untouched:
N.I.N.A. transforms to the mount's own equatorial system internally. Two ways
to get this wrong, neither of which anything can catch — the value is valid
either way: do not feed it a figure read back from
`sensor.<instance>_mount_right_ascension`, which reports the *mount's* epoch in
*hours*; and catalogues and N.I.N.A.'s framing tab quote RA in h:m:s, so
multiply those hours by 15.

**There is no dither action.** The API exposes no dither command — dithering is
driven from inside a sequence, and only reported back, over `GUIDER-DITHER`.

An action returns when N.I.N.A. **accepts** the command, not when the equipment
finishes moving. Watch the entities for that. Out-of-range input is refused
client-side: the API silently clamps it and reports success.

```yaml
- alias: "Cool the camera at sunset"
  triggers:
    - trigger: sun
      event: sunset
      offset: "-00:30:00"
  actions:
    - action: nina_astrophotography.camera_cool
      target:
        device_id: 0123456789abcdef0123456789abcdef
      data:
        temperature: -10
        minutes: 15
```

---

## Events

The integration holds a WebSocket connection to N.I.N.A. alongside its polling,
and **every N.I.N.A. event fires a Home Assistant event** — no polling delay.
The socket is the primary source; polling backstops it.

`IMAGE-SAVE` → `nina_image_save`, `MOUNT-AFTER-FLIP` → `nina_mount_after_flip`,
and so on. Everything also fires as `nina_event`.

The payload is:

| Field | |
|---|---|
| `event` | the N.I.N.A. event name, e.g. `IMAGE-SAVE` |
| `time` | ISO 8601, offset-aware |
| `instance` | the instance name, so a two-rig install can tell them apart |
| `entry_id` | that instance's config entry id, for an exact match |
| `data` | the event's own scalar fields, under N.I.N.A.'s key names |
| `frame` | the mapped frame statistics on `IMAGE-SAVE`, otherwise `null` |

```yaml
- alias: "Report each saved frame"
  triggers:
    - trigger: event
      event_type: nina_image_save
  conditions:
    - condition: template
      value_template: >
        {{ trigger.event.data.entry_id
           == config_entry_id('sensor.n_i_n_a_session_image_count') }}
  actions:
    - action: notify.mobile_app_myphone
      data:
        message: >
          HFR {{ trigger.event.data.frame.hfr | round(2) }},
          {{ trigger.event.data.frame.stars }} stars
```

`nina_websocket_connected` and `nina_websocket_disconnected` fire on connection
**transitions** only.

---

## Blueprints

Copy `blueprints/automation/nina_astrophotography/` into your Home Assistant
config directory, then **Settings → Automations & Scenes → Blueprints**.

| Blueprint | What it does |
|---|---|
| `weather_abort.yaml` | The safety automation: on unsafe conditions **or** the safety monitor dropping out, stop the sequence, park, warm the camera, close the dome. Optionally resumes when conditions clear. |
| `session_startup.yaml` | Unpark, track, open the dome, cool the camera, load and start a sequence. |
| `session_shutdown.yaml` | The scheduled end of night: stop, park, warm, close. |
| `meridian_flip_warning.yaml` | Warns ahead of the flip, and again when N.I.N.A. commits to it and completes it. |
| `guiding_alert.yaml` | Notifies, and optionally refocuses, when guide RMS stays high. |
| `imaging_stall_alert.yaml` | Notifies when frames stop for a bad reason — rig unreachable, mount parked mid-sequence, or no frames — and clears itself when they resume. See [Knowing the rig is working](#knowing-the-rig-is-working). |

All six take a device or entity picker for the rig they act on, so they work on
a two-rig install and need no editing.

`weather_abort.yaml` takes **no weather trigger**, deliberately — see
[Weather](#weather). Its optional resume conditions are where weather belongs.

---

## Lovelace cards

Copy the files from `www/` into your `/config/www/` folder and register each as
a dashboard resource (**Settings → Dashboards → ⋮ → Resources**, type
*JavaScript Module*, URL `/local/<file>.js`).

```yaml
type: custom:nina-observatory-card
prefix: n_i_n_a          # the slugified instance name your entity ids carry
device_id: 0123…         # nina-observatory-card only: which rig its buttons
                         # act on. Needed once two rigs are configured.
```

`N.I.N.A.` slugifies to `n_i_n_a`, which is also the default. Copy yours from
any entity id.

| Card | |
|---|---|
| `nina-observatory-card` | Session banner and progress, equipment chips, meridian countdown, camera / mount / focuser readings, guiding RMS bars, last-frame statistics, and one-tap controls. Stopping a sequence, parking and closing the dome ask for confirmation. |
| `nina-frame-stats-card` | Per-frame HFR, star-count and ADU sparklines with a trend, and a per-filter breakdown. The series is sampled in the browser as frames arrive, so a page reload starts it over. |
| `nina-autofocus-card` | The last autofocus run as a chart: the measured V with error bars, the fitted curves and their minima, and the position the run left the focuser at. Says whether the fit passed your profile's R² threshold, reports the starting HFR against the best measured so a run that bought nothing says so, and flags a fit that landed at the edge of the sweep. Takes an optional `temperature_delta:` (default 2 °C) — the drift since the run worth flagging, which is really your sequence's own refocus trigger. |
| `nina-image-panel-card` | The latest image with a filmstrip of recent frames, an ADU histogram, and per-frame statistics. Needs `host:` (and `port:`) — it fetches images from N.I.N.A. directly. |
| `nina-sky-map-card` | A live star chart with the current pointing, a trail of recent positions, and the meridian. **Set `latitude:`** — it projects the whole star field and defaults to 40°N. |
| `nina-weather-card` | Safety banner, atmospheric and wind conditions, and sky quality. Channels the source cannot provide are shown as absent rather than zero. |

---

## Upgrading to 2.0

**There is no migration, and nothing renames itself.** Home Assistant keys the
entity registry on `unique_id`, so an existing install keeps the entity ids it
already has — dashboards and automations keep working — while entities move
onto their new devices. A **fresh** install gets the new ids.
[`docs/2.0-renames.md`](docs/2.0-renames.md) maps every one.

What does need your attention:

- **Three actions changed their parameters**, because in 1.4.5 they silently did
  nothing: `camera_capture` takes `duration` (was `exposure`, which was never
  sent) and no longer offers `binning` or `filter_index` (which bound nothing);
  `sequence_load` takes `sequence_name` (was `path`, which the API ignores);
  `mount_slew` takes `ra_degrees`/`dec_degrees` in **J2000 degrees** (was `ra`
  in hours) — see [Actions](#actions).
- **1.4.5's five blueprints were rewritten** and their inputs changed, and
  `imaging_stall_alert.yaml` is new. Re-import them and rebuild the
  automations. The old ones referenced entities 2.0 does not create, so they
  were inert either way.
- **The Lovelace cards need `prefix:`** — see [Lovelace cards](#lovelace-cards).
- **`switch.<instance>_flat_panel_light` is gone** — the `light` entity survives.
  Its old registry row lingers as unavailable until you delete it.
- **The poll interval is capped at 60 s**; an entry storing more keeps its rate
  until the options form is next submitted.
- **Entity attributes no longer carry driver metadata.** It is on the device.
- **Long-term statistics restart for two session sensors.**
  `sensor.<instance>_session_integration_time` moves from minutes to hours and
  from `total_increasing` to `measurement`; `sensor.<instance>_session_image_count`
  also becomes `measurement`. Both keep their `unique_id`, so an upgraded
  install keeps the entity and loses its recorded history — the two statistic
  types are not migrated between.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot connect" during setup | Check the Advanced API plugin is running: open `http://<IP>:1888/v2/api/version` in a browser **from the Home Assistant machine**. |
| Entities read `unavailable` | That device is not connected in N.I.N.A. Connect it there. |
| No weather entities | See [Weather](#weather) — channels appear on their first real reading. |
| An action failed | The message carries N.I.N.A.'s own refusal. The HTTP status is almost always 200, so the real reason is in the body — and in `Settings → System → Logs`. |
| An action says several instances are configured | Add a device target to say which rig you mean. |
| A card is blank | Set `prefix:` to your instance's slug — the default `n_i_n_a` only matches the default instance name. |
| `Last Image HFR` does not change during a flat run | Correct. The last-image sensors report the last **light** frame, so a calibration run leaves them where they were rather than blanking your imaging readouts. They read `unknown` only when the session has no lights at all. |

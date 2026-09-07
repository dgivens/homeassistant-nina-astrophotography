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
`N.I.N.A.`, `sensor.n_i_n_a_mount_altitude`. The reference rig registers 89
entities. A dome adds ten more, and a weather source reporting cloud cover,
sky quality or star FWHM adds one each.

| Device | Entities |
|---|---|
| Camera | temperature, cooler power, gain, offset, state; target temperature and USB limit (`number`); cooler and dew heater (`switch`); exposing (`binary_sensor`); abort exposure (`button`) |
| Mount | RA, declination, altitude, azimuth, sidereal time, side of pier, time to meridian flip; at park, at home (`binary_sensor`); tracking rate (`select`); park, unpark, find home (`button`) |
| Focuser | position, temperature, step size; position (`number`); moving, autofocus failed (`binary_sensor`); autofocus (`button`) |
| Filter Wheel | filter (`select`); moving (`binary_sensor`) |
| Guider | RMS total, RA and declination, status; guider (`switch`); clear calibration (`button`) |
| Rotator | position, mechanical position (`number`); reverse (`switch`); moving, synced (`binary_sensor`) |
| Flat Panel | cover state; brightness (`number`); light (`light`); cover (`switch`) |
| Weather | temperature, humidity, dew point, pressure, wind speed/direction/gust, rain rate, sky brightness, sky temperature, cloud cover, sky quality, star FWHM, source |
| Safety Monitor | unsafe, connected (`binary_sensor`) |
| Dome | shutter status; azimuth (`number`); following (`switch`); at park, at home, slewing (`binary_sensor`); open, close, park, home (`button`) |
| Switch | one entity per channel the driver reports, by shape: read-only becomes a `sensor`, an on/off channel a `switch`, a range a `number` |
| Hub | session image count, integration time, average/best/worst HFR, average stars, session start; last image HFR, star count, mean ADU, exposure, RMS, target, filter; sequence target and progress; flats state and iterations; last frame and livestack (`image`); errors (`event`); sequence running (`binary_sensor`); sequence start/stop (`button`); livestack (`switch`) |

Some entities ship **disabled by default**: the three flat-wizard sensors (see
[Flats](#flats)) and diagnostics you are unlikely to want on a dashboard.
Enable them from the entity page.

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

A channel the active source cannot provide reads **`unavailable`**, not
`unknown` — two sources on the same rig are routinely disjoint in both
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

`/flats/status` observes **only flats started through the API**. A Target
Scheduler flat run reads `Finished` with `-1` iterations straight through, so an
entity reporting a stale `Finished` all night is worse than none: the three
`flats_*` entities ship **disabled**. Enable them if you start flats through the
API.

## Errors

`event.<instance>_error` is **best-effort and solver-specific**. N.I.N.A.'s
`ERROR-*` events are log-file regex scrapes: `ERROR-PLATESOLVE` matches ASTAP
only, so a failure from another solver produces nothing. The autofocus arm is
this integration's own timeout verdict rather than N.I.N.A.'s `ERROR-AF`, which
appears dead in the plugin.


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

All five take a device or entity picker for the rig they act on, so they work on
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
- **All five blueprints were rewritten** and their inputs changed. Re-import
  them and rebuild the automations. The old ones referenced entities 2.0 does
  not create, so they were inert either way.
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

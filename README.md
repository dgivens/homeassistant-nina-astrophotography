> [!NOTE]
> **AI-Assisted Development**
>  
> [![AI Assisted](https://img.shields.io/badge/built%20with-Claude%20AI-7b8de8?style=flat-square&logo=anthropic)](https://claude.ai) All code has been reviewed, tested against a live N.I.N.A. instance, and is maintained by a human author. AI assistance was used to accelerate development — the design decisions, testing, and ongoing maintenance are my own.

# N.I.N.A. Astrophotography – Home Assistant Integration

Monitor and control a [N.I.N.A.](https://nighttime-imaging.eu) imaging rig from
Home Assistant, through N.I.N.A.'s
[Advanced API plugin](https://github.com/christian-photo/ninaAPI) (v2).

It provides:

- sensors for the camera, mount, focuser, guider, weather and the current
  session
- buttons and actions to cool, slew, park, focus and run sequences
- Home Assistant events for everything N.I.N.A. reports
- six dashboard cards
- six automation blueprints

This is a maintained fork of
[C3X0Astro/homeassistant-nina-astrophotography](https://github.com/C3X0Astro/homeassistant-nina-astrophotography),
which is no longer updated. Licensed GPL-3.0, like the original.

**Upgrading from 1.4.x?** Follow [the upgrade guide](docs/upgrading-to-2.0.md)
first.

## Requirements

- N.I.N.A. 3.x on the imaging PC.
- The Advanced API plugin, installed from N.I.N.A.'s **Plugins** tab and
  enabled under **Options → Advanced API**. Note the port (default 1888).
- Home Assistant 2026.9.0 or later, able to reach the imaging PC on that port.

> [!WARNING]
> The Advanced API has no authentication. Anything that can reach the port can
> move your mount. Keep it on your LAN or a VPN, never exposed to the internet.

## Installation

### With HACS

1. In HACS, open the **⋮** menu → **Custom repositories**.
2. Enter `https://github.com/dgivens/homeassistant-nina-astrophotography`, choose
   type **Integration**, and click **Add**.
3. Search HACS for **N.I.N.A. Astrophotography** and click **Download**.
4. Restart Home Assistant.
5. Continue with [Setup](#setup).

### Manually

1. Download this repository and copy its `custom_components/nina_astrophotography`
   folder into your Home Assistant config directory, so you end up with
   `config/custom_components/nina_astrophotography/`.
2. Restart Home Assistant.
3. Continue with [Setup](#setup).

### Setup

1. Go to **Settings → Devices & Services → Add Integration** and choose
   **N.I.N.A. Astrophotography**.
2. Enter:
   - **Host**: the imaging PC's IP address or hostname.
   - **Port**: the Advanced API port, usually `1888`.
   - **Instance name**: defaults to `N.I.N.A.`. It becomes part of every entity
     id (`N.I.N.A.` gives `sensor.n_i_n_a_…`), so choose it before you build
     dashboards. A second rig needs a different name.
   - **Poll interval**: defaults to 10 seconds. Most updates arrive
     immediately over N.I.N.A.'s event stream, so you rarely need to change
     this.

Equipment shows up as devices the first time N.I.N.A. reports it connected, so
expect devices to appear as your sequence connects things.

### Removal

Go to **Settings → Devices & Services → N.I.N.A. Astrophotography → ⋮ →
Delete**. This removes the devices, entities and, once no instances are left,
the card resources. If you manage dashboard resources in YAML, remove the six
card entries yourself.

## Read this before writing automations

- **`binary_sensor.<instance>_safety_monitor_unsafe` is `on` when it is
  unsafe.** Trigger an abort on `to: "on"`. An automation triggering on
  `"off"` fires when the sky clears.
- **Don't use weather sensors as a safety source.** Forecast-based sources can
  report clear skies under cloud. Abort on the safety monitor; use weather
  only to decide whether to resume.
- **A disconnected device's entities become `unavailable`, not `off`.**
- **`mount_slew` takes J2000 coordinates in degrees.** Catalogues give RA in
  hours: multiply by 15. Don't feed it the mount RA sensor, which reports hours
  in the mount's own epoch.
- **Actions return when N.I.N.A. accepts the command,** not when the equipment
  finishes. Wait on the entities if you need to know it's done.
- **`sequencer_running` and `imaging` are different.** The sequencer stays
  running while it waits for darkness or safe conditions; `imaging` is only on
  while frames are being taken.
- **Sessions roll over at noon on the imaging PC's clock.** If that clock runs
  UTC, change the hour under **Configure** on the integration, or nights will
  be split in two.

[docs/reference.md](docs/reference.md) has the full behaviour of every entity:
sessions, flats, autofocus, weather, stall detection, and the attributes
available for your own cards.

<a id="lovelace-cards"></a>

## Dashboard cards

The integration installs six cards and registers them with Home Assistant
automatically. To add one:

1. Open a dashboard and click **Edit dashboard** (the pencil icon).
2. Click **Add card** and search for **N.I.N.A.**.
3. Pick a card. With one rig, it works without any configuration. With two,
   pick the rig in the card's **N.I.N.A. instance** field.

Or, in a card's YAML editor:

```yaml
type: custom:nina-observatory-card
```

| Card | Shows | Options (all optional) |
|---|---|---|
| `custom:nina-observatory-card` | Session summary, equipment status, meridian countdown, camera/mount/focuser readings, guiding, last frame, and controls. Stop, park and dome close ask for confirmation. | — |
| `custom:nina-frame-stats-card` | HFR, star count and ADU trends for the session's frames, and a per-filter breakdown | — |
| `custom:nina-autofocus-card` | The last autofocus run: measured points, fitted curves, final position, and whether it passed your R² threshold | `temperature_delta`: flag when the focuser has drifted this many °C since the run (default 2) |
| `custom:nina-image-panel-card` | The latest frame, recent frames, and their statistics | `refresh_on_save`, `stretch`, `show_histogram`, `show_strip` (all default `true`); `strip_count` (default 6, max 20); `quality` (JPEG, default 85) |
| `custom:nina-sky-map-card` | A star chart with the telescope's pointing, recent positions and the meridian | `trail_length` (default 60); `map_size` in px (default 320); `latitude` to override the site |
| `custom:nina-weather-card` | Safety status, weather and sky quality | — |

Every card also accepts:

- `device_id`: which rig to show, when you have more than one. Use the
  visual editor's picker rather than typing an id.
- `prefix`: only needed if you renamed the instance and some readings are
  blank. Set it to the start of your entity ids, e.g. `my_rig` for
  `sensor.my_rig_mount_altitude`.

Cards show readings in the units Home Assistant is set to use. Camera
temperatures are conventionally in °C in astrophotography software, so on a
US customary system you may want to set °C as the display unit for the camera
temperature entities.

If your dashboard resources are managed in YAML (`resource_mode: yaml`, or
`mode: yaml` without `resource_mode`), the integration can't register the
cards. It logs the six entries to add; each looks like this:

```yaml
lovelace:
  resources:
    - url: /nina_astrophotography_static/nina-observatory-card.js
      type: module
```

## Blueprints

To add one, go to **Settings → Automations & Scenes → Blueprints → Import
Blueprint** and paste its URL from the table. Then click **Create automation**
on the imported blueprint and pick your rig's entities.

| Blueprint | What it does |
|---|---|
| [Unsafe conditions abort](https://github.com/dgivens/homeassistant-nina-astrophotography/blob/main/blueprints/automation/nina_astrophotography/weather_abort.yaml) | When the safety monitor reports unsafe or stops reporting: stop the sequence, park, warm the camera, close the dome. Can resume when conditions clear. |
| [Session startup](https://github.com/dgivens/homeassistant-nina-astrophotography/blob/main/blueprints/automation/nina_astrophotography/session_startup.yaml) | Unpark, start tracking, open the dome, cool the camera, load and start a sequence. |
| [Session shutdown](https://github.com/dgivens/homeassistant-nina-astrophotography/blob/main/blueprints/automation/nina_astrophotography/session_shutdown.yaml) | At a set time: stop, park, warm the camera, close the dome. |
| [Meridian flip warning](https://github.com/dgivens/homeassistant-nina-astrophotography/blob/main/blueprints/automation/nina_astrophotography/meridian_flip_warning.yaml) | Notifies before a meridian flip, when it starts, and when it finishes. |
| [Guiding alert](https://github.com/dgivens/homeassistant-nina-astrophotography/blob/main/blueprints/automation/nina_astrophotography/guiding_alert.yaml) | Notifies, and optionally runs autofocus, when guiding RMS stays high. |
| [Imaging stall alert](https://github.com/dgivens/homeassistant-nina-astrophotography/blob/main/blueprints/automation/nina_astrophotography/imaging_stall_alert.yaml) | Notifies when frames stop for a bad reason (N.I.N.A. unreachable, mount parked mid-sequence, no frames), and clears when they resume. [Details](docs/reference.md#the-imaging-stall-alert-blueprint). |

Alternatively, copy the `blueprints/automation/nina_astrophotography/` folder
into `config/blueprints/automation/` and reload automations.

## Actions

Call these from automations, scripts, or **Developer Tools → Actions**. All are
in the `nina_astrophotography` domain.

| Action | Does | Parameters |
|---|---|---|
| `camera_cool` | Cool the camera | `temperature` (°C), `minutes` |
| `camera_warm` | Warm the camera | `minutes` |
| `camera_capture` | Take one exposure | `duration` (s), `gain`, `save` |
| `camera_abort_capture` | Abort the exposure | — |
| `mount_slew` | Slew to coordinates | `ra_degrees`, `dec_degrees` (J2000, degrees) |
| `mount_park` / `mount_unpark` | Park / unpark | — |
| `mount_set_tracking` | Sidereal tracking on or off | `enabled` |
| `focuser_move` | Move to an absolute position | `position` (steps) |
| `focuser_auto_focus` | Run autofocus | — |
| `filterwheel_change_filter` | Change filter | `filter_index` |
| `guider_start` | Start guiding | `force_calibration` |
| `guider_stop` | Stop guiding | — |
| `dome_open` / `dome_close` / `dome_park` | Dome control | — |
| `sequence_start` / `sequence_stop` | Start / stop the sequence | — |
| `sequence_load` | Load a saved sequence | `sequence_name` |

With one rig you don't need a target. With two, target a device (the rig's hub
or any of its equipment) or the action is refused. The visual action editor
gives you a device picker; in YAML, the device id is the last part of the
device page's URL.

Out-of-range values are rejected with an error. There is no dither action; the
API doesn't provide one.

```yaml
- alias: "Cool the camera before sunset"
  triggers:
    - trigger: sun
      event: sunset
      offset: "-00:30:00"
  actions:
    - action: nina_astrophotography.camera_cool
      data:
        temperature: -10
        minutes: 15
```

## Events

Every event N.I.N.A. sends becomes a Home Assistant event as it happens:
`IMAGE-SAVE` fires `nina_image_save`, `MOUNT-AFTER-FLIP` fires
`nina_mount_after_flip`, and so on. Every one also fires as `nina_event`.

| Field | Contains |
|---|---|
| `event` | the N.I.N.A. event name, e.g. `IMAGE-SAVE` |
| `time` | when it happened (ISO 8601) |
| `instance` | the instance name |
| `entry_id` | the config entry id, to tell two rigs apart |
| `data` | the event's fields, using N.I.N.A.'s names |
| `frame` | frame statistics on `IMAGE-SAVE`, otherwise `null` |

```yaml
- alias: "Report each saved frame"
  triggers:
    - trigger: event
      event_type: nina_image_save
  actions:
    - action: notify.mobile_app_myphone
      data:
        message: >
          HFR {{ trigger.event.data.frame.hfr | round(2) }},
          {{ trigger.event.data.frame.stars }} stars
```

`nina_websocket_connected` and `nina_websocket_disconnected` fire when the
connection to N.I.N.A. drops or comes back.

`event.<instance>_error` records plate-solve failures, camera download timeouts
and autofocus timeouts. It misses some errors; see
[the reference](docs/reference.md#error-events).

## Troubleshooting

**"Cannot connect" during setup.** From the Home Assistant machine, open
`http://<imaging-pc>:1888/v2/api/version` in a browser or with `curl`. If that
fails, the plugin isn't running, the port is wrong, or a firewall is blocking
it.

**Entities are `unavailable`.** That equipment isn't connected in N.I.N.A. If
every entity is unavailable, Home Assistant can't reach N.I.N.A.

**No weather entities.** Each weather entity is created on the source's first
real reading, which may not happen until evening.

**An action failed.** The error message includes N.I.N.A.'s reason. More detail
is in **Settings → System → Logs**.

**A card says "Custom element doesn't exist".** Hard-reload the page. If you
manage resources in YAML, add them as shown under
[Dashboard cards](#dashboard-cards). If you upgraded from 1.4.x, delete the old
`/local/nina-*.js` resources.

**A card shows some readings blank.** A few entities are disabled by default;
enable them from the entity's settings. If you renamed the instance, set the
card's `prefix`.

**One device's entity ids have a different prefix from the rest.** Home
Assistant includes the device's area in new entity ids. If you assigned an area
after some equipment had already appeared, only equipment added afterwards
picks it up. Change each affected entity's ID in its settings to match the
others. Cards aren't affected, but your automations are.

**`Last Image HFR` doesn't change during flats.** That's intended: the
`last_image_*` sensors show the last light frame.

**Dome problems.** The dome support hasn't been tested on real hardware.
Please [open an issue](https://github.com/dgivens/homeassistant-nina-astrophotography/issues)
with what you see.

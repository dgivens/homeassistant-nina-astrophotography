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

Connect [N.I.N.A. (Nighttime Imaging 'N' Astronomy)](https://nighttime-imaging.eu) to Home Assistant via the **[Advanced API plugin](https://github.com/christian-photo/ninaAPI)** (v2).  Monitor all equipment in real time and control your rig directly from HA automations, dashboards, and scripts.

---

## Prerequisites

1. **N.I.N.A. 3.x** installed on your imaging PC (Windows).
2. **Advanced API plugin** installed and enabled inside N.I.N.A.:
   - Open N.I.N.A. → *Plugins* tab → search "Advanced API" → Install.
   - Go to *Options → Advanced API* and confirm the port (default **1888**) and that the service is enabled.
3. Your Home Assistant instance must be able to reach the N.I.N.A. PC on the network (same LAN or VPN).

---

## Installation

### HACS (recommended)

> add this repo as a custom repository in HACS and download from there.

### Manual

1. Copy the `nina_astrophotography` folder into your HA `custom_components` directory:
   ```
   config/
   └── custom_components/
       └── nina_astrophotography/    ← this folder
   ```
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **N.I.N.A. Astrophotography**.
4. Enter the IP/hostname of your imaging PC, the API port (default `1888`) and a
   name for the instance. The name titles the entry and prefixes every device,
   so two rigs can coexist.

## Session rollover hour

A session runs from one rollover to the next, defaulting to **12:00 in the rig's
own local time** — the boundary an astrophotographer means by "last night", and
the one N.I.N.A.'s image-history dockable uses.

Change it under **Settings → Devices & Services → N.I.N.A. → Configure** if your
imaging PC's Windows clock runs UTC, which is common on hosted rigs. Every
N.I.N.A. timestamp is local to that clock, so for a site at UTC−05:00 the noon
default falls at 07:00 site time — in the middle of the dawn flat run, splitting
one night's statistics across two sessions. Set it to an hour that is genuinely
midday at the site, expressed in the rig's clock.

---

## Sensors Created

### Measurement Sensors
| Entity | Description | Unit |
|---|---|---|
| `sensor.camera_temperature` | Sensor chip temperature | °C |
| `sensor.camera_target_temperature` | Cooling setpoint | °C |
| `sensor.camera_cooler_power` | Cooler TEC duty cycle | % |
| `sensor.camera_gain` | Current gain | — |
| `sensor.camera_offset` | Current offset | — |
| `sensor.mount_ra` | Current Right Ascension | h |
| `sensor.mount_dec` | Current Declination | ° |
| `sensor.mount_altitude` | Mount altitude | ° |
| `sensor.mount_azimuth` | Mount azimuth | ° |
| `sensor.mount_time_to_meridian_flip` | Minutes until meridian flip | min |
| `sensor.focuser_position` | Focuser step position | steps |
| `sensor.focuser_temperature` | Focuser temp probe | °C |
| `sensor.guider_rms_total` | Guide error total RMS | arcsec |
| `sensor.guider_rms_ra` | Guide error RA RMS | arcsec |
| `sensor.guider_rms_dec` | Guide error Dec RMS | arcsec |
| `sensor.sequence_progress` | Sequence progress | % |
| `sensor.image_last_hfr` | Half-flux radius of last image | px |
| `sensor.image_last_star_count` | Stars detected in last image | — |
| `sensor.image_last_mean_adu` | Mean ADU of last image | — |
| `sensor.image_count` | Images captured this session | — |

### Status Sensors
| Entity | Description |
|---|---|
| `sensor.camera_status` | Camera state string |
| `sensor.camera_current_filter` | Active filter name |
| `sensor.mount_status` | Mount name/status |
| `sensor.mount_sidereal_time` | Local sidereal time |
| `sensor.focuser_status` | Focuser name/status |
| `sensor.guider_status` | PHD2 guider state |
| `sensor.sequence_status` | Sequence state |
| `sensor.sequence_target` | Current target name |

### Binary Sensors
| Entity | Description |
|---|---|
| `binary_sensor.camera_connected` | Camera connected |
| `binary_sensor.camera_cooling` | Cooler active |
| `binary_sensor.mount_connected` | Mount connected |
| `binary_sensor.mount_parked` | Mount at park position |
| `binary_sensor.mount_tracking` | Sidereal tracking on |
| `binary_sensor.mount_slewing` | Mount is slewing |
| `binary_sensor.focuser_connected` | Focuser connected |
| `binary_sensor.focuser_moving` | Focuser in motion |
| `binary_sensor.filterwheel_connected` | Filter wheel connected |
| `binary_sensor.guider_connected` | Guider connected |
| `binary_sensor.guider_active` | Actively guiding |
| `binary_sensor.dome_connected` | Dome connected |
| `binary_sensor.dome_shutter_open` | Dome shutter is open |
| `binary_sensor.sequence_running` | Sequence running |

---

## Services

Call these from automations, scripts, or the Developer Tools → Services panel.

| Service | Description | Key Parameters |
|---|---|---|
| `nina_astrophotography.camera_cool` | Cool sensor | `temperature` (°C), `minutes` |
| `nina_astrophotography.camera_warm` | Warm sensor | `minutes` |
| `nina_astrophotography.camera_capture` | Single exposure | `exposure` (s), `gain`, `filter_index`, `binning`, `save` |
| `nina_astrophotography.camera_abort_capture` | Abort exposure | — |
| `nina_astrophotography.mount_slew` | Slew to coords | `ra` (h), `dec` (°) |
| `nina_astrophotography.mount_park` | Park mount | — |
| `nina_astrophotography.mount_unpark` | Unpark mount | — |
| `nina_astrophotography.mount_set_tracking` | Toggle tracking | `enabled` |
| `nina_astrophotography.focuser_move` | Absolute move | `position` (steps) |
| `nina_astrophotography.focuser_auto_focus` | Run autofocus | — |
| `nina_astrophotography.filterwheel_change_filter` | Change filter | `filter_index` |
| `nina_astrophotography.guider_start` | Start guiding | `force_calibration` |
| `nina_astrophotography.guider_stop` | Stop guiding | — |
| `nina_astrophotography.dome_open` | Open dome | — |
| `nina_astrophotography.dome_close` | Close dome | — |
| `nina_astrophotography.dome_park` | Park dome | — |
| `nina_astrophotography.sequence_start` | Start sequence | — |
| `nina_astrophotography.sequence_stop` | Stop sequence | — |
| `nina_astrophotography.sequence_load` | Load sequence file | `path` |

---

## Example Dashboard (Lovelace YAML)

Add this to a dashboard view to get a full astrophotography control panel:

```yaml
title: Observatory
views:
  - title: N.I.N.A.
    cards:
      # ── Equipment Status ──────────────────────────────────────────────────
      - type: entities
        title: Equipment Status
        entities:
          - entity: binary_sensor.mount_connected
          - entity: binary_sensor.camera_connected
          - entity: binary_sensor.focuser_connected
          - entity: binary_sensor.filterwheel_connected
          - entity: binary_sensor.guider_connected
          - entity: binary_sensor.dome_connected

      # ── Session Overview ──────────────────────────────────────────────────
      - type: glance
        title: Session Overview
        entities:
          - entity: binary_sensor.sequence_running
            name: Sequence
          - entity: sensor.sequence_target
            name: Target
          - entity: sensor.sequence_progress
            name: Progress
          - entity: sensor.image_count
            name: Frames
          - entity: binary_sensor.mount_tracking
            name: Tracking
          - entity: binary_sensor.guider_active
            name: Guiding

      # ── Camera ────────────────────────────────────────────────────────────
      - type: entities
        title: Camera
        entities:
          - entity: sensor.camera_temperature
          - entity: sensor.camera_target_temperature
          - entity: sensor.camera_cooler_power
          - entity: binary_sensor.camera_cooling
          - entity: sensor.camera_gain
          - entity: sensor.camera_current_filter
          - entity: sensor.camera_status

      # ── Mount Pointing ────────────────────────────────────────────────────
      - type: entities
        title: Mount Pointing
        entities:
          - entity: sensor.mount_ra
          - entity: sensor.mount_dec
          - entity: sensor.mount_altitude
          - entity: sensor.mount_azimuth
          - entity: sensor.mount_time_to_meridian_flip
          - entity: binary_sensor.mount_parked
          - entity: binary_sensor.mount_slewing

      # ── Focuser ───────────────────────────────────────────────────────────
      - type: entities
        title: Focuser
        entities:
          - entity: sensor.focuser_position
          - entity: sensor.focuser_temperature
          - entity: binary_sensor.focuser_moving

      # ── Guiding ───────────────────────────────────────────────────────────
      - type: entities
        title: Guiding (PHD2)
        entities:
          - entity: sensor.guider_rms_total
          - entity: sensor.guider_rms_ra
          - entity: sensor.guider_rms_dec
          - entity: sensor.guider_status

      # ── Last Image Stats ──────────────────────────────────────────────────
      - type: entities
        title: Last Image
        entities:
          - entity: sensor.image_last_hfr
          - entity: sensor.image_last_star_count
          - entity: sensor.image_last_mean_adu

      # ── Controls ──────────────────────────────────────────────────────────
      - type: button
        name: Start Sequence
        tap_action:
          action: call-service
          service: nina_astrophotography.sequence_start
      - type: button
        name: Stop Sequence
        tap_action:
          action: call-service
          service: nina_astrophotography.sequence_stop
      - type: button
        name: Park Mount
        tap_action:
          action: call-service
          service: nina_astrophotography.mount_park
      - type: button
        name: Auto Focus
        tap_action:
          action: call-service
          service: nina_astrophotography.focuser_auto_focus
```

---

## Example Automations

### Auto-cool camera at sunset

```yaml
automation:
  - alias: "Cool camera at sunset"
    trigger:
      - platform: sun
        event: sunset
        offset: "-00:30:00"
    action:
      - service: nina_astrophotography.camera_cool
        data:
          temperature: -10
          minutes: 15
```

### Alert if guiding RMS exceeds threshold

```yaml
automation:
  - alias: "Guiding alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.guider_rms_total
        above: 2.5
        for: "00:03:00"
    action:
      - service: notify.mobile_app
        data:
          message: "⚠️ Guide RMS is {{ states('sensor.guider_rms_total') }} arcsec!"
```

### Auto-park before dawn

```yaml
automation:
  - alias: "Park before dawn"
    trigger:
      - platform: sun
        event: sunrise
        offset: "-00:45:00"
    condition:
      - condition: state
        entity_id: binary_sensor.sequence_running
        state: "off"
    action:
      - service: nina_astrophotography.sequence_stop
      - delay: "00:01:00"
      - service: nina_astrophotography.mount_park
      - service: nina_astrophotography.camera_warm
        data:
          minutes: 20
      - service: nina_astrophotography.dome_close
```

---


---

## Additional Entities (v1.1)

### Switch Entities
| Entity | Description |
|---|---|
| `switch.camera_cooler` | Toggle camera TEC cooler on/off (cool to −10 °C / warm over 15 min) |
| `switch.mount_tracking` | Enable/disable sidereal tracking |
| `switch.autoguiding` | Start/stop PHD2 guiding |
| `switch.flat_panel_light` | Toggle flat panel light |

### Select Entities
| Entity | Description |
|---|---|
| `select.active_filter` | Choose filter by name (maps to slot index automatically) |
| `select.mount_tracking_rate` | Sidereal / Lunar / Solar / King |

### Number Entities (controllable)
| Entity | Description | Range |
|---|---|---|
| `number.camera_gain_control` | Set camera gain | 0–5000 |
| `number.camera_offset_control` | Set camera offset | 0–5000 |
| `number.camera_binning_control` | Set binning factor | 1–4 |
| `number.camera_cooling_setpoint` | Set cooling target temperature | −30–20 °C |
| `number.focuser_target_position` | Move focuser to absolute position | 0–200,000 steps |
| `number.filter_wheel_slot` | Change filter by slot index | 0–20 |
| `number.rotator_position` | Rotate to absolute position | 0–360 ° |

### Light Entity
| Entity | Description |
|---|---|
| `light.flat_panel_light` | Flat panel with full HA brightness control (0–255) |

### Button Entities
One-tap action buttons — ideal for dashboard card rows:
`button.run_auto_focus` · `button.mount_find_home` ·
`button.park_mount` · `button.unpark_mount` · `button.start_sequence` ·
`button.stop_sequence` · `button.open_dome` · `button.close_dome` ·
`button.park_dome` · `button.abort_capture` · `button.start_guiding` ·
`button.stop_guiding`

---

## WebSocket Push Events

The integration maintains a persistent WebSocket connection to N.I.N.A. alongside
the REST polling. **Every N.I.N.A. event fires a native HA event** so automations
can react instantly — no polling delay.

### Event naming convention
N.I.N.A. event `IMAGE-SAVE` → HA event `nina_image_save`  
N.I.N.A. event `MOUNT-AFTER-FLIP` → HA event `nina_mount_after_flip`  
All events also fire as `nina_event`. Event data is `event` (the N.I.N.A. name),
`time` (ISO 8601, offset-aware), `data` (the event's own scalar fields) and
`frame` (the mapped statistics on `IMAGE-SAVE`, otherwise `null`).

### Using WebSocket events in automations

```yaml
automation:
  - alias: "React to image saved"
    trigger:
      - platform: event
        event_type: nina_image_save
    action:
      - service: notify.mobile_app_myphone
        data:
          message: >
            Frame saved: HFR {{ trigger.event.data.frame.hfr | round(2) }}
            Stars: {{ trigger.event.data.frame.stars }}

  - alias: "Alert when autofocus fails"
    trigger:
      - platform: event
        event_type: nina_error_af
    action:
      - service: notify.mobile_app_myphone
        data:
          message: "⚠️ N.I.N.A. autofocus failed!"

  - alias: "React to meridian flip complete"
    trigger:
      - platform: event
        event_type: nina_mount_after_flip
    action:
      - service: notify.mobile_app_myphone
        data:
          message: "✅ Meridian flip complete — imaging resuming"
```

### Full list of HA event types
| HA Event | N.I.N.A. Trigger |
|---|---|
| `nina_image_save` | Frame written to disk (carries full ImageStatistics) |
| `nina_sequence_starting` / `nina_sequence_finished` | Sequence begins / ends |
| `nina_autofocus_starting` / `nina_autofocus_finished` | AF run starts / completes |
| `nina_error_af` | Autofocus failure |
| `nina_mount_before_flip` / `nina_mount_after_flip` | Meridian flip events |
| `nina_mount_parked` / `nina_mount_unparked` | Park state changes |
| `nina_camera_connected` / `nina_camera_disconnected` | Camera connection |
| `nina_guider_start` / `nina_guider_stop` | Guiding starts/stops |
| `nina_guider_dither` | Dither complete |
| `nina_dome_shutter_opened` / `nina_dome_shutter_closed` | Dome shutter |
| `nina_safety_changed` | Safety monitor state (data: `{IsSafe: bool}`) |
| `nina_filterwheel_changed` | Filter changed (data: `{Previous: …, New: …}`) |
| `nina_websocket_connected` / `nina_websocket_disconnected` | WS connection health |

---

## Automation Blueprints

Copy the `blueprints/` folder to your HA config directory to install all four blueprints.
Then use **Settings → Automations → Import Blueprint** or just reference them directly.

| Blueprint | Description |
|---|---|
| `session_startup.yaml` | Full startup: unpark → cool camera → open dome → load & start sequence |
| `session_shutdown.yaml` | Safe shutdown: stop sequence → park → warm camera → close dome |
| `guiding_alert.yaml` | Notify (and optionally re-focus) when RMS exceeds threshold |
| `meridian_flip_warning.yaml` | Warn before flip, confirm after flip completes |

---

## Custom Lovelace Card(s)

Copy the following to your HA `/config/www/` folder, then register them:
 
`www/nina-observatory-card.js`
`www/nina-frame-stats-card.js`
`www/nina-image-panel-card.js`
`www/nina-sky-map-card.js`
`www/nina-weather-card.js`

```yaml
# configuration.yaml  (or via UI: Settings → Dashboards → Resources)
lovelace:
  resources:
    - url: /local/nina-observatory-card.js
      type: module
```

Add to any dashboard:

```yaml
type: custom:nina-observatory-card
type: custom:nina-frame-stats-card
type: custom:nina-image-panel-card
type: custom:nina-sky-map-card
type: custom:nina-weather-card
```

The Observatory Card provides:
- Live session banner with target name and progress bar
- Equipment connectivity chips (Camera, Mount, Focuser, Filter Wheel, Guider, Dome)
- Meridian flip countdown warning
- Camera temperature, gain, cooler power, current filter
- Mount RA/Dec/Alt/Az and time to flip
- Focuser position and temperature
- PHD2 guiding RMS bar chart (RA + Dec, colour-coded by severity)
- Last image HFR, star count and mean ADU
- One-tap control buttons: Start/Stop Sequence, Park/Unpark, Auto Focus,
  Open/Close Dome, Cool/Warm Camera, Start/Stop Guiding

The Frame Stats Card provides:
- live per-frame HFR trend, star count, ADU sparklines
- per-filter frame counts
- all driven by IMAGE-SAVE WebSocket events
 
The Image Panel Card provides:
- Latest image display
- previous 5 image history
- RMS, HFR, ADU, Exposure and Star count stats
 
The Sky Map Card provides:
- A live star chart
- Reticle indicating current pointing direction (trails indicate recent movements)
- Current Target coordinates (RA/Dec and Alt/Az)
- mount tracking status
 
The Weather Card provides:
- Safety Monitor
- Atmospheric Conditions - Temperature, Humiidity, DewPoint, Air Pressue
- Ground level wind conditions
- Sky/Viewing Conditions - Cloud cover, Rain Rate, Sky Temp, and Seeing Quality
- Tied to weather monitor in N.I.N.A.
 


## Troubleshooting

| Problem | Fix |
|---|---|
| "Cannot connect" in config flow | Verify the Advanced API plugin is running. Open `http://<IP>:1888/v2/api/version` in a browser from the HA machine. |
| Sensors showing `unknown` | The specific device (camera, mount, etc.) may not be connected in N.I.N.A. Connect it there first. |
| Poll is slow | Increase the poll interval in Options if you have many devices. |
| Service calls fail | Check HA logs (`Settings → System → Logs`) for the underlying API error from N.I.N.A. |

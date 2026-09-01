> [!NOTE]
> **AI-Assisted Development**
>  
> [![AI Assisted](https://img.shields.io/badge/built%20with-Claude%20AI-7b8de8?style=flat-square&logo=anthropic)](https://claude.ai) All code has been reviewed, tested against a live N.I.N.A. instance, and is maintained by a human author. AI assistance was used to accelerate development — the design decisions, testing, and ongoing maintenance are my own.

# N.I.N.A. Astrophotography – Home Assistant Integration

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
4. Enter the IP/hostname of your imaging PC and the API port (default `1888`).

---

## Upgrading from 1.4.x

Release 2.0.0 realigns the integration with the Advanced API v2 spec and
restructures how equipment is modelled in Home Assistant. **Every entity id
changes.** Read this section before upgrading.

### Every entity id is renamed

Equipment now gets one Home Assistant device each, and entities are named
relative to their device (`has_entity_name`), which is what lets multiple 
N.I.N.A. instances coexist. Entity ids follow:

```
<domain>.<instance>_<device>_<entity>
```

*instance* is the name you give the integration during setup, defaulting to
`NINA`. So on a default single-instance install:

| Was | Now |
|---|---|
| `sensor.camera_temperature` | `sensor.nina_camera_temperature` |
| `sensor.guider_rms_total` | `sensor.nina_guider_rms_total` |
| `sensor.dew_point` | `sensor.nina_weather_station_dew_point` |
| `binary_sensor.observatory_safe` | `binary_sensor.nina_safety_monitor_safe` |
| `sensor.time_to_meridian_flip` | `sensor.nina_mount_time_to_meridian_flip` |

Most ids simply gain the `nina_` prefix. The exceptions are entities whose old
name did not begin with its device — weather readings, the selected filter, and
the two above — which now sit under their device's name.

**Migrating:** Home Assistant keys entities by `unique_id`, which has not
changed, so your entities keep their history and settings; only the ids move.
Either accept the new ids and update your automations and dashboards, or rename
each entity back from **Settings → Devices & Services → Entities**. The bundled
cards and blueprints have already been updated.

### Multiple N.I.N.A. instances

Setup now asks for an instance name. Give each rig a distinct one — `FRA500`,
`RC8` — and their devices, entity ids and service targets stay separate even
when both rigs use the same model camera, focuser, etc.

Two things follow from this:

- The bundled Lovelace cards take a matching `prefix:` option:
  ```yaml
  type: custom:nina-observatory-card
  prefix: fra500        # defaults to "nina"
  ```
- **Services now take a target device.** With one instance the target is
  optional. With several it is required — previously a service call silently
  went to whichever instance loaded first, which could park the wrong mount.

### One device per piece of equipment

A `NINA` service device with a child device per equipment type, each carrying
the model, driver version and device id from its driver. Driver metadata that
was briefly published as entity attributes now lives here, which is where Home
Assistant expects it:

```jinja
{{ device_attr('sensor.nina_camera_temperature', 'model') }}   → ZWO ASI2600MM Pro
```

### Removed entities

| Removed | Replacement |
|---|---|
| The eleven `*_name` sensors | The device registry — use `device_attr()`. |
| `sensor.last_image_type` | Always `LIGHT` now; use `sensor.nina_last_frame_filter` for calibration runs. |
| `number.camera_gain`, `number.camera_offset` | The API exposes these read-only; the sensors remain. Set per-exposure via `camera_capture`. |
| `number.filter_wheel_slot` | `select.nina_filter_wheel_active_filter` |
| `number.camera_binning` | `select.nina_camera_binning_mode` |
| `guider_dither` service | No such endpoint exists; dithering is configured in the sequence. |
| Capability and driver attributes | Capabilities gate whether a control exists; driver data moved to the device registry. |

### Changed behaviour

| Entity | Change |
|---|---|
| `sensor.nina_last_image_*` | Describe the last **light** frame. N.I.N.A. does not star-detect calibration frames, so a dawn flat run used to pin HFR to `0` and stars to `-1` for the rest of the day. |
| `sensor.nina_sequence_progress` | Excludes conditional branches never taken, which stay `CREATED` forever and prevented it reaching 100%. |
| `sensor.nina_sequence_target` | Read from the last light frame, so it works under Target Scheduler and Sequencer+. |
| `sensor.nina_mount_time_to_meridian_flip` | Unit corrected from minutes to hours. |
| `sensor.nina_mount_utc_date` | Parsed as UTC; the API omits the offset despite the name. |
| `sensor.nina_livestack_status` | Casing normalised — the spec says lowercase, the server sends `Stopped`. |

### Breaking service changes

| Service | Was | Now |
|---|---|---|
| all services | untargeted | optional `target` device; **required** with multiple instances |
| `mount_slew` | `ra` in decimal **hours** | `ra` in decimal **degrees** (hours × 15) |
| `filterwheel_change_filter` | `filter_index` (list position) | `filter_id` (the wheel's own Id) |
| `sequence_load` | `path` (full Windows path) | `sequence_name` |
| `mount_set_tracking` | `enabled` boolean | `mode`: Sidereal / Lunar / Solar / King / Stopped |
| `camera_capture` | `exposure`, `filter_index`, `binning` | `duration`; set filter and binning beforehand |

### New: image scale and HFR in arcseconds

N.I.N.A. reports HFR in pixels, which is not comparable across a binning change,
a focal reducer or a new camera. Focal length is read from the active profile on
every poll, so swapping a reducer — or switching to a profile that has one —
updates everything derived from it:

- `sensor.nina_image_scale` — arcsec/px at the current focal length and binning
- `sensor.nina_last_image_hfr_arcsec` — rig-independent HFR
- `sensor.nina_telescope_focal_length`, `select.nina_active_profile`

```yaml
- alias: HFR degraded
  trigger:
    - platform: numeric_state
      entity_id: sensor.nina_last_image_hfr_arcsec
      above: 4
```

### New: diagnostics that are off by default

Ten sensors are created but disabled, following Home Assistant's
`entity-disabled-by-default` guidance. Enable any on its device page
(**Settings → Devices & Services → Devices →** device → entity → gear →
**Enabled**).

| Entity | Why you might want it |
|---|---|
| `sensor.nina_mount_guide_rate_ra` / `_dec` | PHD2's calibration is computed against the guide rate. If a driver reconnect resets it and PHD2 restores a stale calibration, guiding degrades silently all night. |
| `sensor.nina_camera_bit_depth` | ASI High Speed Mode and some QHY output modes silently drop to 8-bit, unrecoverable in the resulting lights. Alert on `!= 16`. |
| `sensor.nina_camera_sensor_type` | Per ASCOM `ICameraV3` this is only meaningful at bin 1×1, so a colour sensor can report `Monochrome` once binned, breaking debayering. |
| `sensor.nina_mount_utc_date` | Mounts with their own RTC or GPS drift; 30s of error is 7.5 arcmin of pointing error. Many drivers just proxy the PC clock, making the check tautological — hence off by default. |
| `sensor.nina_mount_equatorial_system` | A JNOW/J2000 mismatch is the usual cause of plate solves landing 15–20 arcmin off. |
| `sensor.nina_guider_pixel_scale` | Changes silently when PHD2 binning changes, making arcsec RMS history non-comparable. |
| `sensor.nina_camera_pixel_size`, `..._readout_mode_for_lights`, `sensor.nina_rotator_step_size` | Reference values, readable without remoting into the observatory PC. |

---

## Entities Created

Each piece of equipment is its own device under a service device representing
N.I.N.A. itself. Entity ids follow **`<domain>.<instance>_<device>_<entity>`**,
where *instance* is the name you gave the integration (default `NINA`). The ids
below assume that default — with an instance named `FRA500` you would have
`sensor.fra500_camera_temperature` instead.

The headings below are the bare equipment roles. In Home Assistant the devices
themselves are prefixed with the instance name, so you will see `NINA Camera`
(or `FRA500 Camera`) on the devices page.

Legend: **ᴰ** diagnostic · **○** disabled by default · **⚡** push-updated via WebSocket.


### Service Device

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_flat_wizard_running` | Flat Wizard Running | on/off |
| `binary_sensor.nina_livestack_running` | Livestack Running | on/off |
| `binary_sensor.nina_sequence_running` | Sequence Running | on/off |
| `button.nina_reset_sequence` | Reset Sequence (action) | — |
| `button.nina_skip_sequence_item` | Skip Sequence Item (action) | — |
| `button.nina_start_sequence` | Start Sequence (action) | — |
| `button.nina_stop_flat_wizard` | Stop Flat Wizard (action) | — |
| `button.nina_stop_sequence` | Stop Sequence (action) | — |
| `image.nina_latest_captured_frame` | Latest Captured Frame | — |
| `image.nina_screenshot` | N.I.N.A. window screenshot ᴰ○ | — |
| `select.nina_active_profile` | Active Profile (settable) | — |
| `select.nina_active_tab` | Active Tab (settable) ᴰ | — |
| `sensor.nina_active_profile` | Active Profile | — |
| `sensor.nina_flat_wizard_progress` | Flat Wizard Progress | % |
| `sensor.nina_flat_wizard_state` | Flat Wizard State | — |
| `sensor.nina_frame_sparkline_data` | Frame Sparkline Data ⚡ ᴰ | — |
| `sensor.nina_frames_per_filter` | Frames Per Filter ⚡ | — |
| `sensor.nina_hfr_trend` | HFR Trend ⚡ | — |
| `sensor.nina_hfr_trend_delta` | HFR Trend Delta ⚡ ᴰ | px |
| `sensor.nina_image_scale` | Image Scale | arcsec/px |
| `sensor.nina_last_frame_adu_std_dev` | Last Frame ADU Std Dev ⚡ ᴰ | — |
| `sensor.nina_last_frame_exposure` | Last Frame Exposure ⚡ | s |
| `sensor.nina_last_frame_filter` | Last Frame Filter ⚡ | — |
| `sensor.nina_last_frame_guide_rms` | Last Frame Guide RMS ⚡ | — |
| `sensor.nina_last_frame_hfr` | Last Frame HFR ⚡ | px |
| `sensor.nina_last_frame_hfr_std_dev` | Last Frame HFR Std Dev ⚡ ᴰ | px |
| `sensor.nina_last_frame_max_adu` | Last Frame Max ADU ⚡ ᴰ | — |
| `sensor.nina_last_frame_mean_adu` | Last Frame Mean ADU ⚡ | — |
| `sensor.nina_last_frame_median_adu` | Last Frame Median ADU ⚡ ᴰ | — |
| `sensor.nina_last_frame_min_adu` | Last Frame Min ADU ⚡ ᴰ | — |
| `sensor.nina_last_frame_stars` | Last Frame Stars ⚡ | — |
| `sensor.nina_last_frame_target` | Last Frame Target ⚡ | — |
| `sensor.nina_last_image_exposure_time` | Last Image Exposure Time | s |
| `sensor.nina_last_image_filter` | Last Image Filter | — |
| `sensor.nina_last_image_hfr` | Last Image HFR | px |
| `sensor.nina_last_image_hfr_arcsec` | Last Image HFR (arcsec) | arcsec |
| `sensor.nina_last_image_mean_adu` | Last Image Mean ADU | — |
| `sensor.nina_last_image_median_adu` | Last Image Median ADU ᴰ | — |
| `sensor.nina_last_image_star_count` | Last Image Star Count | — |
| `sensor.nina_livestack_status` | Livestack Status | — |
| `sensor.nina_rolling_avg_adu_10` | Rolling Avg ADU (10) ⚡ | — |
| `sensor.nina_rolling_avg_hfr_10` | Rolling Avg HFR (10) ⚡ | px |
| `sensor.nina_rolling_avg_stars_10` | Rolling Avg Stars (10) ⚡ | — |
| `sensor.nina_sequence_current_instruction` | Sequence Current Instruction | — |
| `sensor.nina_sequence_progress` | Sequence Progress | % |
| `sensor.nina_sequence_status` | Sequence Status | — |
| `sensor.nina_sequence_target` | Sequence Target | — |
| `sensor.nina_session_avg_hfr` | Session Avg HFR ⚡ | px |
| `sensor.nina_session_avg_stars` | Session Avg Stars ⚡ | — |
| `sensor.nina_session_best_hfr` | Session Best HFR ⚡ | px |
| `sensor.nina_session_frame_count` | Session Frame Count ⚡ | — |
| `sensor.nina_session_image_count` | Session Image Count | — |
| `sensor.nina_session_integration_time` | Session Integration Time ⚡ | min |
| `sensor.nina_session_worst_hfr` | Session Worst HFR ⚡ ᴰ | px |
| `sensor.nina_start_time` | Start Time ᴰ | — |
| `sensor.nina_telescope_focal_length` | Telescope Focal Length ᴰ | mm |
| `sensor.nina_version` | Version ᴰ | — |
| `switch.nina_livestack` | Livestack (settable) | on/off |

### Camera

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_camera_at_target_temperature` | At Target Temperature | on/off |
| `binary_sensor.nina_camera_connected` | Connected | on/off |
| `binary_sensor.nina_camera_cooling` | Cooling | on/off |
| `binary_sensor.nina_camera_dew_heater` | Dew Heater | on/off |
| `binary_sensor.nina_camera_exposing` | Exposing | on/off |
| `binary_sensor.nina_camera_live_view` | Live View ᴰ | on/off |
| `binary_sensor.nina_camera_sub_sample_enabled` | Sub-sample Enabled ᴰ | on/off |
| `button.nina_camera_abort_capture` | Abort Capture (action) | — |
| `button.nina_camera_cancel_cooling` | Cancel Cooling (action) | — |
| `button.nina_camera_cancel_warming` | Cancel Warming (action) | — |
| `number.nina_camera_cooling_setpoint` | Cooling Setpoint (settable) | °C |
| `number.nina_camera_usb_limit` | USB Limit (settable) | — |
| `select.nina_camera_binning_mode` | Binning Mode (settable) | — |
| `sensor.nina_camera_battery` | Battery ᴰ | % |
| `sensor.nina_camera_binning` | Binning ᴰ | — |
| `sensor.nina_camera_bit_depth` | Bit Depth ᴰ○ | bit |
| `sensor.nina_camera_cooler_power` | Cooler Power | % |
| `sensor.nina_camera_exposure_end_time` | Exposure End Time | — |
| `sensor.nina_camera_gain` | Gain | — |
| `sensor.nina_camera_last_download_time` | Last Download Time ᴰ | s |
| `sensor.nina_camera_offset` | Offset | — |
| `sensor.nina_camera_pixel_size` | Pixel Size ᴰ○ | μm |
| `sensor.nina_camera_readout_mode` | Readout Mode ᴰ | — |
| `sensor.nina_camera_readout_mode_for_lights` | Readout Mode for Lights ᴰ○ | — |
| `sensor.nina_camera_sensor_type` | Sensor Type ᴰ○ | — |
| `sensor.nina_camera_status` | Status | — |
| `sensor.nina_camera_target_temperature` | Target Temperature ᴰ | °C |
| `sensor.nina_camera_temperature` | Temperature | °C |
| `sensor.nina_camera_usb_limit` | USB Limit ᴰ | — |
| `switch.nina_camera_cooler` | Cooler (settable) | on/off |
| `switch.nina_camera_dew_heater` | Dew Heater (settable) | on/off |

### Mount

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_mount_at_home` | At Home | on/off |
| `binary_sensor.nina_mount_connected` | Connected | on/off |
| `binary_sensor.nina_mount_parked` | Parked | on/off |
| `binary_sensor.nina_mount_pulse_guiding` | Pulse Guiding ᴰ | on/off |
| `binary_sensor.nina_mount_slewing` | Slewing | on/off |
| `binary_sensor.nina_mount_tracking` | Tracking | on/off |
| `button.nina_mount_find_home` | Find Home (action) | — |
| `button.nina_mount_meridian_flip` | Meridian Flip (action) | — |
| `button.nina_mount_park_mount` | Park Mount (action) | — |
| `button.nina_mount_set_mount_park_position` | Set Mount Park Position (action) | — |
| `button.nina_mount_stop_slew` | Stop Slew (action) | — |
| `button.nina_mount_unpark_mount` | Unpark Mount (action) | — |
| `select.nina_mount_tracking_mode` | Tracking Mode (settable) | — |
| `sensor.nina_mount_altitude` | Altitude | ° |
| `sensor.nina_mount_azimuth` | Azimuth | ° |
| `sensor.nina_mount_dec` | Dec | ° |
| `sensor.nina_mount_equatorial_system` | Equatorial System ᴰ○ | — |
| `sensor.nina_mount_guide_rate_dec` | Guide Rate Dec ᴰ○ | arcsec/s |
| `sensor.nina_mount_guide_rate_ra` | Guide Rate RA ᴰ○ | arcsec/s |
| `sensor.nina_mount_ra` | RA | h |
| `sensor.nina_mount_side_of_pier` | Side of Pier | — |
| `sensor.nina_mount_sidereal_time` | Sidereal Time ᴰ | h |
| `sensor.nina_mount_site_elevation` | Site Elevation ᴰ | m |
| `sensor.nina_mount_site_latitude` | Site Latitude ᴰ | ° |
| `sensor.nina_mount_site_longitude` | Site Longitude ᴰ | ° |
| `sensor.nina_mount_time_to_meridian_flip` | Time to Meridian Flip | h |
| `sensor.nina_mount_tracking_mode` | Tracking Mode | — |
| `sensor.nina_mount_utc_date` | UTC Date ᴰ○ | — |
| `switch.nina_mount_tracking` | Tracking (settable) | on/off |

### Focuser

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_focuser_connected` | Connected | on/off |
| `binary_sensor.nina_focuser_moving` | Moving | on/off |
| `binary_sensor.nina_focuser_settling` | Settling ᴰ | on/off |
| `binary_sensor.nina_focuser_temperature_compensation` | Temperature Compensation | on/off |
| `button.nina_focuser_cancel_auto_focus` | Cancel Auto Focus (action) | — |
| `button.nina_focuser_run_auto_focus` | Run Auto Focus (action) | — |
| `button.nina_focuser_stop_focuser` | Stop Focuser (action) | — |
| `number.nina_focuser_target_position` | Target Position (settable) | — |
| `sensor.nina_focuser_last_autofocus_filter` | Last Autofocus Filter ᴰ | — |
| `sensor.nina_focuser_last_autofocus_hfr` | Last Autofocus HFR | px |
| `sensor.nina_focuser_last_autofocus_position` | Last Autofocus Position | steps |
| `sensor.nina_focuser_last_autofocus_temperature` | Last Autofocus Temperature ᴰ | °C |
| `sensor.nina_focuser_last_autofocus_time` | Last Autofocus Time | — |
| `sensor.nina_focuser_position` | Position | steps |
| `sensor.nina_focuser_step_size` | Step Size ᴰ | μm |
| `sensor.nina_focuser_temperature` | Temperature | °C |

### Filter Wheel

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_filter_wheel_connected` | Connected | on/off |
| `binary_sensor.nina_filter_wheel_moving` | Moving | on/off |
| `select.nina_filter_wheel_active_filter` | Active Filter (settable) | — |
| `sensor.nina_filter_wheel_current_filter` | Current Filter | — |

### Guider

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_guider_active` | Active | on/off |
| `binary_sensor.nina_guider_calibrating` | Calibrating | on/off |
| `binary_sensor.nina_guider_connected` | Connected | on/off |
| `binary_sensor.nina_guider_lost_lock` | Lost Lock | on/off |
| `button.nina_guider_clear_guider_calibration` | Clear Guider Calibration (action) | — |
| `button.nina_guider_start_guiding` | Start Guiding (action) | — |
| `button.nina_guider_start_guiding_with_calibration` | Start Guiding with Calibration (action) | — |
| `button.nina_guider_stop_guiding` | Stop Guiding (action) | — |
| `sensor.nina_guider_peak_dec` | Peak Dec ᴰ | arcsec |
| `sensor.nina_guider_peak_ra` | Peak RA ᴰ | arcsec |
| `sensor.nina_guider_pixel_scale` | Pixel Scale ᴰ○ | arcsec/px |
| `sensor.nina_guider_rms_dec` | RMS Dec | arcsec |
| `sensor.nina_guider_rms_ra` | RMS RA | arcsec |
| `sensor.nina_guider_rms_total` | RMS Total | arcsec |
| `sensor.nina_guider_status` | Status | — |
| `switch.nina_guider_autoguiding` | Autoguiding (settable) | on/off |

### Rotator

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_rotator_connected` | Connected | on/off |
| `binary_sensor.nina_rotator_moving` | Moving | on/off |
| `binary_sensor.nina_rotator_reversed` | Reversed ᴰ | on/off |
| `binary_sensor.nina_rotator_synced` | Synced ᴰ | on/off |
| `button.nina_rotator_stop_rotator` | Stop Rotator (action) | — |
| `number.nina_rotator_mechanical_position` | Mechanical Position (settable) | ° |
| `number.nina_rotator_position` | Position (settable) | ° |
| `sensor.nina_rotator_mechanical_position` | Mechanical Position ᴰ | ° |
| `sensor.nina_rotator_position` | Position | ° |
| `sensor.nina_rotator_step_size` | Step Size ᴰ○ | ° |
| `switch.nina_rotator_reverse_direction` | Reverse Direction (settable) | on/off |

### Dome

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_dome_at_home` | At Home | on/off |
| `binary_sensor.nina_dome_connected` | Connected | on/off |
| `binary_sensor.nina_dome_following_mount` | Following Mount | on/off |
| `binary_sensor.nina_dome_parked` | Parked | on/off |
| `binary_sensor.nina_dome_shutter_open` | Shutter Open | on/off |
| `binary_sensor.nina_dome_slewing` | Slewing | on/off |
| `binary_sensor.nina_dome_synchronized` | Synchronized ᴰ | on/off |
| `button.nina_dome_close_dome` | Close Dome (action) | — |
| `button.nina_dome_home_dome` | Home Dome (action) | — |
| `button.nina_dome_open_dome` | Open Dome (action) | — |
| `button.nina_dome_park_dome` | Park Dome (action) | — |
| `button.nina_dome_stop_dome` | Stop Dome (action) | — |
| `button.nina_dome_sync_dome_to_mount` | Sync Dome to Mount (action) | — |
| `number.nina_dome_target_azimuth` | Target Azimuth (settable) | ° |
| `sensor.nina_dome_azimuth` | Azimuth | ° |
| `sensor.nina_dome_shutter_status` | Shutter Status | — |
| `switch.nina_dome_follow_mount` | Follow Mount (settable) | on/off |

### Flat Panel

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_flat_panel_connected` | Connected | on/off |
| `binary_sensor.nina_flat_panel_cover_open` | Cover Open | on/off |
| `binary_sensor.nina_flat_panel_light_on` | Light On | on/off |
| `light.nina_flat_panel_light` | Flat panel light (settable, dimmable) | — |
| `sensor.nina_flat_panel_brightness` | Brightness | — |
| `sensor.nina_flat_panel_cover_state` | Cover State | — |
| `switch.nina_flat_panel_cover_open` | Cover Open (settable) | on/off |
| `switch.nina_flat_panel_light` | Light (settable) | on/off |

### Switch Device

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_switch_device_connected` | Connected | on/off |

### Weather Station

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_weather_station_connected` | Connected | on/off |
| `sensor.nina_weather_station_atmospheric_seeing` | Atmospheric Seeing | arcsec |
| `sensor.nina_weather_station_average_period` | Average Period ᴰ | h |
| `sensor.nina_weather_station_barometric_pressure` | Barometric Pressure | hPa |
| `sensor.nina_weather_station_cloud_cover` | Cloud Cover | % |
| `sensor.nina_weather_station_dew_point` | Dew Point | °C |
| `sensor.nina_weather_station_humidity` | Humidity | % |
| `sensor.nina_weather_station_rain_rate` | Rain Rate | mm/h |
| `sensor.nina_weather_station_sky_brightness` | Sky Brightness | lx |
| `sensor.nina_weather_station_sky_quality` | Sky Quality | mag/arcsec² |
| `sensor.nina_weather_station_sky_temperature` | Sky Temperature | °C |
| `sensor.nina_weather_station_temperature` | Temperature | °C |
| `sensor.nina_weather_station_wind_direction` | Wind Direction | ° |
| `sensor.nina_weather_station_wind_gust` | Wind Gust | m/s |
| `sensor.nina_weather_station_wind_speed` | Wind Speed | m/s |

### Safety Monitor

| Entity | Description | Unit |
|---|---|---|
| `binary_sensor.nina_safety_monitor_connected` | Connected | on/off |
| `binary_sensor.nina_safety_monitor_safe` | Safe | on/off |

> The switch device additionally creates one `sensor` per read-only channel
> and one `number` per writable channel, discovered from the hardware.


---

## Services

All services accept a **target device**. With one N.I.N.A. instance the target
is optional; with several it is required — the integration refuses to guess.

| Service | Description | Key Parameters |
|---|---|---|
| `nina_astrophotography.application_switch_tab` | Switch the active tab in the N.I.N.A. user interface. | `tab` |
| `nina_astrophotography.camera_abort_capture` | Abort the current camera exposure immediately. | — |
| `nina_astrophotography.camera_capture` | Take a single camera exposure. Binning and filter are not parameters of this endpoint — set them first with Set Binning and Change Filter. | `duration`, `gain`, `save`, `solve`, `wait_for_result`, `image_type`, `target_name` |
| `nina_astrophotography.camera_cool` | Start cooling the camera sensor to a target temperature. | `temperature`, `minutes`, `cancel` |
| `nina_astrophotography.camera_set_binning` | Set the camera binning mode. Must be a mode the camera reports, e.g. 1x1 or 2x2. | `binning` |
| `nina_astrophotography.camera_set_dew_heater` | Turn the camera's dew heater on or off. | `enabled` |
| `nina_astrophotography.camera_warm` | Gradually warm the camera sensor back to ambient temperature. | `minutes`, `cancel` |
| `nina_astrophotography.dome_close` | Close the dome shutter. | — |
| `nina_astrophotography.dome_open` | Open the dome shutter. | — |
| `nina_astrophotography.dome_park` | Park the dome. | — |
| `nina_astrophotography.dome_set_follow` | Start or stop the dome following the telescope. | `enabled` |
| `nina_astrophotography.dome_slew` | Slew the dome to an azimuth. | `azimuth` |
| `nina_astrophotography.filterwheel_change_filter` | Rotate the filter wheel to the filter with the given Id. | `filter_id` |
| `nina_astrophotography.flats_auto_brightness` | Run the flat wizard at a fixed exposure time, letting N.I.N.A. pick the flat panel brightness that reaches the target histogram mean. | `count`, `exposure_time`, `filter_id`, `binning`, `gain`, `offset`, `histogram_mean`, `mean_tolerance`, `min_brightness`, `max_brightness`, `keep_closed` |
| `nina_astrophotography.flats_auto_exposure` | Run the flat wizard at a fixed panel brightness, letting N.I.N.A. pick the exposure time that reaches the target histogram mean. | `count`, `brightness`, `filter_id`, `binning`, `gain`, `offset`, `histogram_mean`, `mean_tolerance`, `min_exposure`, `max_exposure`, `keep_closed` |
| `nina_astrophotography.flats_skyflat` | Run the flat wizard against the twilight sky. | `count`, `filter_id`, `binning`, `gain`, `offset`, `histogram_mean`, `mean_tolerance`, `min_exposure`, `max_exposure`, `dither` |
| `nina_astrophotography.flats_stop` | Stop the running flat wizard process. | — |
| `nina_astrophotography.flats_trained_flat` | Run the flat wizard using the filter's trained flat settings. | `count`, `filter_id`, `binning`, `gain`, `offset`, `keep_closed` |
| `nina_astrophotography.focuser_auto_focus` | Trigger an autofocus routine using the configured method. | `cancel` |
| `nina_astrophotography.focuser_move` | Move the focuser to an absolute step position. | `position` |
| `nina_astrophotography.guider_clear_calibration` | Discard the autoguider's stored calibration. | — |
| `nina_astrophotography.guider_start` | Start the autoguider. | `calibrate` |
| `nina_astrophotography.guider_stop` | Stop the autoguider. | — |
| `nina_astrophotography.mount_meridian_flip` | Perform a meridian flip if one is needed. This never forces a flip. | — |
| `nina_astrophotography.mount_park` | Send the telescope mount to its park position. | — |
| `nina_astrophotography.mount_set_tracking` | Set the mount's tracking mode. | `mode` |
| `nina_astrophotography.mount_slew` | Slew the telescope mount to the given coordinates. | `ra`, `dec`, `wait_for_result`, `center`, `rotate`, `rotation_angle` |
| `nina_astrophotography.mount_stop_slew` | Stop the mount's current slew. | — |
| `nina_astrophotography.mount_sync` | Sync the mount's reported position to the given coordinates. | `ra`, `dec` |
| `nina_astrophotography.mount_unpark` | Unpark the telescope mount. | — |
| `nina_astrophotography.rotator_move` | Move the rotator to a position in degrees. | `position`, `mechanical` |
| `nina_astrophotography.sequence_load` | Load a sequence by name from N.I.N.A.'s configured sequence folder. Names come from the sequence/list-available endpoint — this is a name, not a path. | `sequence_name` |
| `nina_astrophotography.sequence_reset` | Reset the loaded sequence's progress back to the start. | — |
| `nina_astrophotography.sequence_skip` | Skip ahead in the running sequence. | `type` |
| `nina_astrophotography.sequence_start` | Start the currently loaded imaging sequence. | `skip_validation` |
| `nina_astrophotography.sequence_stop` | Stop the currently running sequence. | — |
| `nina_astrophotography.switch_set_value` | Set a value on the connected switch device. | `index`, `value` |

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
          - entity: binary_sensor.nina_mount_connected
          - entity: binary_sensor.nina_camera_connected
          - entity: binary_sensor.nina_focuser_connected
          - entity: binary_sensor.nina_filter_wheel_connected
          - entity: binary_sensor.nina_guider_connected
          - entity: binary_sensor.nina_dome_connected

      # ── Session Overview ──────────────────────────────────────────────────
      - type: glance
        title: Session Overview
        entities:
          - entity: binary_sensor.nina_sequence_running
            name: Sequence
          - entity: sensor.nina_sequence_target
            name: Target
          - entity: sensor.nina_sequence_progress
            name: Progress
          - entity: sensor.nina_session_image_count
            name: Frames
          - entity: binary_sensor.nina_mount_tracking
            name: Tracking
          - entity: binary_sensor.nina_guider_active
            name: Guiding

      # ── Camera ────────────────────────────────────────────────────────────
      - type: entities
        title: Camera
        entities:
          - entity: sensor.nina_camera_temperature
          - entity: sensor.nina_camera_target_temperature
          - entity: sensor.nina_camera_cooler_power
          - entity: binary_sensor.nina_camera_cooling
          - entity: sensor.nina_camera_gain
          - entity: sensor.nina_filter_wheel_current_filter
          - entity: sensor.nina_camera_status

      # ── Mount Pointing ────────────────────────────────────────────────────
      - type: entities
        title: Mount Pointing
        entities:
          - entity: sensor.nina_mount_ra
          - entity: sensor.nina_mount_dec
          - entity: sensor.nina_mount_altitude
          - entity: sensor.nina_mount_azimuth
          - entity: sensor.nina_mount_time_to_meridian_flip
          - entity: binary_sensor.nina_mount_parked
          - entity: binary_sensor.nina_mount_slewing

      # ── Focuser ───────────────────────────────────────────────────────────
      - type: entities
        title: Focuser
        entities:
          - entity: sensor.nina_focuser_position
          - entity: sensor.nina_focuser_temperature
          - entity: binary_sensor.nina_focuser_moving

      # ── Guiding ───────────────────────────────────────────────────────────
      - type: entities
        title: Guiding (PHD2)
        entities:
          - entity: sensor.nina_guider_rms_total
          - entity: sensor.nina_guider_rms_ra
          - entity: sensor.nina_guider_rms_dec
          - entity: sensor.nina_guider_status

      # ── Last Image Stats ──────────────────────────────────────────────────
      - type: entities
        title: Last Image
        entities:
          - entity: sensor.nina_last_image_hfr
          - entity: sensor.nina_last_image_star_count
          - entity: sensor.nina_last_image_mean_adu

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
        entity_id: sensor.nina_guider_rms_total
        above: 2.5
        for: "00:03:00"
    action:
      - service: notify.mobile_app
        data:
          message: "⚠️ Guide RMS is {{ states('sensor.nina_guider_rms_total') }} arcsec!"
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
        entity_id: binary_sensor.nina_sequence_running
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

## WebSocket Push Events

The integration maintains a persistent WebSocket connection to N.I.N.A. alongside
the REST polling. **Every N.I.N.A. event fires a native HA event** so automations
can react instantly — no polling delay.

### Event naming convention
N.I.N.A. event `IMAGE-SAVE` → HA event `nina_image_save`  
N.I.N.A. event `MOUNT-AFTER-FLIP` → HA event `nina_mount_after_flip`  
All events also fire as `nina_event` with `event` and `response` in event data.

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
            Frame saved: HFR {{ trigger.event.data.response.ImageStatistics.HFR | round(2) }}
            Stars: {{ trigger.event.data.response.ImageStatistics.Stars }}

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

Copy the `blueprints/` folder to your HA config directory to install all five
blueprints, then use **Settings → Automations → Import Blueprint**.

| Blueprint | Description |
|---|---|
| `session_startup.yaml` | Full startup: unpark → cool camera → open dome → load & start sequence |
| `session_shutdown.yaml` | Safe shutdown: stop sequence → park → warm camera → close dome |
| `weather_abort.yaml` | Abort and shut down safely on unsafe conditions, with optional auto-resume |
| `guiding_alert.yaml` | Notify (and optionally re-focus) when RMS exceeds threshold |
| `meridian_flip_warning.yaml` | Warn before flip, confirm after flip completes |

Each blueprint asks you to **pick its entities and a target device** rather than
assuming entity ids. That means they work whatever you named your instance, and
they work when several N.I.N.A. instances are configured — you simply import the
blueprint once per rig and point each automation at that rig's entities.

The entity pickers are filtered to this integration, so they only offer relevant
entities. Each field's description names the entity it expects, for example
`sensor.<instance>_guider_rms_total`.

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

Every card takes an optional `prefix`, which must match the instance name you
gave the integration. It defaults to `nina`, so a single default install needs
no configuration. With a second rig named `FRA500`:

```yaml
type: custom:nina-observatory-card
prefix: fra500
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
  Open/Close Dome, Cool/Warm Camera, Start/Stop Guiding, Dither

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

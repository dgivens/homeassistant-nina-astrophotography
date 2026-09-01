# Changelog

All notable changes to the N.I.N.A. Astrophotography Home Assistant integration are documented here.

---

## [2.0.0] - 2026-09-01

Realigns the integration with the N.I.N.A. Advanced API v2 OpenAPI spec (v2.2.15)
and the AsyncAPI WebSocket spec. Endpoint paths, query parameters and response
field names were audited end-to-end against the published specs; several had
never matched, leaving the affected entities permanently `unknown`.

### Fixed — endpoints that returned 404

| Call | Was | Now |
|---|---|---|
| Abort exposure | `/equipment/camera/abort` | `/equipment/camera/abort-exposure` |
| Mount slew | `/equipment/mount/slew-to-coordinates-j2000` | `/equipment/mount/slew` |
| Mount find home | `/equipment/mount/find-home` | `/equipment/mount/home` |
| Start guiding | `/equipment/guider/start-guiding` | `/equipment/guider/start` |
| Stop guiding | `/equipment/guider/stop-guiding` | `/equipment/guider/stop` |
| Flat panel light | `/equipment/flatdevice/toggle-light` | `/equipment/flatdevice/set-light` |
| Sequence state | `/sequence` | `/sequence/state` |
| Image history | `/image/history` | `/image-history` |
| Latest image | `/image/latest`, `/image?index=` | `/image/{index}` (index -1 = latest) |
| Tracking mode select | `/equipment/telescope/tracking` | `/equipment/mount/tracking` |
| Camera gain / offset setters | `/equipment/camera/set-gain`, `/set-offset` | no such endpoints — entities removed |
| Guider dither | `/equipment/guider/dither` | no such endpoint — service and button removed |

`const.py` still carried a full set of pre-2.x `/equipment/telescope/...` paths
that no longer exist; the endpoint table now mirrors the spec.

### Fixed — wrong query parameters

- `mount/tracking` takes `mode` (0 Sidereal … 4 Stopped), not `on`.
- `guider/start` takes `calibrate`, not `forceCalibration`.
- `camera/capture` takes `duration`; it has no `binning` or `filter_index`.
- `camera/set-binning` takes a mode name such as `2x2`, not `x` and `y`.
- `rotator/reverse` takes `reverseDirection`, not `reverse`.
- `sequence/load` takes `sequenceName` (a name), not `path`.
- `sequence/skip` requires `type` (CurrentItems / ToEnd / ToImaging).
- `image-history` uses `all` / `count` / `index`; `count` is a boolean that
  switches the response to an integer, not a limit.
- `flats/auto-exposure` requires `brightness` (fixed brightness, variable
  exposure). The complementary `flats/auto-brightness` requires `exposureTime`.
- **Mount slew RA is in degrees, not hours.**

### Fixed — wrong response fields

- Image history star count is `Stars`, not `DetectedStars`.
- `DomeInfo.ShutterStatus` is a string enum (`ShutterOpen`, `ShutterClosed`, …);
  it was compared against the integer `0`, so Dome Shutter Open was always off.
- `FWInfo` exposes `AvailableFilters`, not `Filters`; the filter select showed
  no options and changed filters by list position instead of by filter `Id`.
- `MountInfo` reports `TrackingMode` as a name; the select read `TrackingRate`,
  which is an object.
- `/sequence/state` returns a tree of containers, not a flat object with
  `Status` / `TargetName` / `ProgressExposures`. Sequence status, target,
  progress and the running flag are now derived by walking that tree, and a
  Sequence Current Instruction sensor was added.
- Flat panel brightness is scaled between the driver's `MinBrightness` and
  `MaxBrightness` rather than assuming 0–255.
- Timestamp sensors now return parsed datetimes, as their device class requires.
- The image entity passed `hass=None` to `ImageEntity` and called a non-existent
  `schedule_update_ha_states()`.

### Fixed — blueprints

All five blueprints were rewritten. Besides the entity-id rename they carried
three defects that predate this release:

- **Inputs were used inside templates without being bound.** Home Assistant
  requires blueprint inputs to be assigned in a `variables:` (or
  `trigger_variables:`) block before a template can reference them, so
  `{{ notify_device }}`, `{{ rms_threshold }}` and similar rendered empty.
- **Service calls carried no target**, and used signatures this release changed:
  `mount_set_tracking` took `enabled: true/false` (now `mode: Sidereal/Stopped`)
  and `sequence_load` took `path` (now `sequence_name`).
- **`meridian_flip_warning` compared minutes against an hours sensor**, so with
  the unit corrected it would have fired continuously. It now converts
  explicitly via a template trigger.

Entities and the target instance are now blueprint inputs with pickers filtered
to this integration, so the blueprints are independent of instance naming and
usable once per rig on a multi-instance setup. `weather_abort.yaml` was also
missing from the README's blueprint table.

### Breaking — every entity id is renamed

Entities now use `has_entity_name`, so their ids derive from their device:

```
<domain>.<instance>_<device>_<entity>
```

where *instance* is a name chosen at setup (default `NINA`). Most ids simply
gain a `nina_` prefix; entities whose old name did not begin with their device
(weather readings, the selected filter, observatory safety, time to meridian
flip) now sit under their device's name.

`unique_id` is unchanged, so entity history and per-entity settings survive;
only the ids move. The bundled cards and blueprints are updated. See the
upgrade section of the README for the mapping.

### Added — multiple N.I.N.A. instances

Two rigs with identical camera, filter wheel and focuser models can now be
configured side by side:

- Setup asks for an instance name, which prefixes every device and entity id.
- Device identifiers are keyed on the config entry, so identical hardware
  models never merge.
- The Lovelace cards take a matching `prefix:` option (default `nina`).

### Fixed — services could drive the wrong observatory

`_get_client()` returned whichever config entry loaded first, so with two
instances configured every one of the 37 services silently targeted instance
one — `mount_park` could park the wrong mount. Services now take a target
device: optional with a single instance, required with several, and an error
rather than a guess when ambiguous.

### Changed — one device per piece of equipment

Every entity previously hung off a single `N.I.N.A. Astrophotography` device.
There is now a `N.I.N.A.` service device with a child device per equipment type,
linked by `via_device`. Each carries the `model`, `model_id` and `sw_version`
reported by its driver, so `device_attr()` resolves per instrument. Driver
metadata that was published as entity attributes moved here, which is where
Home Assistant expects it. Entity IDs are unchanged.

`DriverInfo` is deliberately not mapped to `manufacturer`: several ASCOM drivers
return the template default ("Information about the driver itself. Version: 6.5"),
and `DisplayName` is just `Name` with " (ASCOM)" appended.

### Changed — attributes replaced by entities

Home Assistant's sensor documentation recommends additional entities over
`extra_state_attributes`, and provides `entity_category` plus
`entity_registry_enabled_default` to keep them out of the way. The ~120
capability and driver attributes added earlier in this release were removed:

- Driver identity moved to the device registry.
- Capability flags (`CanPark`, `HasShutter`, `SupportsOnOff`, …) now gate
  whether a control is offered or available, rather than being published.
- Values that duplicated a `select`'s options or a `number`'s bounds were dropped.
- Nine genuinely useful diagnostics became entities, disabled by default.

The eleven `*_name` sensors were removed along with them — the device registry
now carries that information.

### Added — image scale and HFR in arcseconds

Focal length is read from the active profile on every poll, so swapping a focal
reducer (or switching to a profile that has one) propagates immediately:

- `sensor.image_scale` — 206.265 × pixel size ÷ focal length, at current binning
- `sensor.last_image_hfr_arcsec` — rig-independent HFR, comparable against seeing
- `sensor.telescope_focal_length`, `sensor.active_profile`, `select.active_profile`

A pixel-based HFR threshold breaks on any binning, camera or focal-length change;
an arcsecond one does not.

### Fixed — found by testing against a live rig

Verified against a running N.I.N.A. 3.2 / Advanced API 2.2.15.2 instance:

- **Last-image sensors tracked calibration frames.** N.I.N.A. does not run star
  detection on flats, darks or bias frames, so every one reports `HFR 0` and
  `Stars -1`. On the test rig 45 of 89 frames were flats, and a dawn flat run
  pinned the last-image sensors to those sentinels. They now track light frames,
  and the sentinels map to unavailable.
- **Sequence progress could never reach 100%.** Conditional branches that are
  never taken stay `CREATED` forever; a completed sequence read 75%. Leaves
  under a container that already finished or was skipped are now excluded, which
  gives exactly 100% on the completed test sequence.
- **Sequence target was unusable with plugins.** Under Target Scheduler the
  container tree only names the scheduler's own container, and Sequencer+
  conditionals push real targets to an unpredictable depth. The target is now
  read from the last light frame. Container names also have N.I.N.A.'s
  `_Container` suffix stripped.
- **`TimeToMeridianFlip` is in hours**, confirmed by a live mount reporting `24`
  alongside `"24:00:00"`. It was previously labelled minutes.
- **`MountInfo.UTCDate` has no timezone offset** despite being UTC, so it was
  being interpreted as local time — a whole-timezone error.
- **`/livestack/status` returns `"Stopped"`**, not the lowercase `stopped` the
  spec documents. Status comparisons are now case-insensitive.
- **`/flats/status` reports `-1` iterations when idle**, which computed as 100%
  progress. A run now requires a positive total.
- **`/image-history` is oldest-first**, confirming the latest frame is the last
  element; the pre-2.0 code read element `[0]`.

### Added

Coverage for API resources the integration did not expose:

- **Switch device** — a sensor per read-only channel and a number per writable
  channel, discovered from the connected device, plus a `switch_set_value` service.
- **Rotator** — position, mechanical position, step size, moving/synced/reversed
  states, mechanical move and reverse controls.
- **Dome** — azimuth, shutter status, park/home/slewing/following/synchronized,
  slew-to-azimuth, follow toggle, stop, home and sync.
- **Flat panel** — cover state and open/close control, brightness sensor.
- **Camera** — binning, readout mode, USB limit, battery, dew heater, last
  download time, exposure end time, at-target-temperature, sub-sample and live
  view states.
- **Mount** — tracking mode, side of pier, site latitude/longitude/elevation,
  pulse guiding, meridian flip, sync, stop slew, set park position.
- **Focuser** — settling and temperature-compensation states, stop move.
- **Guider** — peak RA/Dec, pixel scale, calibrating and lost-lock states,
  clear calibration.
- **Autofocus history** (`/equipment/focuser/last-af`) — the last run's position,
  HFR, temperature, filter and timestamp.
- **Flat Wizard** (`/flats/*`) — state and progress sensors plus trained,
  auto-exposure, auto-brightness and sky flat services.
- **Livestack** (`/livestack/*`) — status sensor and start/stop switch.
- **Application** — N.I.N.A. version, start time, active tab select and a
  screenshot image entity (disabled by default).
- Sequence skip and reset.

Device capability and driver fields (`CanPark`, `DriverVersion`, `ExposureMax`,
`BinningModes`, …) are exposed as attributes on the matching entity rather than
as separate entities.

### Changed

- WebSocket event tables completed from the AsyncAPI spec: `SEQUENCE-ENTITY-FAILED`,
  `ROTATOR-MOVED`, `ROTATOR-MOVED-MECHANICAL`, `TS-WAITSTART`, `TS-NEWTARGETSTART`
  and `TS-TARGETSTART` were missing. The socket URL now honours the configured
  API version instead of hard-coding `/v2`.
- State-changing WebSocket events trigger a coordinator refresh instead of
  waiting for the next poll.
- Services are registered once per integration rather than once per config entry.
- Entity IDs referenced in the README, Lovelace cards and blueprints were
  corrected: Home Assistant derives them from the entity *name*, so several
  documented IDs (`sensor.image_last_hfr`, `binary_sensor.guider_is_guiding`, …)
  never existed.

### Breaking

See the upgrade table in the README. In summary: `mount_slew` takes RA in
degrees; `filterwheel_change_filter` takes `filter_id`; `sequence_load` takes
`sequence_name`; `mount_set_tracking` takes `mode`; `camera_capture` takes
`duration` and no longer accepts filter or binning; the `guider_dither` service
and the camera gain/offset, filter slot and binning number entities are removed.

---

## [1.4.2] - 2026-03-20

### Fixed

#### WebSocket URL corrected from /v2 to /v2/socket (websocket.py)
The WebSocket client was connecting to ws://HOST:1888/v2, which is the HTTP REST
API prefix — not a valid WebSocket endpoint. The correct URL per the ninaAPI v2
documentation is ws://HOST:1888/v2/socket.
EmbedIO (the web server used by the Advanced API plugin) returns a 404 HTTP response
when a WebSocket upgrade is attempted at an unregistered path, causing the client to
retry every 5 seconds with exponential backoff. This produced the repeated log entry:
N.I.N.A. WebSocket: unexpected error: 404, message='Invalid response status',
url='ws://10.0.20.96:1888/v2'
With this fix the WebSocket connects successfully on the first attempt, enabling
all push-driven features that depend on it:

IMAGE-SAVE events → per-frame statistics sensors update instantly on capture
SEQUENCE-STARTING events → session frame stats reset for each new sequence
MOUNT-BEFORE-FLIP / MOUNT-AFTER-FLIP events → meridian flip automations
All other ninaAPI WebSocket events fire correctly as native HA events

Impact: Every installation running v1.0.0–v1.4.1 has had non-functional
WebSocket push events. Polling-based sensors (all REST endpoint sensors) were
unaffected and continued to work normally.

## [1.4.1] - 2026-03-20

### Fixed

#### Mount endpoint corrected in `api.py`
All mount/telescope API calls were targeting `/equipment/telescope/...` but the
N.I.N.A. Advanced API v2.2.x routes these under `/equipment/mount/...`. This caused
all mount sensors (RA, Dec, altitude, azimuth, time to meridian flip, sidereal time)
and all mount control services (park, unpark, slew, tracking, find home) to return
404 errors.

Affected methods updated:

| Method | Old path | Corrected path |
|---|---|---|
| `get_mount()` | `/equipment/telescope/info` | `/equipment/mount/info` |
| `connect_mount()` | `/equipment/telescope/connect` | `/equipment/mount/connect` |
| `disconnect_mount()` | `/equipment/telescope/disconnect` | `/equipment/mount/disconnect` |
| `slew_mount()` | `/equipment/telescope/slew-to-coordinates-j2000` | `/equipment/mount/slew-to-coordinates-j2000` |
| `park_mount()` | `/equipment/telescope/park` | `/equipment/mount/park` |
| `unpark_mount()` | `/equipment/telescope/unpark` | `/equipment/mount/unpark` |
| `set_tracking()` | `/equipment/telescope/tracking` | `/equipment/mount/tracking` |
| `find_home()` | `/equipment/telescope/find-home` | `/equipment/mount/find-home` |


## [1.4.0] - 2026-03-20

### Added

#### Weather station sensors — 14 new sensor entities (`sensor.py`)
Full ASCOM ObservingConditions standard mapped to HA sensors. Works with any weather driver connected in N.I.N.A.: OpenWeatherMap, Pegasus UPB, AAG CloudWatcher, ASCOM Alpaca weather stations, and others.

| Entity | Description | Unit |
|---|---|---|
| `sensor.weather_temperature` | Ambient air temperature | °C |
| `sensor.weather_humidity` | Relative humidity | % |
| `sensor.dew_point` | Dew point temperature | °C |
| `sensor.wind_speed` | Wind speed | m/s |
| `sensor.wind_direction` | Wind direction | ° |
| `sensor.wind_gust` | Wind gust speed | m/s |
| `sensor.barometric_pressure` | Atmospheric pressure | hPa |
| `sensor.cloud_cover` | Cloud cover percentage | % |
| `sensor.rain_rate` | Rain rate | mm/h |
| `sensor.sky_quality` | Sky quality (SQM) | mag/arcsec² |
| `sensor.sky_brightness` | Sky brightness | lux |
| `sensor.sky_temperature` | Sky temperature (IR) | °C |
| `sensor.atmospheric_seeing` | Atmospheric seeing (FWHM) | arcsec |
| `sensor.weather_station_name` | Weather driver name | — |

#### Safety monitor — 3 new entities (`binary_sensor.py`)
| Entity | Description |
|---|---|
| `binary_sensor.safety_monitor_connected` | Safety monitor device connectivity |
| `binary_sensor.observatory_safe` | Safety state using HA SAFETY device class (`on` = **unsafe**, per HA convention) |
| `sensor.safety_monitor_name` | Safety monitor device name |

#### Weather abort blueprint (`blueprints/automation/nina_astrophotography/weather_abort.yaml`)
The most critical observatory automation — a full safe-shutdown triggered by unsafe conditions. Supports:
- Safety monitor going unsafe (immediate trigger, no delay)
- Wind speed threshold with configurable sustained duration
- Rain rate threshold
- Cloud cover threshold
- Optional auto-resume when conditions clear
- Configurable shutdown steps: stop sequence → park mount → warm camera → close dome
- Pre- and post-shutdown mobile notifications with frame count

#### Weather & Safety Lovelace Card (`www/nina-weather-card.js`)
- Safety banner at top: green `Conditions safe` / pulsing red `UNSAFE — conditions exceeded` / grey if disconnected
- Dew point proximity warning: fires when temperature is within 3°C of dew point
- Atmosphere grid: temperature, humidity, dew point, pressure with colour-coded warning thresholds
- Wind panel with animated compass rose (arrow colour changes red at dangerous speeds)
- Sky conditions grid: cloud cover, rain rate, sky temperature, atmospheric seeing
- Sky quality (SQM) progress bar mapped to Bortle scale with qualitative label (Excellent/Good/Moderate/Poor)
- Graceful empty state when no weather station is connected in N.I.N.A.

Add to a dashboard:
```yaml
type: custom:nina-weather-card
```

---

## [1.3.0] - 2026-03-20

### Added

#### Image streaming via Advanced API (`api.py`)
Added `get_image_bytes()` and `get_image_stream_url()` methods to `NinaApiClient`. The Advanced API serves JPEG frames at `GET /v2/api/image?index=0&stream=true&useAutoStretch=true`, enabling direct image retrieval without a separate plugin.

#### HA Image entity (`image.py`)
New `image.nina_latest_captured_frame` entity using HA's native `ImageEntity` platform. Updates automatically when an `IMAGE-SAVE` WebSocket event fires. Compatible with the built-in Picture Entity Card and any HA integration that consumes image entities.

#### Image Panel Lovelace Card (`www/nina-image-panel-card.js`)
Full-featured image viewer card with:
- Live image fetched directly from the N.I.N.A. PC streaming endpoint
- Stats overlay: filter, HFR, star count, guide RMS, target name
- ADU histogram derived from frame statistics sensors (min/max/mean/median visualisation)
- Recent frames strip: last 6 thumbnails with filter labels, click to browse back through history
- Stats row below image: HFR (colour-coded), star count, mean ADU, exposure time
- Click-to-fullscreen (loads full-quality version in modal)
- Auto-refreshes on `nina_image_save` HA event — no manual reload needed
- Exposing indicator bar animates while camera is actively integrating

Card requires `host` config pointing to the N.I.N.A. PC:
```yaml
type: custom:nina-image-panel-card
host: 192.168.1.100
port: 1888
```

---

## [1.2.0] - 2026-03-20

### Added

#### Per-frame image statistics (`frame_statistics.py`, `frame_stats_sensor.py`)
The integration now maintains a live in-memory ring buffer of every frame saved by N.I.N.A. during the current session, populated in real time from `IMAGE-SAVE` WebSocket events. This is entirely push-driven — sensors update the instant a frame lands, with no polling delay.

**23 new sensor entities:**

| Entity | Description |
|---|---|
| `sensor.last_frame_hfr` | Half-flux radius of the most recent frame |
| `sensor.last_frame_hfr_std_dev` | HFR standard deviation across detected stars |
| `sensor.last_frame_stars` | Star count detected in the most recent frame |
| `sensor.last_frame_mean_adu` | Mean ADU of the most recent frame |
| `sensor.last_frame_median_adu` | Median ADU of the most recent frame |
| `sensor.last_frame_min_adu` | Minimum ADU (sky background indicator) |
| `sensor.last_frame_max_adu` | Maximum ADU (saturation indicator) |
| `sensor.last_frame_adu_std_dev` | ADU standard deviation |
| `sensor.last_frame_filter` | Filter used for the most recent frame |
| `sensor.last_frame_exposure` | Exposure duration of the most recent frame |
| `sensor.last_frame_guide_rms` | Guide RMS string at the time of capture |
| `sensor.last_frame_target` | Target name from the most recent frame |
| `sensor.rolling_avg_hfr_10` | Rolling average HFR over the last 10 frames |
| `sensor.rolling_avg_stars_10` | Rolling average star count over the last 10 frames |
| `sensor.rolling_avg_adu_10` | Rolling average mean ADU over the last 10 frames |
| `sensor.frame_session_count` | Total frames captured this session |
| `sensor.session_integration_time` | Total integration time in minutes |
| `sensor.session_avg_hfr` | Session-wide average HFR |
| `sensor.session_best_hfr` | Best (lowest) HFR recorded this session |
| `sensor.session_worst_hfr` | Worst (highest) HFR recorded this session |
| `sensor.session_avg_stars` | Session-wide average star count |
| `sensor.hfr_trend` | Focus quality trend: `improving`, `degrading`, or `stable` |
| `sensor.hfr_trend_delta` | Numeric HFR delta (last 5 vs previous 5 frames; negative = improving) |
| `sensor.frames_per_filter` | Total frame count with per-filter breakdown in extra attributes |
| `sensor.frame_sparkline_data` | 30-point sparkline arrays in extra attributes (used by the card) |

**New behaviour:**
- Session stats automatically reset when a `SEQUENCE-STARTING` WebSocket event is received
- All frame sensors use `RestoreEntity` — last known values survive HA restarts
- Ring buffer holds up to 500 frames before oldest are dropped

#### Frame Statistics Lovelace Card (`www/nina-frame-stats-card.js`)
A new custom card providing a live per-session imaging dashboard:
- KPI row: last HFR vs rolling average, star count, exposure and filter
- HFR trend chip with numeric delta and colour-coded border (green = improving, red = degrading)
- Session average and best HFR summary
- Three canvas sparkline charts: HFR (with dashed average line), star count, mean ADU — each point colour-coded by the filter used
- Per-filter frame count chips with matching colours
- Graceful empty state before the first frame arrives

Add to a dashboard with:
```yaml
type: custom:nina-frame-stats-card
```

---

## [1.1.0] - 2026-03-20

### Fixed

#### Endpoint paths corrected for N.I.N.A. Advanced API v2.2.x (`api.py`)
All equipment info endpoints were returning 404. The v2.2.x plugin requires an `/info` suffix on every equipment path. Updated all endpoints:

| Old path | Corrected path |
|---|---|
| `/equipment/camera` | `/equipment/camera/info` |
| `/equipment/telescope` | `/equipment/telescope/info` |
| `/equipment/focuser` | `/equipment/focuser/info` |
| `/equipment/filterwheel` | `/equipment/filterwheel/info` |
| `/equipment/guider` | `/equipment/guider/info` |
| `/equipment/rotator` | `/equipment/rotator/info` |
| `/equipment/dome` | `/equipment/dome/info` |
| `/equipment/flatdevice` | `/equipment/flatdevice/info` |

#### Response key names corrected (`sensor.py`, `number.py`)
Several sensor key paths did not match the actual API response structure:

- `TemperatureSetPoint` → `TargetTemp` (camera cooling setpoint sensor and number entity)
- `Temperature` and `CoolerPower` now handle `"NaN"` string values returned when the sensor is unavailable — these correctly resolve to `unknown` rather than surfacing `NaN`
- `Gain` and `Offset` values of `-1` (returned when camera is not connected) now resolve to `unknown` rather than `-1`

#### JSON content-type handling (`api.py`)
Added `content_type=None` to all `resp.json()` calls to prevent parse failures when the API returns `text/plain` or omits the content-type header.

### Added

#### New binary sensors (`binary_sensor.py`)
- `binary_sensor.camera_exposing` — true while a capture is in progress (`IsExposing` key)
- `binary_sensor.mount_at_home` — true when mount is at home position (`AtHome` key)
- `binary_sensor.flatdevice_connected` — flat device connectivity

#### New diagnostic sensors (`sensor.py`)
- `sensor.camera_name` — connected camera device name
- `sensor.focuser_step_size` — focuser step size in micrometres

---

## [1.0.0] - 2026-03-20

### Added
- Initial release
- Full N.I.N.A. Advanced API v2 support via REST polling and WebSocket push events
- 22 measurement and status sensors (camera temperature, guiding RMS, mount coordinates, sequence progress, image statistics)
- 14 binary sensors (equipment connectivity, mount state, guider state, dome shutter, sequence running)
- 7 controllable number entities (camera gain, offset, binning, cooling setpoint, focuser position, filter slot, rotator position)
- 4 switches (camera cooler, mount tracking, autoguiding, flat panel light)
- 2 select entities (active filter by name, mount tracking rate)
- 1 light entity (flat panel with HA brightness control)
- 13 button entities for one-tap actions (park, unpark, auto focus, dither, sequence start/stop, dome open/close, etc.)
- 20 registered HA services for full rig control
- Persistent WebSocket connection with automatic reconnect and exponential backoff
- Every N.I.N.A. event fires a native HA event for automation triggers
- UI config flow with connection validation
- Options flow for adjustable poll interval (5–300 seconds)
- 4 automation blueprints: session startup, session shutdown, guiding quality alert, meridian flip warning
- Custom `nina-observatory-card.js` Lovelace card with equipment status, mount coordinates, guiding RMS bars, image stats, and one-tap control buttons

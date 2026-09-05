# Changelog

All notable changes to the N.I.N.A. Astrophotography Home Assistant integration are documented here.

---

## [2.0.0] - unreleased

### Breaking

- **The config entry is now titled by an instance name you choose**, not
  `N.I.N.A. <version> @ <host>`: a version in a title goes stale on the rig's
  next update, and the title is what names the hub device. Existing entries keep
  their title, and it becomes their instance name.
- **`instance_name` is a new, required field in the add form** (default
  `N.I.N.A.`). It prefixes every device name, so two rigs can coexist; a blank
  name, or one another entry already uses, is refused.
- **The `api_version` dropdown is gone from the add form.** It only ever offered
  one value. The key is still read from existing entry data by the client that
  serves the unmigrated services.
- **`switch.<instance>_flat_panel_light` is removed.** The flat panel's light
  was both a `light` and a `switch` for one device function; the `light`
  survives. Nothing in 2.0 claims the switch's `unique_id`, so an upgraded
  install keeps the row as an unavailable leftover until it is deleted.
- New installs get device-scoped entity ids: entities now hang off a device
  per equipment type rather than one device per integration, and the device
  name is part of the id. `docs/2.0-renames.md` is the mapping. An **existing**
  install is not renamed — Home Assistant keys the registry on `unique_id`, so
  an entity whose `unique_id` is unchanged keeps the id it already has and only
  moves to its new device.
- The poll interval is now capped at **60 s** in both the add and the options
  form; 1.4.5 accepted 5–300. The tiering design assumes a fast tier near 10 s.
  An entry already storing a longer interval keeps polling at that rate, and
  has to be lowered to 60 or less the next time the options form is submitted.
- Home Assistant bus events keep their names (`nina_<event>` and the catch-all
  `nina_event`) but the payload is now `event` / `time` / `data` / `frame`
  instead of the raw `response` dict: the event socket emits models, and a wire
  dict must not cross the API seam. Only the wrapper changed — `data` carries
  the event's own scalar fields under the wire's own key names (`IsSafe` on
  `SAFETY-CHANGED`, `Previous`/`New` on `FLAT-BRIGHTNESS-CHANGED`, …), so
  `trigger.event.data.response.IsSafe` becomes `trigger.event.data.data.IsSafe`.
  Nested objects and arrays are not carried: the only ones the API sends are
  `FILTERWHEEL-CHANGED`'s `Previous`/`New` and the `TS-*` coordinates, both of
  which put empty arrays where scalars belong. `IMAGE-SAVE`'s statistics move
  to `frame` as a mapped frame — sentinels already normalised, keys in
  snake_case (`frame.hfr`, `frame.stars`). `trigger.event.data.event` is
  unchanged.

### Added

- **A session rollover hour**, under **Configure**: `rollover_hour`, 0–23,
  default 12. It is read in the RIG's local hours, so a rig whose Windows clock
  runs UTC can put the boundary at a real midday on site rather than in the
  middle of its dawn flats.

### Changed

- `nina_websocket_connected` and `nina_websocket_disconnected` now fire on
  connection **transitions** only; 1.4.x re-fired `disconnected` on every failed
  reconnect attempt, so an automation counting them will see far fewer.
  `disconnected` also fires when the integration is unloaded or reloaded while
  the socket was connected.

---

## [1.4.5] - 2026-09-03

Endpoint corrections. Seven commands in `api.py` asked for paths the Advanced
API does not serve, so they returned a 404 page and the equipment never moved,
and the image entity asked for its stretch under a parameter name that does not
exist. Every path here is checked against the 2.2.15 specification and the
fixes are pinned by tests; the rig they were confirmed against runs Advanced
API 2.2.15.2 on N.I.N.A. 3.2.0.9001.

### Behaviour changes to be aware of

- **The dither service and button are gone.** The API has no dither route
  anywhere in its 156 paths — dithering is driven from inside a sequence and
  only reported back. `nina_astrophotography.guider_dither` and
  `button.guider_dither` never worked and could not be made to, so they are
  removed rather than left in the service picker to be written into an
  automation. Delete the orphaned button entity from the entity registry, and
  remove any script or dashboard row that calls the service. The
  `nina_guider_dither` event still fires when a sequence dithers, so an
  automation that *reacts* to dithering is unaffected.
- **Commands that silently did nothing now actually run.** Abort Capture, Slew
  Mount, Find Home, Start/Stop Guiding and the flat panel light all reached a
  path that does not exist. An automation written around one of them has been
  running with that step doing nothing; it will now move equipment.

### Fixed

- **Slew Mount pointed the mount at the wrong part of the sky.** Beyond the
  wrong path, `/equipment/mount/slew` reads `ra` in degrees while the service
  takes decimal hours — as its documentation says, and as `sensor.mount_ra`
  reports, because every RA N.I.N.A. hands out is in hours. Unconverted, a
  slew to 22h04m would have gone to RA 22.07 degrees: 1h28m, eight hours away,
  with no error, because that is a valid RA either way. The service contract is
  unchanged, so nothing written against it needs revisiting.
- Abort Capture requested `/equipment/camera/abort`; the API serves
  `/equipment/camera/abort-exposure`. The exposure ran to completion.
- Start Guiding requested `/equipment/guider/start-guiding` and sent the
  calibration flag as `forceCalibration`. The path is `/equipment/guider/start`
  and the flag is `calibrate` — an unbound flag falls back to the API default,
  so `force_calibration: true` would have reused the stale calibration a caller
  asks to discard after a meridian flip.
- Stop Guiding requested `/equipment/guider/stop-guiding`; the API serves
  `/equipment/guider/stop`. The shutdown blueprint went on to park the mount
  with PHD2 still guiding.
- Mount Find Home requested `/equipment/mount/find-home`; the API serves
  `/equipment/mount/home`.
- The flat panel light requested `/equipment/flatdevice/toggle-light`; the API
  serves `/equipment/flatdevice/set-light`. Brightness worked, so a flat run
  driven from Home Assistant shot its flats against a dark panel.
- `image.nina_latest_image` showed an unstretched frame. The stretch was asked
  for as `useAutoStretch`, which is not a parameter on `/image/{index}`; the
  API's is `autoPrepare`. An unknown query parameter binds nothing and is not
  rejected, so the request succeeded and returned the linear frame — very
  nearly black for a single sub-exposure, with nothing in the log to explain it.
- `nina-image-panel-card.js` requested `/image?index=N`. `/image` is not a
  route, so the main frame and every strip thumbnail came back 404. This is the
  same bug fixed in the integration in 1.4.3; the card builds its own URL in
  the browser and was missed. Its stretch parameter is corrected too, and both
  are now pinned by a test.

### Known remaining

Two endpoints are still wrong and are deliberately not touched here, because
neither is a path swap:

- `get_latest_image()` calls `/image/latest` and `get_sequence()` calls
  `/sequence`. The real path for the latter is `/sequence/state`, which returns
  a nested container tree rather than the flat object every sensor reads.
- `camera_capture` sends the exposure time as `time`, but the API reads
  `duration`; `binning` and `filter_index` bind nothing at all, having no
  equivalent parameters on the capture endpoint. `sequence_load` sends `path`
  where the API reads `sequenceName`, which is a name from
  `/sequence/list-available` and not a file path, so the service field is
  wrong as well as the parameter.

---

## [1.4.4] - 2026-09-03

Published from this fork, which is now the maintained line — the original
repository has had no commits since 2026-03-20. Every fix in 1.4.3 and 1.4.4 is
also open as an individual pull request there, and will stay open.

### Fixed

- `Time to Meridian Flip` returned hours while the sensor declared minutes, so
  every reading was 60x too small. A flip 45 minutes away read `0.75`. The
  meridian-flip warning blueprint triggers `below: warning_minutes`, so a
  15-minute threshold fired when the flip was 15 *hours* away.
- `Last Image Star Count` read the field `DetectedStars`, which does not exist
  on a frame — the API renames it to `Stars` on the way out. That sensor had
  always been `unknown`.
- `Latest Captured Frame` reported the moment the integration loaded as though
  it were a capture time. It now reports nothing until a frame arrives.
- `nina-image-panel-card.js` requested the same broken image-history endpoint
  the integration did, and swallowed the failure, leaving its filmstrip filter
  labels permanently blank.

### Changed

- Documentation and issue links in `manifest.json`, `hacs.json` and the five
  blueprint `source_url` fields now point at this fork, so "Report an issue"
  and Home Assistant's blueprint re-import check reach a maintained repository.
- Adds the modification notice GPL-3.0 section 5(a) requires, naming the
  upstream original and the date this line diverged.

### Note on statistics

`Time to Meridian Flip` keeps its `min` unit string, so Home Assistant will not
treat this as a unit change. Existing long-term statistics show a 60x
discontinuity at this version rather than being rescaled. The mount also
reports 24 hours when no flip is pending, which now records as `1440`.

---

## [1.4.3] - 2026-09-02

Bug-fix rollup. Every change here is also open as an individual pull request
upstream; this release exists so the fixes can be installed together.

### Behaviour changes to be aware of

- **Failed commands now raise.** Button presses and number sets previously
  logged a failure and returned normally, which Home Assistant reads as
  success. They now raise `HomeAssistantError`, so an automation that silently
  depended on a failing call carrying on will now stop at that step. This is
  the point of the change, but it can surface automations that were quietly
  broken.
- **The mount tracking switch worked backwards.** Turning it *off* sent the
  wrong parameter and started sidereal tracking. If any automation compensated
  for that, it needs revisiting.

### Fixed

- API failures are no longer reported as success. The Advanced API answers HTTP
  200 for everything and carries the outcome in the response envelope, which
  was never checked.
- N.I.N.A. being unreachable now marks entities unavailable instead of
  publishing zeros. A crashed instance raises `ServerDisconnectedError`, which
  was previously classified as an API error rather than a lost connection.
- A wrong endpoint is distinguished from a refused command, so a permanently
  missing path fails the config entry instead of retrying forever, while a 5xx
  still retries.
- The image entity works at all. `/image` was requested with the index as a
  query parameter; the API serves `/image/{index}`, so every fetch returned
  404. A refusal also arrives as HTTP 200 carrying JSON, which was handed to
  the frontend as image data.
- The image platform no longer fails to set up, and its WebSocket listener is
  released on reload rather than leaking one per config entry reload.
- Image history reads `/image-history`; `count` is a boolean, not a limit, and
  the response is oldest-first, so the "latest frame" sensors read the wrong
  end of the list.
- Calibration frames no longer poison the session statistics. FLAT/DARK/BIAS
  report `HFR 0` and `Stars -1`, which were being averaged in.
- All 25 frame-statistics sensors update again — the callback called a method
  that does not exist — and the twelve last-frame sensors survive a restart.
- Blueprint inputs take effect. `!input` cannot be read from a template unless
  it is bound in `variables:` first, so notifications went nowhere and weather
  aborts never fired.
- Filter selection handles unnamed filter slots, which were offered in the
  dropdown but could not be selected.
- `manifest.json` points at this integration rather than the N.I.N.A. plugin.

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

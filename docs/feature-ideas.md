# Feature ideas

Features that would help someone watching a rig from Home Assistant, written
up far enough to start an issue from. None is promised or scheduled. To take
one on, open an issue that links its section here, so two people don't build
the same thing. When it ships, delete its section in the same PR.

Each idea lists the data it needs. **Already fetched** means the integration
requests it, though it may throw part of it away. **New request** means a route
the integration never calls. Look up a new route in the vendored spec,
`docs/v2.0/ninaapi-v2-openapi.yaml`, then capture it before writing code
against it (`docs/contributing/fixtures.md`). A route that is not on that
page's read-only list may be captured only from a simulator, or from a live rig
whose operator has said it is idle. Anything marked *verify* is believed but
not yet confirmed against a rig.

Effort and value are rough: **S** is a blueprint or a single entity, **M** adds
model or session-fold work, and **L** adds a card plus new requests.

| Idea | Kind | Effort | Value |
|---|---|---|---|
| [Verify the meridian flip](#verify-the-meridian-flip) | blueprint | S | High |
| [Alert when the night ends early](#alert-when-the-night-ends-early) | blueprint, entity | S–M | High |
| [Check the rig is put to bed](#check-the-rig-is-put-to-bed) | blueprint | S | High |
| [Alert on equipment dropping mid-sequence](#alert-on-equipment-dropping-mid-sequence) | blueprint | S | High |
| [Alert when the camera misses its setpoint](#alert-when-the-camera-misses-its-setpoint) | blueprint | S | High |
| [Detect degrading frames](#detect-degrading-frames) | entity, blueprint | M | High |
| [Morning report](#morning-report) | blueprint, attribute | S | High |
| [Alert on unguided lights](#alert-on-unguided-lights) | blueprint | S | Medium-high |
| [Long-term integration statistics](#long-term-integration-statistics) | entity | S | Medium-high |
| [Surface sequence-authored messages and the log](#surface-sequence-authored-messages-and-the-log) | event, action | M | Medium-high |
| [Rich phone notifications](#rich-phone-notifications) | blueprint | M | Medium-high |
| [Skip an instruction and choose a sequence](#skip-an-instruction-and-choose-a-sequence) | action, select | S–M | Medium |
| [N.I.N.A. screenshot on demand](#nina-screenshot-on-demand) | image, card | M | Medium |
| [The night in the logbook](#the-night-in-the-logbook) | logbook | S–M | Medium |
| [Dew-margin alert](#dew-margin-alert) | blueprint | S | Medium |
| [Target Scheduler context on the target](#target-scheduler-context-on-the-target) | attributes | S | Medium |
| [Guide graph card](#guide-graph-card) | card, entities | M–L | Medium |
| [Sun and twilight at the site](#sun-and-twilight-at-the-site) | entity | S | Medium-low |
| [Horizon and moon on the sky map](#horizon-and-moon-on-the-sky-map) | card | M | Medium-low |
| [Stop-motion actions](#stop-motion-actions) | action | S | Medium-low |
| [Fields fetched but unused](#fields-fetched-but-unused) | entities | S each | Low |

---

## Alerts that save a night

### Verify the meridian flip

- **Problem:** a cancelled flip still raises `MOUNT-AFTER-FLIP`, but leaves
  tracking off and the guider stopped, and a slew that fails without throwing
  carries on as if it worked. The meridian flip blueprint's `complete` branch
  reports "The flip finished. Guiding and imaging resume." whatever happened,
  and every sub after it trails.
- **Proposal:** a new input on `meridian_flip_warning.yaml`, with a default.
  After AFTER-FLIP, require tracking on, a changed pier side, the guider
  `Guiding` and a new light frame. The message names the check that failed.
  Autofocus, recentring and settling inside the flip all happen before
  AFTER-FLIP; the window has to cover the sequence's own after-flip triggers
  plus one full exposure. So default it to the longest exposure plus a grace,
  as the stall alert does, rather than a fixed number of minutes.
- **Data (already fetched):** the `MOUNT-AFTER-FLIP` event (it carries no
  payload, so there is no success flag to read), `mount_side_of_pier`,
  `guider_status` and `last_frame_at`. `MountModel.tracking_enabled` is mapped
  but no entity exposes it; a binary sensor for it would be cleaner than
  reading the tracking-rate select.
- **Watch out for:**
  - Record the pier side at `MOUNT-BEFORE-FLIP` (the `committed` branch) to
    compare against. The blueprint runs `mode: queued`, so each trigger is a
    separate run and nothing carries over between them by itself.
  - Some drivers report pier side as unknown; skip that check for them.
  - An unsafe flip belongs to `weather_abort`.
  - *Verify* on the simulator that a cancelled flip raises AFTER-FLIP; this is
    read from N.I.N.A.'s source, not seen on a rig.

### Alert when the night ends early

- **Problem:** a sequence error, Target Scheduler running out of targets, a
  N.I.N.A. crash or a Windows reboot ends the night hours before dawn. The
  stall alert's no-frames check is silent while the sequencer is stopped, and a
  quick restart beats the unreachable check.
- **Proposal:**
  - A timestamp sensor for when N.I.N.A. started, from `/application-start`,
    which is already polled every tick. A change in its value means N.I.N.A.
    restarted; `polling.RestartDetector` already detects this.
  - A blueprint that fires when the sequencer stops, or N.I.N.A. restarts,
    more than a chosen time before dawn at the site. The message gives
    context: mount parked or tracking, camera cooling, the last error.
- **Watch out for:**
  - Gate on time before dawn, not on a sun elevation: a sequence that ends at
    astronomical dawn on purpose stops while the sun is still well below the
    horizon, and would page every morning.
  - Across a restart `sequencer_running` goes on → unavailable → off, so a
    `from: "on"` / `to: "off"` trigger misses it.
  - A deliberate stop looks the same, so offer a mute window or skip stops
    that Home Assistant made.
  - Target Scheduler legitimately stops when nothing is left to image, so the
    wording must not claim a failure.
  - Stay quiet while unsafe, which `weather_abort` owns.

### Check the rig is put to bed

- **Problem:** the sequence ended, or dawn came, and the mount is still
  tracking toward the pier, or the cooler runs all day, the flat panel is lit
  or the dome is open. Session shutdown parks the mount, closes the dome only
  over a parked mount and alerts if the roof doesn't close. But it runs only at
  its scheduled time and never checks the cooler or the flat panel.
- **Proposal:** a blueprint that checks the end state N minutes after the
  sequencer stops, or at dawn at the site, with a toggle for each check. It
  notifies by default. Tracking still on is the alarm, because that is the
  pier-collision risk; not parked is a warning, since some hosted rigs end at
  home rather than park. An alternative is to extend `session_shutdown.yaml`
  with a sequencer-stopped trigger and the extra checks, as new inputs with
  defaults, rather than duplicating its park-then-close.
- **Data (already fetched):** `mount_at_park`, the tracking select, the
  `camera_cooler` switch, the flat panel light, `dome_shutter_status` and
  `sequencer_running`.
- **Watch out for:** some hosted sites leave cooling on deliberately. The dome
  entities have been tested on the simulator only.

### Alert on equipment dropping mid-sequence

- **Problem:** the focuser disconnects at midnight and focus drifts all night,
  or the filter wheel drops and every sub is shot through one filter. The stall
  alert only notices if frames stop, and only after 20 minutes or more.
- **Proposal:** a blueprint triggered by the `nina_<device>_disconnected` bus
  events, or by a chosen entity going `unavailable`, while
  `sequencer_running` is on.
- **Watch out for:**
  - Sequences disconnect the flat panel, and everything at the end, on purpose,
    so leave the flat panel out by default.
  - Events missed while the socket was down are not fired again, so trigger on
    `unavailable` too. Pick entities that do go unavailable on a disconnect:
    those with `_survives_disconnect` (`entity.py`) keep their state.
  - Gate on `reachable`, so that losing the link isn't reported as every device
    dropping at once.

### Alert when the camera misses its setpoint

- **Problem:** on a hot night the cooler saturates and the sensor runs above
  its setpoint, so the night's lights no longer match the dark library. The
  observatory card warns only when the cooler is off.
- **Proposal:** a blueprint that fires when the temperature drifts from the
  setpoint for 10 minutes while imaging with the cooler on, and when the cooler
  is saturated *and* drifting. High cooler power with the temperature holding
  is not a fault. A variant could compare each light's own temperature (from
  `nina_image_save`) with the setpoint. A `camera_at_setpoint` binary sensor is
  optional.
- **Data:** `camera_temperature`, `number.<instance>_camera_target_temperature`
  (from `TemperatureSetPoint`) and `camera_cooler_power`. The wire also carries
  `AtTargetTemp`, which is not mapped; its tolerance is unknown (*verify*).
- **Watch out for:**
  - Cooling and warming ramps.
  - The setpoint keeps its last value after a warm-up.
  - Uncooled cameras and DSLRs have no setpoint.
  - Some drivers, including the one in the captured fixtures, report whole
    degrees, so a 1 °C threshold behaves as 2 °C there.

### Detect degrading frames

- **Problem:** cloud, dew, focus drift or a rising moon costs hours of subs
  while the rig looks healthy. The stall alert doesn't notice, because frames
  keep arriving. The trend logic exists only in
  `www/nina-frame-stats-card.js`, which no automation can use.
- **Proposal:** a `frames_degraded` binary sensor with a `reason` attribute,
  computed in `session.py`, and a blueprint on top of it. Compare each light
  with a baseline for the same target, filter, exposure and gain (and binning,
  once #173 lands). Starting values, to be tuned:
  - stars below half the baseline: cloud or dew;
  - HFR above 1.3 times the baseline for two or three subs: focus or seeing;
  - sky background (median minus an estimate of the offset pedestal) well
    above the baseline: moon, dawn or lit cloud.
- **Data (already fetched):** each light's HFR, stars, mean and median ADU,
  RMS, filter, exposure and target (`Frame` in `api/models.py`, folded into
  `session.recent_lights`). `HFRStDev` is on the wire but discarded.
- **Depends on:** #173. Pixel HFR can't be compared across binnings until each
  frame carries its binning.
- **Watch out for:**
  - Key by target as well as filter: moving from a Milky Way field to a sparse
    galaxy field halves the stars and shifts the background, and would fire on
    every target change.
  - Key by filter, not by a run of consecutive frames: filters are interleaved
    by hand as well as by Target Scheduler. Never infer anything from a
    filter's name.
  - Raw mean ADU includes the bias pedestal, so on short narrowband subs a
    "twice the baseline" test barely moves.
  - A target sinking toward the horizon worsens HFR for a real reason, and
    autofocus moves the baseline.
  - At a dark site cloud can lower the background rather than raise it.
  - Narrowband star counts are small and noisy, so require persistence before
    firing.
  - N.I.N.A.'s and Hocus Focus's star detection give HFR on different scales.

### Alert on unguided lights

- **Problem:** PHD2 loses the guide star and N.I.N.A. keeps exposing unguided.
  The guiding alert's RMS reads unknown on `LostLock`, which restarts its
  window, and the stall alert stays quiet because frames keep coming.
- **Proposal:** a blueprint that fires when `guider_status` stays `LostLock`
  while `sequencer_running` is on, or when a light arrives without guiding RMS
  while the guider is connected. This could instead be a `reason` in
  [Detect degrading frames](#detect-degrading-frames).
- **Watch out for:** the coordinator already hides the stale `LostLock` N.I.N.A.
  reports after a guider stop, so read the entity, not the raw state. Some
  operators image unguided on purpose, so offer an opt-out. Ignore flips and
  settle windows.

### Dew-margin alert

- **Problem:** dew forms on the corrector or objective and HFR and star counts
  collapse. The weather card flags a dew threat (`dew_margin`, default 3 °C),
  but nothing notifies.
- **Proposal:** a blueprint that fires when `weather_temperature` minus
  `weather_dew_point` stays under a margin (default 3 °C, as on the card) for N
  minutes while `sequencer_running` is on. Pairs with the star-drop reason in
  [Detect degrading frames](#detect-degrading-frames).
- **Data (already fetched):** `sensor.<instance>_weather_temperature`,
  `_weather_dew_point` (derived from humidity when the station gives none) and
  `_weather_humidity`.
- **Watch out for:**
  - The camera's dew heater warms only the sensor window, not the objective or
    corrector, so never offer it as the fix. Dew straps are usually channels on
    a switch device.
  - Under a clear sky the optics radiate below air temperature by a degree or
    more, so a station's air reading overstates the margin.
  - Weather channels that report `"NaN"` read unknown.
  - Stay quiet while unsafe, as the card does.

---

## Reporting and history

### Morning report

- **Problem:** "What did I get last night, and did the dawn flats run?" means
  opening N.I.N.A. or the Target Scheduler database.
- **Proposal:** a blueprint that sends a summary at dawn at the site, or when
  the sequencer stops: lights and hours per target and filter, mean HFR, time
  spent waiting, and flats per filter.
- **Data:** `session_avg_hfr`'s `by_target` and `by_filter` attributes,
  `session_image_count` with `light_count`, `last_frame_at` and
  `recent_waits`. The one addition is flat (and dark) counts per filter as an
  attribute. FLAT frames are already in the session fold, keyed by image type.
- **Watch out for:** send it before the session rolls over. The session keeps
  only frames from the current N.I.N.A. process, so if N.I.N.A. restarts
  overnight the report counts only frames since the restart.

### Long-term integration statistics

- **Problem:** hours per night, month or season belong in a statistics-graph
  card, but `session_integration_time` uses the `MEASUREMENT` state class, so
  Home Assistant's long-term statistics can't add it up.
- **Proposal:** a new sensor with `state_class: total_increasing`, for
  integration time and perhaps the light count.
- **Watch out for:**
  - A N.I.N.A. restart mid-session drops the value, since the session keeps
    only the current process's frames. `total_increasing` treats a drop as a
    new cycle; `total` with a fixed `last_reset` would book it as negative
    growth.
  - Changing the state class of the existing sensor raises a recorder
    statistics repair, which is why this proposes a new one.
  - Lifetime totals per target belong to the Target Scheduler database.

### The night in the logbook

- **Problem:** there is no readable account of what happened overnight: target
  changes, flips, autofocus results, safety changes, guider starts and stops,
  the sequence finishing, errors.
- **Proposal:** a `logbook.py` that describes a chosen subset of the `nina_*`
  bus events.
- **Watch out for:** a night raises hundreds of events, each fired twice (as
  `nina_<name>` and as `nina_event`), so describe a curated subset only.
  `TS-TARGETSTART` fires once per exposure; use `TS-NEWTARGETSTART`. Events
  missed while the socket was down aren't fired again.

### Surface sequence-authored messages and the log

- **Problem:** only some failures reach an entity. Plate solve errors are
  matched for ASTAP only. Messages a sequence sends on purpose ("flats done",
  "target complete") are lost.
- **Proposal:**
  - Keep the bare-string `Response` that a "Send WebSocket Event" instruction
    sends, which `_dispatch` in `api/v2/events.py` drops, and expose it as an
    event entity.
  - `SEQUENCE-ENTITY-FAILED` (from the "Send Error to WebSocket" trigger)
    reaches the bus as `nina_sequence_entity_failed`, with its nested fields
    dropped, but no entity. Surface it on `event.<instance>_error` or a new
    `event.<instance>_sequence_message`.
  - Add a response-only `get_log` action over
    `/application/logs?lineCount=&level=` (*new request*). Other alerts could
    then quote the last few errors.
- **Watch out for:**
  - Neither socket shape has a captured fixture, so capture both on the
    simulator first.
  - They exist only if the operator adds the instruction or trigger to their
    sequence, so document that.
  - Log timestamps are naive local time.
  - The log can hold paths and user names: return it from the action and never
    keep it in state, and redact log fixtures.

---

## Notifications and controls

### Rich phone notifications

- **Problem:** the first sub of a new target is the moment to check framing,
  rotation and focus, and a stall alert is more useful with Stop and Park
  buttons on it.
- **Proposal:** a blueprint that, on `TS-NEWTARGETSTART` or a change of
  `sequence_target`, waits for the next light and sends its thumbnail with HFR
  and stars. Add actionable buttons to the stall and early-end alerts.
- **Watch out for:**
  - `TS-TARGETSTART` fires once per exposure; triggering on it sends a
    thumbnail for every sub.
  - The blueprints notify with `notify.send_message`, which takes only a
    message and a title. Images and actions need an optional mobile-app notify
    service input.
  - For the image, use the `image.<instance>_last_frame` entity picture, which
    Home Assistant serves through its own authenticated proxy.
  - `authenticationRequired` on a destructive button works on iOS only.

### Skip an instruction and choose a sequence

- **Problem:** a hung instruction, such as a centring loop that never ends or a
  long wait, can only be cleared by stopping the whole night, and
  `sequence_stop` doesn't run the sequence's own End block (*verify*). And
  `sequence_name` is typed by hand.
- **Proposal:** a `sequence_skip` action over
  `/sequence/skip?type=CurrentItems|ToEnd|ToImaging`, and a `select` of the
  sequences from `/sequence/list-available`, polled on the slow tier. Both are
  *new requests*. `type=ToEnd` is probably the graceful end of the night,
  running the End block where a stop does not (*verify*).
- **Watch out for:** work out what skip does on the simulator only. It is
  destructive, so the card asks for confirmation. Skip answers when N.I.N.A.
  accepts it (a refusal arrives as a 409 in the body), so confirm the outcome
  from the next poll, never from the response.

### Stop-motion actions

- **Problem:** there is no way to halt a mount slew heading somewhere wrong.
- **Proposal:** actions over `/equipment/mount/slew/stop`,
  `/equipment/dome/stop`, `/equipment/focuser/stop-move` and
  `/equipment/rotator/stop-move` (*new requests*), with a confirmation on the
  card.
- **Watch out for:**
  - Halting a slew that the sequence started fails that instruction. Test on
    the simulator first.
  - Stopping a roll-off roof leaves it part-open, the opposite of safe; keep
    the dome stop out of automations.
  - Each answers on acceptance, so confirm from the next poll.

---

## Dashboard extras

### N.I.N.A. screenshot on demand

- **Problem:** seeing what N.I.N.A. shows, such as a modal dialog or an error
  pop-up, takes remote desktop.
- **Proposal:** an `image` entity and a card button over
  `/application/screenshot` (*new request*; it can resize and set JPEG
  quality), fetched only on demand.
- **Watch out for:**
  - The spec says only "Takes a screenshot". Whether it captures the whole
    desktop or only N.I.N.A.'s window is unknown (*verify*); if only the
    window, a separate dialog or Windows error box, the very thing this is
    for, may be missed.
  - A desktop capture may show private content.
  - What it returns while minimised or locked is unknown.
  - Mind the bandwidth on a hosted link.
  - A card can't reach N.I.N.A. directly, since it serves plain HTTP; fetch
    through a `views.py`-style proxy or the `image` entity.

### Target Scheduler context on the target

- **Problem:** the dashboard could show "NGC 281 until 03:22 (project X,
  rotation 90°)".
- **Proposal:** attributes on `sequence_target` from `TS-NEWTARGETSTART`'s
  `ProjectName`, `TargetEndTime` and `Rotation`, which reach the bus but are
  not mapped.
- **Watch out for:** `TargetEndTime` is naive, probably local time like
  `WaitEndTime`, unlike the event's naive-UTC `Time` (*verify*); add it to the
  mapper's timezone handling. Plain sequences have none of these.

### Guide graph card

- **Problem:** telling wind gusts from periodic error or cloud needs the RA and
  Dec trace, not one RMS number.
- **Proposal:** a card over `/equipment/guider/graph` (*new request*; the
  `GuideStepsHistory` type is already in `api/v2/schema.py`), fetched only while
  the card is open. Peak RA and Dec entities from `PeakRA` and `PeakDec` under
  `Guider.RMSError`, which `/equipment/info` already returns; use the
  arcsecond values, not the pixel ones.
- **Watch out for:** the payload grows with N.I.N.A.'s graph history setting,
  so capture a fixture first. The card needs a `views.py`-style proxy or a
  websocket command, since it can't reach N.I.N.A. directly.

### Sun and twilight at the site

- **Problem:** the stall alert works out the sun at the rig in Jinja, and each
  blueprint proposed here would have to repeat it.
- **Proposal:** sun elevation and astronomical dusk and dawn sensors from the
  site's latitude and longitude, using `astral`. It would simplify the
  early-end, put-to-bed and morning-report blueprints, and the stall alert.
- **Watch out for:**
  - `astral` ships with Home Assistant but isn't in the `test` dependency
    group, and the manifest lists no requirements. Keep the computation in a
    Home Assistant-side module, or add `astral` to the test group.
  - Throttle the elevation sensor rather than updating it every poll.
  - The gain is small when Home Assistant is near the rig, and larger for a rig
    hosted far away.

### Horizon and moon on the sky map

- **Proposal:** draw the profile's custom horizon from `/profile/horizon`, and
  show the moon's separation from the mount's position and its phase from
  `/astro-util/moon-separation` (both *new requests*).
- **Watch out for:** the moon route returns a separation and a phase, not the
  moon's position, so this is a readout rather than a moon drawn on the map. It
  takes `ra` in degrees, while `MountModel.right_ascension` is in hours; check
  which epoch it expects, since the mount reports JNOW. Display only: Target
  Scheduler already enforces moon avoidance.

### Fields fetched but unused

Each is a small entity or attribute, of low value on its own:

- HFR in arcseconds: `derive.hfr_arcsec` and `image_scale_arcsec_per_px` are
  written and tested but nothing uses them. Blocked on #173.
- The mount's `Slewing`, which isn't in `MountModel`; it would allow a
  stuck-slewing check.
- The camera's `LastDownloadTime`, not mapped; a rising download time points to
  USB or cable trouble.
- Camera `Battery` (DSLRs) and focuser `TempComp`, both mapped with no entity.

---

## Not planned

Ideas that come up and the reason each is left out. Reopen one with an issue if
the reason stops holding.

- **Imaging-PC disk, CPU and memory:** the Advanced API doesn't expose them.
  Use System Bridge or Glances. A full disk shows up as a stall anyway.
- **A dither action:** there is no route for it, and `GUIDER-DITHER` fires even
  for a skipped dither.
- **Go or no-go from weather readings:** forecast sources report clear skies
  under cloud. That decision belongs to the safety monitor.
- **A Home Assistant `weather` entity:** it needs a condition and a forecast,
  and would add nothing over the sensors and the weather card.
- **Target Scheduler project completion:** it lives in the Target Scheduler
  database, which no route exposes. `/sequence/state` describes the running
  sequence, not project progress, and is large and grows every night.
- **A manual meridian flip:** `/equipment/mount/flip` raises no before or after
  events, which blinds every flip entity, and it competes with the sequence's
  own trigger.
- **An on-demand plate solve:** a blocking call that loads the imaging PC in
  the middle of a night, for little monitoring value.
- **Editing or switching profiles remotely:** too easy to break a night from a
  phone.
- **Starting flats from Home Assistant:** sequences and Target Scheduler run
  flats, and the `/flats/*` routes would tangle with the flat panel interlocks.
- **A notification for every frame:** noise. Alert on degrading frames or a new
  target instead.
- **Update entities for N.I.N.A. or its plugins:** N.I.N.A.'s plugin manager
  handles those.
- **A moon phase entity:** Home Assistant's moon integration covers it.
- **A custom timeline card:** a built-in history-graph of `imaging`,
  `sequence_waiting`, `safety_monitor_unsafe` and `mount_meridian_flip`
  already draws one.
- **Target altitude or horizon alerts:** the sequencer and Target Scheduler
  enforce those limits, so an alert duplicates them and adds false alarms near
  the horizon.

# Stall Alert Blueprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `imaging_stall_alert.yaml`, a sixth blueprint that notifies when
the rig has stopped producing frames *for a bad reason*, and clears the alert
when it resumes.

**Architecture:** Three independent arms — unreachable, parked, quiet — feeding
one alert lifecycle. The quiet arm is gated on the states that explain a
legitimate silence, so hours of waiting never alarm. Notify only: no abort, no
park, no sequence stop.

**Spec:** [`docs/v2.0-design.md`](../../v2.0-design.md) §6.2 (running vs
imaging), §5.2.1 (availability), §3.4 (which events are proven).

**Prerequisite:** PR #54 (`scheduler_waiting`, `wait_ends_at`, `last_frame_at`)
merged to `v2`.

## Why this is not a README snippet

The obvious rule — "no frame for 30 minutes" — fires on this repo's own
captures:

| Measured | Where | Consequence |
|---|---|---|
| **31.5 min** between consecutive lights | `image_history_session.json`, a normal night | a 30-minute rule alarms on a healthy rig |
| **116 min** with no frame at all | dawn night: unsafe 04:26, safety loop to dawn, **zero `TS-WAITSTART`** | `scheduler_waiting` is `off` throughout; only a safety gate suppresses it |
| **11.6 min** from a wait ending to the first frame | `imaging_guiding`: wait ends 20:51:48, first save 21:03:24 | slew, rotate, filter, settle — a wait ending is not a frame arriving |
| **12:11:42** `CalculatedWaitDuration` | `dawn_sequence_complete.json`, a `Wait for Time` container | a daytime wait with `running` true and `scheduler_waiting` false |
| `Index out of range` | `scheduler_waiting_image_history_latest.json` and two others | `last_frame_at` is `unknown` before the night's first frame |

Nothing in the N.I.N.A. ecosystem covers this. Ground Station reports
*instruction failures* and explicitly has no time-based trigger, and its
triggers run before instructions, so it cannot report a failure in the last
one. It also runs inside N.I.N.A.: if N.I.N.A. hangs or the PC wedges, nothing
is sent. Watching from Home Assistant is what makes the dead cases observable.

## Global Constraints

- **Notify only.** No `sequence_stop`, no park, no dome. A false positive must
  cost a phone buzz, never a night.
- **Every arm keys on ENTITIES, never on bus events.** Event `Time` fields are
  inconsistently offset — `TS-WAITSTART` arrives naive while most others carry
  `-05:00` — and the entities are already normalised.
- **`notify.send_message` against a notify entity**, never `notify.<service>`
  built from text: `ServiceNotFound` is not suppressed by `continue_on_error`.
  `continue_on_error: true` on every notify.
- **Safety is gated as "not `on`", never "is `off`".** `_unsafe()` returns
  `None` when the monitor is absent, so the entity reads `unknown` — and
  `state: "off"` would mute the alarm exactly when the safety monitor has
  dropped out.
- **A template trigger fires once, on `false → true`.** Any gate that is a
  *clock* must be inside the trigger or evaluated on a repeating trigger;
  otherwise the first evaluation loses the stall for the rest of the night.
- **`last_changed` resets on every Home Assistant restart.** The settle gate is
  therefore mute for `settle_minutes` after a restart. That errs toward silence,
  which is the right direction, and is stated in the input description.
- Conventions from the five shipped blueprints: the rig-match template
  condition, `max_exceeded: silent`, `homeassistant.min_version: "2024.10.0"`,
  `author: dgivens`, `source_url`, `icon:` on input sections, notify default
  `[]`, and `trigger_variables` for anything a trigger template reads.

---

## Task S1: The blueprint

**Files:**
- Create: `blueprints/automation/nina_astrophotography/imaging_stall_alert.yaml`
- Test: `tests/ha/test_blueprints.py` (extend `REQUIRED` and the full-input map)

**Interfaces:**
- Consumes: `binary_sensor.<rig>_{sequencer_running,imaging,scheduler_waiting,safety_monitor_unsafe,mount_at_park}`,
  `sensor.<rig>_{last_frame_at,camera_state,sequence_target,guider_status,mount_time_to_meridian_flip,camera_temperature,camera_cooler_power}`.
- Produces: one automation; a persistent notification plus notify messages.

### The three arms

| Arm | Trigger | Gates | Rationale |
|---|---|---|---|
| **Unreachable** | `sequencer_running` → `unavailable`, `for: "00:02:00"` | none | N.I.N.A. down, PC rebooted, network gone. Every entity goes `unavailable`, so no other arm can fire — the failure this design most needs and the one a naive template misses entirely. |
| **Parked** | `mount_at_park` → `on` | sequencer running | A mount that parked itself while the sequencer runs is a stall with no ambiguity and no timer. |
| **Quiet** | `time_pattern` `/1` | all five below | The frames stopped. |

**Quiet-arm gates**, all required:

1. `sequencer_running` is `on` — a stopped sequencer is not a stall.
2. `scheduler_waiting` is `off` — a target-window wait is hours of nothing.
3. `safety_unsafe` is not `on` — the 116-minute case. `weather_abort` owns it.
4. `now() - scheduler_waiting.last_changed > settle_minutes` — the 11.6 min of
   slew, rotation, filter change and settle after a wait ends.
5. `night_only` is off, or the sun is below the horizon — the twelve-hour
   daytime `Wait for Time`. **Optional and user-facing**: solar imagers run in
   daylight and must be able to turn it off.

**Quiet-arm threshold**, either of:

- `imaging` has been `off` for `imaging_quiet_minutes` (default 20) — the fast
  arm. Catches an Idle camera, a plate-solve retry loop, a hung autofocus.
  Measured autofocus runs are 4.0–4.6 min, so 20 clears them comfortably.
- `last_frame_at` older than `longest_exposure_seconds + grace_minutes`
  (default 600 s + 30 min = 40 min), **or** `last_frame_at` is unavailable while
  the sequencer has been running longer than that — "the rig never took a first
  frame tonight" is a stall, and `has_value()` alone would make the blueprint
  mute for it.

40 min, not 35: the observed worst healthy gap is 31.5 min, and 35 leaves 3.5
minutes of headroom. Overhead (dither, download, filter change, autofocus,
flip) is fixed cost and does not scale with exposure, so the grace is **added**,
never multiplied. `Date` is the frame's *save* time, so the clock already
starts one exposure behind — say so in the input description.

### Alert lifecycle

`mode: single` with `max_exceeded: silent`. `mode: restart` would break the
steps below: the quiet arm's `time_pattern /1` would kill the waiting run every
60 s and re-notify, and it would never escalate or clear. The run already ends
when a frame lands, through `wait_for_trigger` on `last_frame_at`.

1. Raise: `persistent_notification.create` with a stable `notification_id`, plus
   `notify.send_message`.
2. `wait_for_trigger`: `last_frame_at` changes (a frame landed), or
   `sequencer_running` goes `off` (the night ended, or someone stopped it).
   `timeout: escalate_minutes` (default 60).
3. On timeout: renotify, up to `escalations` times (default 2). After that the
   run does **not** stop. It keeps waiting without reminders, so the cleared
   message still arrives when frames resume. If the run ended, the next tick
   would raise a duplicate alert, and nothing would be left to dismiss the
   notification. A stall still stalled at 05:00 is a dawn problem, not a 3am
   one.
4. On resume: dismiss the notification and send the cleared message.
   **Never send "cleared" if nothing was raised.**
5. `SEQUENCE-FINISHED` fires on a **manual stop as well as end of night**, so
   the cleared message says which was observed rather than claiming the night
   completed.

### The message

Triage from bed, without opening Home Assistant. Rig name; minutes quiet; the
last frame's target and filter; `camera_state` (Idle vs Exposing vs Downloading
is the single most diagnostic field); `guider_status` and RMS; `mount_at_park` /
`at_home`; camera temperature and cooler power (a warmed camera means a
shutdown already ran — do not send anyone to the roof); `autofocus_failed`; the
newest `event.<rig>_error`; `safety_monitor_connected`.

`mount_time_to_meridian_flip` reading `unknown` is itself a diagnosis: the `24`
sentinel means tracking is off.

Include **`MOUNT-HOMED` count in the last hour** if it can be had cheaply. The
dawn failure's signature was homing every ~80 s for two hours — 80 events — and
one line would have named it instantly.

**Steps:**
- [ ] Write the blueprint with the three arms, five gates and two thresholds
- [ ] `night_only` defaults **on**, with a description naming solar imaging as
      the reason to turn it off
- [ ] Add both input sets to `tests/ha/test_blueprints.py`
- [ ] Verify the unit blueprint checks still pass (no hardcoded entity ids)

## Task S2: Documentation

**Files:**
- `README.md` — the blueprint list and the "Knowing the rig is working" section
- `docs/2.0-renames.md` — a blueprint is a user-facing artifact

**Steps:**
- [ ] README: replace "a blueprint shipping that is the next piece of work" with
      what the blueprint does, its defaults, and the three arms
- [ ] State the two suppressions a user must know: an unsafe rig does not alert
      (that is `weather_abort`'s job), and `night_only` must be turned off for
      solar work
- [ ] Note that guiding has its own blueprint and this one does not duplicate it

## Task S3: Review gate

**Steps:**
- [ ] `code-reviewer`, `code-simplifier` and `astro-imaging-engineer` on the PR
- [ ] Both suites green; blueprint instantiates on defaults AND full inputs

---

## Known limits, recorded rather than fixed

- **An HA restart during an open alert loses both the alert and its "cleared"
  message.**
  `wait_for_trigger` does not survive a restart, and neither do persistent
  notifications, which live in memory. The notification and the automatic
  clear are both lost. The phone notification already sent is what remains.
- **The settle gate is mute for `settle_minutes` after an HA restart**, because
  `last_changed` resets. Errs toward silence.
- **A safety loop is suppressed entirely.** If conditions are unsafe the rig is
  behaving correctly, and `weather_abort` is the blueprint that speaks.
- **Not covered: a rig that is imaging but producing garbage.** Star count, HFR
  and RMS entities exist; a quality alarm is a separate blueprint and a separate
  set of thresholds.

## Follow-ups this plan does not do

1. `sensor.<rig>_last_light_at`, or `image_type` as an attribute on
   `last_frame_at` — dawn flats keep `last_frame_at` fresh while lights have
   stopped, so it cannot answer "am I still collecting on target".
2. An equipment-connected rollup binary sensor. The dawn night shows
   `CAMERA-DISCONNECTED` and `GUIDER-DISCONNECTED` mid-night with nothing
   aggregating them, so a dropped guider currently looks like a stall.
3. The `MOUNT-HOMED` count in the last hour, which §The message asked for if
   it came cheap. It was left out because no entity exposes it without a
   `history_stats` or recorder query. The message reports `mount_at_home`
   state instead.

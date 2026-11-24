/**
 * Rig states for `nina-observatory-card`, composed out of the committed dump.
 *
 * `site_configured` has the camera, mount, focuser, guider and rotator up, a
 * tracking mount two hours from its flip, and no session — it is dumped on a
 * later day than its night. `site_configured_us_customary` is the same rig on a US
 * customary instance, where Home Assistant shows every temperature in °F.
 * `equipment_disconnected` has every driver down under a live hub, and
 * `nina_unreachable` is `site_configured` once N.I.N.A. stops answering: every
 * entity unavailable, the hub's included.
 *
 * The `simulator_dome_*` dumps are the test VM's rig, the one with a dome: an
 * OmniSim dome parked and closed, or open and following an unparked mount.
 *
 * `dawn_flats` is the one capture of the reference rig's flat panel: a 0–4096
 * panel with its cover closed and its light off, after the flats.
 *
 * `scheduler_waiting` and `wait_for_time` are the two captured waits that name
 * their end, each dumped twenty and nine minutes before it.
 * `simulator_altitude_wait` is the test VM's Wait if Sun Altitude, dumped 24
 * minutes before the minute N.I.N.A. expects it to end.
 */

import { flipScenarios, linkScenarios, rig } from "../hass.mjs";

const UP = "site_configured";
const FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip";
const DOME = "simulator_dome_parked";
const PARK = "binary_sensor.n_i_n_a_mount_at_park";
const SHUTTER = "sensor.n_i_n_a_dome_shutter_status";
const UNSAFE = "binary_sensor.n_i_n_a_safety_monitor_unsafe";
const ROTATOR = "number.n_i_n_a_rotator_position";
const SYNCED = "binary_sensor.n_i_n_a_rotator_synced";
const GUIDER = "switch.n_i_n_a_guider";
const CAMERA = "sensor.n_i_n_a_camera_state";
const COOLER = "switch.n_i_n_a_camera_cooler";
const FLATS = "dawn_flats";
const COVER_STATE = "sensor.n_i_n_a_flat_panel_cover_state";
const COVER = "switch.n_i_n_a_flat_panel_cover";
const FLAT_LIGHT = "light.n_i_n_a_flat_panel_light";
const FLAT_LEVEL = "number.n_i_n_a_flat_panel_brightness";
const BEHIND_COVER = "binary_sensor.n_i_n_a_flat_panel_light_frames_behind_closed_cover";
const REACHABLE = "binary_sensor.n_i_n_a_reachable";
const SEQUENCER = "binary_sensor.n_i_n_a_sequencer_running";
const IMAGE_COUNT = "sensor.n_i_n_a_session_image_count";
const WAITING = "binary_sensor.n_i_n_a_sequence_waiting";
const TARGET = "sensor.n_i_n_a_sequence_target";

// The cover's sensor and switch read the same cover, so a scenario moves both.
const cover = (dump, sensor, sw) =>
  rig(dump, FLATS).override(COVER_STATE, sensor).override(COVER, sw);
// Part-way, every row last changed `ago` ms before now. N.I.N.A. reports the
// travel, but no capture caught it.
const partWayFor = (dump, ago) =>
  cover(dump, "NeitherOpenNorClosed", "unknown").changedAt(new Date(Date.now() - ago));

// The flats rig `r` with its panel's light on at half its range.
const lit = (dump, r) => r
  .override(FLAT_LIGHT, "on", {
    ...dump[FLATS].states[FLAT_LIGHT].attributes, brightness: 128, color_mode: "brightness",
  })
  .override(FLAT_LEVEL, "2048.0");

// The panel's driver down under a live hub. The cover's state stays up only
// while it holds a fault the panel reported before it went: `held`.
const panelDown = (dump, held = "unavailable") => {
  const r = rig(dump, FLATS).override(COVER_STATE, held);
  for (const id of [COVER, FLAT_LIGHT, FLAT_LEVEL]) r.override(id, "unavailable");
  return r;
};

// What the cover's buttons read at this step.
const coverButtons = (log, card) => log.push(`buttons ${
  card.shadowRoot.innerHTML.match(/<button[^>]*id="btn-cover[^"]*"[^>]*>[^<]*/g).join(" | ")}`);
// Presses a cover button, logging what the card asks and confirming it.
const pressCover = (log, card, id) => {
  window.confirm = (ask) => {
    log.push(`confirm ${ask}`);
    return true;
  };
  card.shadowRoot.getElementById(id).click();
  coverButtons(log, card);
};

// The captured wait on `rigState`, moved in time so that now is `into` ms
// after the read that first showed it, as it was when dumped at 0. `changes`
// are attributes a scenario replaces, for the waits no capture holds.
const waiting = (dump, rigState, into = 0, changes = {}) => {
  const row = dump[rigState].states[WAITING];
  const shift = Date.now() - into - Date.parse(row.attributes.started_at);
  const moved = (at) => at && new Date(Date.parse(at) + shift).toISOString();
  return rig(dump, rigState).override(WAITING, "on", {
    ...row.attributes,
    started_at: moved(row.attributes.started_at),
    ends_at: moved(row.attributes.ends_at),
    ...changes,
  });
};

// No `draw` hook: the card has no canvas.

export const scenarios = {
  // Every id resolved, and the equipment up.
  station: { hass: (dump) => rig(dump, UP).build() },

  // A night with frames, which is the only state where Last image has
  // readings to print.
  session: { hass: (dump) => rig(dump, "dawn_flats").build() },

  // The same rig with no registry, which is the prefix fallback.
  templated: { hass: (dump) => rig(dump, UP).unresolvable().build() },

  // The camera and focuser temperatures and the setpoint in °F, each labelled
  // with the unit Home Assistant converted it to.
  us_customary: { hass: (dump) => rig(dump, "site_configured_us_customary").build() },

  // The time to the flip shown in hours, which must render what `station` does.
  flip_in_hours: { hass: (dump) => rig(dump, UP).displayedIn(FLIP, "h", 1 / 60).build() },

  // Twenty minutes to the latest flip of a profile whose window is ten minutes
  // wide: the banner warns of a flip in 10–20 min. The reading is invented — the
  // corpus never caught a mount this close to its flip.
  flip_soon: { hass: (dump) => rig(dump, UP).override(FLIP, 20).build() },

  // Inside the window: the slew is due at the next item boundary.
  flip_due: { hass: (dump) => rig(dump, UP).override(FLIP, 6).build() },

  // N.I.N.A. waiting to flip, then slewing: the banner and the mount's metric
  // say which, where the countdown alone would show nothing.
  ...flipScenarios(),

  // The mechanical position disabled: the sky angle alone.
  rotator_sky_only: {
    hass: (dump) => rig(dump, UP).without("rotator_mechanical_position").build(),
  },

  // Unsynced: the sky angle reads —.
  rotator_unsynced: { hass: (dump) => rig(dump, UP).override(SYNCED, "off").build() },

  // A rotator seen, then dropped: no chip or section.
  rotator_down: { hass: (dump) => rig(dump, UP).override(ROTATOR, "unavailable").build() },

  // Every driver down, N.I.N.A. answering. Must not read as a lost link.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },

  // `station` with the guider and cooler switches disabled: the chips stay
  // green, the cooler pair disables all the same, and the guider pair reads
  // the guider's status instead.
  switches_disabled: { hass: (dump) => rig(dump, UP).without("guider", "camera_cooler").build() },

  // `station` under a prefix that matches no entity: everything resolves but
  // the guider switch, whose pair reads the guider's status instead.
  foreign_prefix: { hass: (dump) => rig(dump, UP).build(), config: { prefix: "observatory" } },

  // The lost link: the banner in place of the session and the chips gone.
  // `lost` puts the time the link went down in the banner.
  ...linkScenarios(),

  // `unreachable` with the sequencer's row disabled.
  unreachable_without_sequencer: {
    hass: (dump) => rig(dump, "nina_unreachable").without("sequencer_running").build(),
  },

  // A Dome chip and Open Dome.
  dome_closed: { hass: (dump) => rig(dump, DOME).build() },

  // Close Dome, which warns that the mount is not confirmed parked.
  dome_open: { hass: (dump) => rig(dump, "simulator_dome_following").build() },

  // Close Dome while the shutter is still opening. Seen on the wire, but over
  // between two of N.I.N.A.'s refreshes too often to capture.
  dome_opening: { hass: (dump) => rig(dump, DOME).override(SHUTTER, "opening").build() },

  // A red chip, and Close Dome to retry. The simulator cannot fail.
  dome_shutter_error: { hass: (dump) => rig(dump, DOME).override(SHUTTER, "error").build() },

  // Open Dome disabled. The simulator's safety monitor reads safe throughout.
  dome_unsafe: { hass: (dump) => rig(dump, DOME).override(UNSAFE, "on").build() },

  // The monitor not reporting is not a safe reading: Open Dome disabled.
  dome_safety_unknown: {
    hass: (dump) => rig(dump, DOME).override(UNSAFE, "unavailable").build(),
  },

  // The dome's driver down under a live hub: no chip and no dome button.
  dome_driver_down: {
    hass: (dump) => {
      const r = rig(dump, DOME);
      for (const id of [SHUTTER, "button.n_i_n_a_dome_open", "button.n_i_n_a_dome_close"]) {
        r.override(id, "unavailable");
      }
      return r.build();
    },
  },

  // A connected dome whose shutter reads nothing: still a dome, and Close
  // stays, since a shutter not known closed may be open.
  dome_shutter_unknown: { hass: (dump) => rig(dump, DOME).override(SHUTTER, "unknown").build() },

  // A driver with no shutter control: the chip and no button.
  dome_without_shutter_control: {
    hass: (dump) => rig(dump, DOME).without("dome_open", "dome_close").build(),
  },

  // The lost link over a dome: Close Dome stays, and the banner says to check.
  dome_unreachable: { hass: (dump) => rig(dump, "simulator_dome_unreachable").build() },

  // Lost after the mount last read parked: Close Dome must still warn that the
  // mount is not confirmed parked. No capture holds a dome rig with its mount
  // parked, so the park reading is overridden; the rest is the simulator's.
  dome_lost_parked: {
    hass: (dump) => rig(dump, DOME)
      .override(PARK, "on", { ...dump[DOME].states[PARK].attributes })
      .build(),
    after: (dump) => [rig(dump, "simulator_dome_unreachable").build()],
  },

  // A Flat Panel chip and section, and Open Flat Cover.
  flat_panel: { hass: (dump) => rig(dump, FLATS).build() },

  // Close Flat Cover. No capture holds the cover open.
  flat_panel_open: { hass: (dump) => cover(dump, "Open", "on").build() },

  // Lit at half its range, which the section's heading says, and Open Flat
  // Cover disabled, since the action refuses to open a lit panel. No capture
  // holds the light on; HA's 128 of 255 is the panel's 2048 of 4096.
  flat_panel_lit: { hass: (dump) => lit(dump, rig(dump, FLATS)).build() },
  // Stuck part-way and lit: Close stays live, Open is still refused.
  flat_panel_lit_stuck: { hass: (dump) => lit(dump, partWayFor(dump, 120_000)).build() },

  // A cover part-way for longer than the default 60 s it may travel is
  // stuck: both buttons, a red chip, and kept when the card folds.
  flat_panel_stuck: { hass: (dump) => partWayFor(dump, 120_000).build() },
  flat_panel_stuck_folded: {
    hass: (dump) => partWayFor(dump, 120_000).build(),
    folded: ["card"],
  },

  // Moving, on a card that never saw where it started: one disabled button.
  flat_panel_moving: { hass: (dump) => partWayFor(dump, 5_000).build() },

  // Open pressed on the closed cover: the button stays, disabled, while the
  // cover travels, and becomes Close once it is open.
  flat_panel_opening: {
    hass: (dump) => rig(dump, FLATS).build(),
    act: ({ dump, hand, log }) => ({
      pressed: (card) => pressCover(log, card, "btn-cover-open"),
      moving: (card) => {
        hand(cover(dump, "NeitherOpenNorClosed", "unknown")
          .changedAt(new Date(Date.now() - 5_000)).build());
        coverButtons(log, card);
      },
      open: (card) => {
        hand(cover(dump, "Open", "on").build());
        coverButtons(log, card);
      },
    }),
  },

  // Close pressed on an open cover with no sequence running: the plain
  // question, and no `force`.
  flat_panel_closing: {
    hass: (dump) => cover(dump, "Open", "on").build(),
    act: ({ log }) => ({ pressed: (card) => pressCover(log, card, "btn-cover-close") }),
  },
  // The same during a sequence, which the action refuses unless forced: the
  // card warns of blank lights, and the close it confirms is sent with
  // `force`. The rig's flats ran with no sequence, so it is switched on here.
  flat_panel_closing_running: {
    hass: (dump) => cover(dump, "Open", "on").override(SEQUENCER, "on").build(),
    act: ({ log }) => ({ pressed: (card) => pressCover(log, card, "btn-cover-close") }),
  },

  // Open pressed on a cover in error: Close stays, since the press changes no
  // reading while it waits. The rig's panel has not failed.
  flat_panel_cover_error_pressed: {
    hass: (dump) => cover(dump, "Error", "unknown").build(),
    act: ({ log }) => ({ pressed: (card) => pressCover(log, card, "btn-cover-open") }),
  },

  // Part-way for two minutes, but N.I.N.A. stopped answering 30 s into it:
  // the readings are as of then, so not stuck. No capture holds a panel
  // through an outage, so the link's moment is stamped by hand.
  flat_panel_cover_travelling_not_answering: {
    hass: (dump) => {
      const hass = partWayFor(dump, 120_000).override(REACHABLE, "off").build();
      hass.states[REACHABLE].last_changed = new Date(Date.now() - 90_000).toISOString();
      return hass;
    },
  },
  // Stuck, then N.I.N.A. lost with the Reachable sensor disabled, so nothing
  // says when it went quiet: the readings' age is unknown, so not stuck.
  flat_panel_cover_stuck_lost_unknown_since: {
    hass: (dump) => partWayFor(dump, 120_000).build(),
    after: (dump) => [
      rig(dump, FLATS).without("reachable")
        .override(SEQUENCER, "unavailable").override(IMAGE_COUNT, "unavailable").build(),
    ],
  },
  // A slower cover, given 180 s: two minutes part-way is still travel.
  flat_panel_cover_slow: {
    config: { cover_stuck_after: 180 },
    hass: (dump) => partWayFor(dump, 120_000).build(),
  },
  // A threshold past the editor's ten minutes is held to them: two minutes
  // part-way is no fault, and Infinity no render loop.
  flat_panel_cover_stuck_after_infinite: {
    config: { cover_stuck_after: Infinity },
    hass: (dump) => partWayFor(dump, 120_000).build(),
  },
  // One shorter than a read is held to the editor's 20 s: a cover 15 s
  // part-way is still moving.
  flat_panel_cover_stuck_after_too_short: {
    config: { cover_stuck_after: 5 },
    hass: (dump) => partWayFor(dump, 15_000).build(),
  },

  // A red chip and both buttons. The rig's panel has not failed.
  flat_panel_cover_error: { hass: (dump) => cover(dump, "Error", "unknown").build() },

  // A light saved behind the closed cover: a red chip, and the warning kept
  // when the card folds. The rig's newest frame after its close is a flat.
  flat_panel_lights_behind_cover: {
    hass: (dump) => rig(dump, FLATS).override(BEHIND_COVER, "on").build(),
  },
  flat_panel_lights_behind_cover_folded: {
    hass: (dump) => rig(dump, FLATS).override(BEHIND_COVER, "on").build(),
    folded: ["card"],
  },

  // The cover's diagnostic sensor disabled: the switch says closed.
  flat_panel_cover_state_disabled: {
    hass: (dump) => rig(dump, FLATS).without("flat_panel_cover_state").build(),
  },

  // A panel with a light and no cover: no cover reading and no button. The
  // rig's panel has a cover.
  flat_panel_light_only: {
    hass: (dump) => rig(dump, FLATS).override(COVER_STATE, "NotPresent")
      .without("flat_panel_cover").build(),
  },

  // A panel with a cover and no light: its brightness number reads Home
  // Assistant's default 0–100, which is no reading. The rig's panel has a light.
  flat_panel_cover_only: {
    hass: (dump) => rig(dump, FLATS)
      .override(FLAT_LIGHT, "unavailable")
      .override(FLAT_LEVEL, "0.0", {
        ...dump[FLATS].states[FLAT_LEVEL].attributes, min: 0, max: 100,
      })
      .build(),
  },

  // An on/off light, whose range ASCOM sets to 0–1: no brightness. The rig's
  // panel dims.
  flat_panel_switched_light: {
    hass: (dump) => rig(dump, FLATS)
      .override(FLAT_LEVEL, "0.0", {
        ...dump[FLATS].states[FLAT_LEVEL].attributes, min: 0, max: 1,
      })
      .build(),
  },

  // N.I.N.A. lost over a panel: its last readings, dimmed, and no cover
  // button, since only commands that end activity send without a link.
  flat_panel_lost: {
    hass: (dump) => rig(dump, DOME).build(),
    after: (dump) => [
      rig(dump, "simulator_dome_unreachable").changedAt(new Date(Date.now() - 45_000)).build(),
    ],
  },

  // The panel's driver down under a live hub: no chip, section or button.
  flat_panel_down: { hass: (dump) => panelDown(dump).build() },

  // A sequence that disconnects the panel once its cover is set, and then
  // takes a light behind the closed cover: the red chip says the panel is
  // down, and the warning stays when the card folds. No capture holds it.
  flat_panel_down_lights_behind_cover: {
    hass: (dump) => panelDown(dump).override(BEHIND_COVER, "on").build(),
  },
  flat_panel_down_lights_behind_cover_folded: {
    hass: (dump) => panelDown(dump).override(BEHIND_COVER, "on").build(),
    folded: ["card"],
  },
  // Disconnected part-way, which the cover's state holds: no chip while it
  // could still be travelling, and a red one once it is past
  // `cover_stuck_after`, timed from when it went part-way.
  flat_panel_down_held_part_way: {
    hass: (dump) => panelDown(dump, "NeitherOpenNorClosed")
      .changedAt(new Date(Date.now() - 5_000)).build(),
  },
  flat_panel_down_held_stuck: {
    hass: (dump) => panelDown(dump, "NeitherOpenNorClosed")
      .changedAt(new Date(Date.now() - 120_000)).build(),
  },
  // Disconnected in error, which the cover's state holds: a red chip, and the
  // fault kept when the card folds.
  flat_panel_down_held_error: { hass: (dump) => panelDown(dump, "Error").build() },
  flat_panel_down_held_error_folded: {
    hass: (dump) => panelDown(dump, "Error").build(),
    folded: ["card"],
  },

  // Folded to its header, which keeps `flip_soon`'s warning and, the session
  // running and the mount unparked, Stop and Park.
  folded: { hass: (dump) => rig(dump, UP).override(FLIP, 20).build(), folded: ["card"] },

  // Folded with nothing to warn of: the header, Stop and Park.
  folded_calm: { hass: (dump) => rig(dump, UP).build(), folded: ["card"] },

  // Folded while N.I.N.A. is not answering: the banner, and the fixed set of
  // commands that end activity.
  folded_not_answering: { ...linkScenarios().not_answering, folded: ["card"] },

  // Folded over `dome_shutter_error`: the fault line, and Close Dome.
  folded_shutter_error: {
    hass: (dump) => rig(dump, DOME).override(SHUTTER, "error").build(),
    folded: ["card"],
  },

  // Folded over `flat_panel_cover_error`: the fault line and the banner's cue.
  folded_cover_error: {
    hass: (dump) => cover(dump, "Error", "unknown").build(),
    folded: ["card"],
  },

  // Folded with the camera lost and the guider switched off mid-session, both
  // invented: no capture loses either during a run.
  folded_faults: {
    hass: (dump) =>
      rig(dump, UP).override(CAMERA, "unavailable").override(GUIDER, "off").build(),
    folded: ["card"],
  },

  // The same with the camera's row disabled rather than lost: no fault, since a
  // disabled entity says nothing about the camera.
  folded_camera_disabled: {
    hass: (dump) => rig(dump, UP).without("camera_state").build(),
    folded: ["card"],
  },

  // Sections folded to their headings: Controls keeps Stop and Park.
  folded_sections: {
    hass: (dump) => rig(dump, UP).build(),
    folded: ["mount", "rotator", "guiding", "controls"],
  },

  // Target Scheduler waiting for its next target: the header counts down to
  // 21:05, and the banner says what the sequence waits for.
  wait_scheduler: { hass: (dump) => waiting(dump, "scheduler_waiting").build() },

  // A wait mid-night, inside five minutes of the last frame, which keeps
  // `imaging` on, and with the target sensor naming the one before: the banner
  // says what the sequence waits for, and no target. Both rows are moved, the
  // target from `weather_frozen`, Target Scheduler's lost-lock capture.
  wait_after_frames: {
    hass: (dump) => waiting(dump, "scheduler_waiting")
      .override("binary_sensor.n_i_n_a_imaging", "on")
      .override(TARGET, dump.weather_frozen.states[TARGET].state).build(),
  },

  // The sequence's own Wait for Time.
  wait_for_time: { hass: (dump) => waiting(dump, "wait_for_time").build() },

  // A Wait for Time Span, invented on `wait_for_time`: no capture caught one
  // running. Placed from the read that first showed it, so the countdown is
  // the most it can have left.
  wait_time_span: {
    hass: (dump) => waiting(dump, "wait_for_time", 60_000, {
      kind: "time_span", ends_at: null, span_seconds: 300,
    }).build(),
  },

  // An altitude wait, whose end N.I.N.A. expects to the minute: the countdown
  // is in minutes, and marked approximate.
  wait_altitude: { hass: (dump) => waiting(dump, "simulator_altitude_wait").build() },

  // The same wait ten minutes past that minute, still running: N.I.N.A.'s
  // estimate is only that, so no countdown and no end.
  wait_altitude_overrun: {
    hass: (dump) => waiting(dump, "simulator_altitude_wait", 34 * 60_000).build(),
  },

  // An altitude wait N.I.N.A. places no end for (`--`), invented on the same
  // capture, whose own wait has one: no countdown.
  wait_altitude_unplaced: {
    hass: (dump) => waiting(dump, "simulator_altitude_wait", 0, { ends_at: null }).build(),
  },

  // Half a minute past Target Scheduler's end, before a read shows the wait
  // over: still waiting, with no countdown or end.
  wait_overdue: {
    hass: (dump) => waiting(dump, "scheduler_waiting", 20 * 60_000 + 71_000).build(),
  },

  // Folded: the header keeps the countdown.
  wait_folded: {
    hass: (dump) => waiting(dump, "scheduler_waiting").build(),
    folded: ["card"],
  },

  // Folded headings cueing what they hide: the cooler and guider switched off
  // mid-session, both invented, so Camera and Guiding warn.
  folded_cues: {
    hass: (dump) => rig(dump, UP).override(COOLER, "off").override(GUIDER, "off").build(),
    folded: ["camera", "guiding"],
  },
};

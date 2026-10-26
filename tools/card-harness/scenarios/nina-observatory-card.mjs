/**
 * Rig states for `nina-observatory-card`, composed out of the committed dump.
 *
 * `site_configured` has the camera, mount, focuser and guider up, a tracking
 * mount two hours from its flip, and no session — it is dumped on a later day
 * than its night. `site_configured_us_customary` is the same rig on a US
 * customary instance, where Home Assistant shows every temperature in °F.
 * `equipment_disconnected` has every driver down under a live hub, and
 * `nina_unreachable` is `site_configured` once N.I.N.A. stops answering: every
 * entity unavailable, the hub's included.
 *
 * The `simulator_dome_*` dumps are the test VM's rig, the one with a dome: an
 * OmniSim dome parked and closed, or open and following an unparked mount.
 */

import { linkScenarios, rig } from "../hass.mjs";

const UP = "site_configured";
const FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip";
const DOME = "simulator_dome_parked";
const PARK = "binary_sensor.n_i_n_a_mount_at_park";
const SHUTTER = "sensor.n_i_n_a_dome_shutter_status";
const UNSAFE = "binary_sensor.n_i_n_a_safety_monitor_unsafe";

// No `draw` hook: the card has no canvas.

export const scenarios = {
  // Every id resolved, and the equipment up.
  station: { hass: (dump) => rig(dump, UP).build() },

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
};

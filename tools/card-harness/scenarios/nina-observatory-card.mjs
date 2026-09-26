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
 */

import { rig } from "../hass.mjs";

const UP = "site_configured";
const FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip";

// No `draw` hook: the card has no canvas. `Date.now()` is pinned, so
// `changedAt` offsets are fixed.

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

  // Every driver down, N.I.N.A. answering. Must not read as a lost link.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },

  // `station` with the link lost and no live view to keep.
  unreachable: { hass: (dump) => rig(dump, "nina_unreachable").build() },

  // `station`, then one missed poll: must still draw `station`.
  blip: {
    hass: (dump) => rig(dump, UP).build(),
    after: (dump) => [
      rig(dump, "nina_unreachable").changedAt(new Date(Date.now() - 10_000)).build(),
    ],
  },

  // `station`, then a link down past the grace period.
  lost: {
    hass: (dump) => rig(dump, UP).build(),
    after: (dump) => [
      rig(dump, "nina_unreachable").changedAt(new Date(Date.now() - 45_000)).build(),
    ],
  },

  // `unreachable` with the sequencer's row disabled.
  unreachable_without_sequencer: {
    hass: (dump) => rig(dump, "nina_unreachable").without("sequencer_running").build(),
  },
};

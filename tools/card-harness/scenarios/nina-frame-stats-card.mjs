/**
 * Rig states for `nina-frame-stats-card`, composed out of the committed dump.
 *
 * `dawn_flats` is the one state dumped from inside its own night, so it is the
 * one with a session: 55 lights over four targets and five filters, the newest
 * 24 of them through S, and the dawn flats after them. That reaches every
 * branch the sparklines have — the target boundaries, a colour per filter, the
 * HFR trend, which needs ten frames in the newest filter — and the flats prove
 * the series skips calibration frames rather than charting them.
 *
 * `site_configured` holds no session, because it is dumped months after its
 * night. That is the empty card, and it is also what a new night shows before
 * its first light.
 */

import { rig } from "../hass.mjs";

const NIGHT = "dawn_flats";

// No `draw` hook: the three sparklines are painted from the frame the render
// queues, which the runner fires.

export const scenarios = {
  // Every id resolved, and the whole night charted.
  session: { hass: (dump) => rig(dump, NIGHT).build() },

  // The same rig with no registry, which is the prefix fallback. Its ops must
  // match `session`'s: the same entities, reached the other way. No `prefix:` —
  // the point is the id the card builds unaided.
  templated: { hass: (dump) => rig(dump, NIGHT).unresolvable().build() },

  // No lights in the session, so no charts: the waiting panel under the
  // header's session totals.
  waiting: { hass: (dump) => rig(dump, "site_configured").build() },
};

/**
 * Rig states for `nina-frame-stats-card`, composed out of the committed dump.
 *
 * `dawn_flats` is the one state dumped from inside its own night, so it is the
 * one with a session: 55 lights over four targets and five filters, the newest
 * 24 of them through S, and the dawn flats after them. That reaches the target
 * boundaries, a colour per filter and the HFR trend, which needs ten frames in
 * the newest filter; it reads Stable. The flats never reach `recent_lights`, so
 * the charts hold lights alone, and the header counts lights rather than the
 * 122 frames the count sensor reports.
 *
 * Not reached: a gap in a series or a frame with no filter, since no captured
 * light lacks a reading or a filter, nor a trend that reads Improving or
 * Degrading, since the newest ten S frames hold steady.
 *
 * `site_configured` holds no session, because it is dumped on a later day than
 * its night. That is the empty card, and it is also what a new night shows
 * before its first light.
 */

import { rig } from "../hass.mjs";

const NIGHT = "dawn_flats";
const EXPOSURE = "sensor.n_i_n_a_last_image_exposure";
const INTEGRATION = "sensor.n_i_n_a_session_integration_time";

// No `draw` hook: the three sparklines are painted from the frame the render
// queues, which the runner fires.

export const scenarios = {
  // Every id resolved, and the whole night charted.
  session: { hass: (dump) => rig(dump, NIGHT).build() },

  // The same rig with no registry, which is the prefix fallback. Its ops must
  // match `session`'s: the same entities, reached the other way. No `prefix:` —
  // the point is the id the card builds unaided.
  templated: { hass: (dump) => rig(dump, NIGHT).unresolvable().build() },

  // The exposure and the integration time shown in minutes, which must render
  // what `session` does.
  in_minutes: {
    hass: (dump) =>
      rig(dump, NIGHT)
        .displayedIn(EXPOSURE, "min", 1 / 60)
        .displayedIn(INTEGRATION, "min", 60)
        .build(),
  },

  // No lights in the session, so no charts: the waiting panel under the
  // header's session totals.
  waiting: { hass: (dump) => rig(dump, "site_configured").build() },
};

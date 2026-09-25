/**
 * Rig states for `nina-autofocus-card`, composed out of the committed dump.
 *
 * `site_configured` carries a whole autofocus report — nine swept positions,
 * three fits and two minima, one of which sits below the chart's floor — so the
 * chart, the legend and every chip render off captured data.
 * `equipment_disconnected` never observed a focuser at all.
 */

import { rig } from "../hass.mjs";

const UP = "site_configured";
const VERDICT = "binary_sensor.n_i_n_a_focuser_autofocus_failed";

// `override` replaces an attribute map wholesale, so a verdict is patched onto
// the rig's own rather than written from scratch: the profile's R² threshold
// then stays whatever the capture holds, instead of drifting away from the
// report charted beneath it at the next re-capture.
const verdict = (dump, changes) => ({
  ...dump[UP].states[VERDICT].attributes,
  ...changes,
});

export const scenarios = {
  // Every id resolved, and a run that passed.
  run: { hass: (dump) => rig(dump, UP).build() },

  // The same rig with no registry, which is the prefix fallback. Its ops must
  // match `run`'s: the same entities, reached the other way. No `prefix:` — the
  // point is the id the card builds unaided.
  templated: { hass: (dump) => rig(dump, UP).unresolvable().build() },

  // The banner, and the two branches only a rejected run reaches: the computed
  // position the focuser never took, and the restore back to where it started.
  //
  // The R² is invented, because no captured rig has produced a rejected run.
  // Only it is: the report charted underneath stays the real one, which scored
  // 0.971 against the same 0.7 threshold. The two disagree on purpose — this
  // scenario is for the banner and the stat boxes, not for a coherent rig.
  rejected: {
    hass: (dump) =>
      rig(dump, UP)
        .override(VERDICT, "on", verdict(dump, { r_squared: 0.42, reason: "rejected" }))
        .build(),
  },

  // A hung run wrote no report, so the curve below the banner is an earlier
  // run's — which is the one thing the banner has to say.
  //
  // Nothing but the reason is overridden, and that is the point: the verdict
  // carries the report's R² whether or not the run hung, so a hung rig really
  // does show "Passed · needs 0.70" under the banner. The focuser position
  // boxes describe the charted run too — a hung run can be left parked
  // mid-sweep, but the rig never produced one to capture.
  hung: {
    hass: (dump) =>
      rig(dump, UP).override(VERDICT, "on", verdict(dump, { reason: "hung" })).build(),
  },

  // The temperature box flagged, off the rig's own 0.2 °C of drift rather than
  // an invented reading: the threshold is what the scenario moves.
  drifted: {
    hass: (dump) => rig(dump, UP).build(),
    config: { temperature_delta: 0.1 },
  },

  // The same flag on a US customary instance, where Home Assistant shows both
  // temperatures in °F. The threshold is compared in °F with them, and every
  // label names that unit.
  drifted_us_customary: {
    hass: (dump) => rig(dump, "site_configured_us_customary").build(),
    config: { temperature_delta: 0.1 },
  },

  // No focuser ever observed, so nothing resolves and no id has a state —
  // the empty card, which is what a fresh install shows.
  no_run: { hass: (dump) => rig(dump, "equipment_disconnected").build() },
};

/**
 * Rig states for `nina-autofocus-card`, composed out of the committed dump.
 *
 * `site_configured` carries a whole autofocus report — nine swept positions,
 * three fits and two minima, one of which sits below the chart's floor — so the
 * chart, the legend and every chip render off captured data.
 * `equipment_disconnected` never observed a focuser at all.
 */

import { rig } from "../hass.mjs";

const draw = (card) => card._draw();

const VERDICT = "binary_sensor.n_i_n_a_focuser_autofocus_failed";

export const scenarios = {
  // Every id resolved, and a run that passed.
  run: { hass: (dump) => rig(dump, "site_configured").build(), draw },

  // The same rig with no registry, which is the prefix fallback. Its ops must
  // match `run`'s: the same entities, reached the other way.
  templated: {
    hass: (dump) => rig(dump, "site_configured").unresolvable().build(),
    config: { prefix: "n_i_n_a" },
    draw,
  },

  // The banner, and the two branches only a rejected run reaches: the computed
  // position the focuser never took, and the restore back to where it started.
  //
  // Overridden, because no captured rig has produced a rejected run — and the
  // verdict alone is, so the report charted underneath is the real one and
  // scored 0.97. The two numbers disagree on purpose: this scenario is for the
  // banner and the stat boxes, not for a coherent rig.
  rejected: {
    hass: (dump) =>
      rig(dump, "site_configured")
        .override(VERDICT, "on", {
          device_class: "problem",
          r_squared: 0.42,
          r_squared_threshold: 0.7,
          reason: "rejected",
        })
        .build(),
    draw,
  },

  // A run that hung wrote no report, so the curve below the banner belongs to
  // an earlier run — which is the one thing the banner has to say.
  hung: {
    hass: (dump) =>
      rig(dump, "site_configured")
        .override(VERDICT, "on", {
          device_class: "problem",
          r_squared: null,
          r_squared_threshold: 0.7,
          reason: "hung",
        })
        .build(),
    draw,
  },

  // The temperature box flagged, off the rig's own 0.2 °C of drift rather than
  // an invented reading: the threshold is what the scenario moves.
  drifted: {
    hass: (dump) => rig(dump, "site_configured").build(),
    config: { temperature_delta: 0.1 },
    draw,
  },

  // No focuser ever observed, so nothing resolves and no id has a state —
  // the empty card, which is what a fresh install shows.
  no_run: { hass: (dump) => rig(dump, "equipment_disconnected").build(), draw },
};

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
const RUN = "sensor.n_i_n_a_focuser_last_autofocus";
const POSITION = "sensor.n_i_n_a_focuser_autofocus_position";
const FOCUSER = "number.n_i_n_a_focuser_position";
const HFR = "sensor.n_i_n_a_focuser_autofocus_hfr";
const STARTING_HFR = "sensor.n_i_n_a_focuser_autofocus_starting_hfr";

// `override` replaces an attribute map wholesale, so a verdict is patched onto
// the rig's own: the profile's R² threshold stays whatever the capture holds,
// and in step with the report charted beneath it.
const verdict = (dump, changes) => ({
  ...dump[UP].states[VERDICT].attributes,
  ...changes,
});

// One of the run's captured minima, which a HYPERBOLIC focus point is not
// built from: the trend-line intersection, or the quadratic minimum built-in
// N.I.N.A. also reports.
const unused = (dump, name) => ({
  ...dump[UP].states[RUN].attributes.minima.find((minimum) => minimum.name === name),
  used: false,
});

// The fitting, R²s, verdict and focus point are invented: no capture holds a
// hyperbolic run. The focus point is the hyperbola's minimum, where a
// HYPERBOLIC run puts it, and the hyperbolic minimum sits on it too. The fits
// and the trend-line intersection are otherwise the captured ones, judged and
// used as that fitting would. Hocus Focus computes only the trend lines and the
// hyperbola on such a run, so it reports no quadratic minimum; the captured
// quadratic fit stays in `fits` all the same. `changes` lands on the run's
// attributes.
const hyperbolic = (dump, changes = {}) => {
  const run = dump[UP].states[RUN].attributes;
  return rig(dump, UP)
    .override(RUN, dump[UP].states[RUN].state, {
      ...run,
      fitting: "HYPERBOLIC",
      fitted_hfr: 1.8,
      fits: [
        ...run.fits.map((fit) => ({
          ...fit,
          judged: false,
          r_squared: fit.name === "RightTrend" ? 0 : fit.r_squared,
        })),
        { name: "Hyperbolic", equation: "y = 1.8 * cosh(asinh((x - 2336) / 40))",
          coefficients: null, r_squared: 0.988, judged: true },
      ],
      minima: [
        unused(dump, "TrendLineIntersection"),
        { name: "HyperbolicMinimum", position: 2336, value: 1.8, used: true },
      ],
      ...changes,
    })
    .override(POSITION, 2336)
    .override(VERDICT, "off", verdict(dump, { r_squared: 0.988, reason: null }));
};

// The same run as built-in N.I.N.A. reports it, which is all four minima in
// its own order, and "NINA" as both autofocuser and star detector. Derived:
// the hyperbolic minimum is the invented hyperbola's own vertex, and the
// gaussian maximum is a guess — built-in N.I.N.A. fits a gaussian to an HFR
// sweep too, and no capture shows where it lands; here, up the right arm. Its
// gaussian fit is left out of `fits` rather than given an invented equation.
const builtIn = (dump) => hyperbolic(dump, {
  autofocuser: "NINA",
  star_detector: "NINA",
  minima: [
    unused(dump, "TrendLineIntersection"),
    { name: "HyperbolicMinimum", position: 2336, value: 1.8, used: true },
    unused(dump, "QuadraticMinimum"),
    { name: "GaussianMaximum", position: 2475, value: 7.6, used: false },
  ],
});

// A contrast-detection run, which focuses at the gaussian maximum. No capture
// holds one, so it is derived from the captured sweep: each HFR becomes a
// contrast score of 1/HFR², which peaks where the stars are smallest, its
// spread carried through the same transform. As Hocus Focus does, it reports
// the trend-line intersection beside the gaussian maximum; both minima and the
// focus point are invented, and the trend lines' equations are left out rather
// than invented too. The HFR readings are unknown, as the integration
// publishes them for this method.
const contrast = (dump) => {
  const run = dump[UP].states[RUN].attributes;
  return rig(dump, UP)
    .override(RUN, dump[UP].states[RUN].state, {
      ...run,
      method: "CONTRASTDETECTION",
      fitting: "GAUSSIAN",
      fitted_hfr: null,
      curve: run.curve.map((point) => ({
        ...point,
        value: 1 / point.value ** 2,
        error: (2 * point.error) / point.value ** 3,
      })),
      fits: [
        { name: "Gaussian", equation: "y = 0.43 * exp(-(x - 2343)^2 / (2 * 38^2))",
          coefficients: null, r_squared: null, judged: false },
      ],
      minima: [
        { name: "TrendLineIntersection", position: 2344, value: 0.52, used: false },
        { name: "GaussianMaximum", position: 2343, value: 0.43, used: true },
      ],
    })
    .override(POSITION, 2343)
    .override(HFR, "unknown")
    .override(STARTING_HFR, "unknown")
    .override(VERDICT, "off", verdict(dump, { r_squared: null, reason: null }));
};

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

  // A run whose fit put focus outside the positions it measured, which fails
  // whatever its R² — so the captured 0.971 stays and passes. No capture holds
  // one: the focus point is moved a step past the sweep's 2492, and the
  // focuser is back at the run's 2352 start, where a discarded run leaves it.
  out_of_range: {
    hass: (dump) =>
      rig(dump, UP)
        .override(POSITION, 2527)
        .override(FOCUSER, 2352)
        .override(VERDICT, "on", verdict(dump, { reason: "out_of_range" }))
        .build(),
  },

  // A profile with N.I.N.A.'s R² check off, which the integration publishes as
  // a null threshold: no fit was judged, though the minima the focus point
  // came from were still used. Only the threshold changes; the captured run
  // passed, so the verdict stays off.
  r_squared_check_off: {
    hass: (dump) =>
      rig(dump, UP)
        .override(VERDICT, "off", verdict(dump, { r_squared_threshold: null }))
        .build(),
  },

  // No verdict entity at all, as when it is disabled: no threshold to read,
  // and nothing to say the check was off, so the fits keep their own `judged`.
  no_verdict: {
    hass: (dump) => rig(dump, UP).without("focuser_autofocus_failed").build(),
  },

  // A hyperbolic run that passed beside a trend line scoring 0.000.
  hyperbolic: { hass: (dump) => hyperbolic(dump).build() },

  // The same run with no starting HFR to compare against, which is the one
  // place the card prints the fitted HFR: the hyperbola's 1.80.
  hyperbolic_unmeasured_start: {
    hass: (dump) => hyperbolic(dump).without("focuser_autofocus_starting_hfr").build(),
  },

  // The four minima built-in N.I.N.A. reports whatever it fitted, only one of
  // which this fitting uses.
  hyperbolic_built_in: { hass: (dump) => builtIn(dump).build() },

  // A contrast-detection run, whose focus point is the gaussian maximum.
  contrast: { hass: (dump) => contrast(dump).build() },

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

  // The sequence's refocus trigger sets the threshold when the card has no
  // option. The capture's trigger reads 2 °C, so its threshold is moved to
  // flag the rig's own 0.2 °C of drift.
  trigger_drifted: {
    hass: (dump) =>
      rig(dump, UP)
        .override(VERDICT, "off", verdict(dump, { refocus_temperature_delta: 0.1 }))
        .build(),
  },

  // An explicit option outranks the trigger: 0.2 °C is past the trigger's 0.1
  // but short of the card's 0.3, so nothing is flagged.
  option_over_trigger: {
    hass: (dump) =>
      rig(dump, UP)
        .override(VERDICT, "off", verdict(dump, { refocus_temperature_delta: 0.1 }))
        .build(),
    config: { temperature_delta: 0.3 },
  },

  // The same flag on a US customary instance, where Home Assistant shows both
  // temperatures in °F: every label names that unit, and the threshold is
  // printed converted to it.
  drifted_us_customary: {
    hass: (dump) => rig(dump, "site_configured_us_customary").build(),
    config: { temperature_delta: 0.1 },
  },

  // The threshold is °C on any instance: 0.4 °F of drift is 0.2 °C, short of
  // 0.3, so nothing is flagged.
  held_us_customary: {
    hass: (dump) => rig(dump, "site_configured_us_customary").build(),
    config: { temperature_delta: 0.3 },
  },

  // No focuser ever observed, so nothing resolves and no id has a state —
  // the empty card, which is what a fresh install shows.
  no_run: { hass: (dump) => rig(dump, "equipment_disconnected").build() },
};

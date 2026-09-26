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
 * Every captured light has a filter from one wheel of single letters, so the
 * filter scenarios relabel that night rather than invent one.
 *
 * Not reached: a gap in a series, since no captured light lacks a reading,
 * nor a trend that reads Improving or Degrading, since the newest ten S frames
 * hold steady.
 *
 * `site_configured` holds no session, because it is dumped on a later day than
 * its night. That is the empty card, and it is also what a new night shows
 * before its first light.
 */

import { rig } from "../hass.mjs";

const NIGHT = "dawn_flats";
const EXPOSURE = "sensor.n_i_n_a_last_image_exposure";
const INTEGRATION = "sensor.n_i_n_a_session_integration_time";
const HFR = "sensor.n_i_n_a_last_image_hfr";
const AVG_HFR = "sensor.n_i_n_a_session_avg_hfr";
const FILTER = "sensor.n_i_n_a_last_image_filter";
const WHEEL = "select.n_i_n_a_filter_wheel_filter";

// The night with its filters renamed by `names`, captured name to new, where
// null takes the name away. Only labels change: each light, breakdown row and
// the last-filter reading keeps what the integration published, re-sorted by
// name as it sorts them, and a filter named null loses its row as a light
// with no filter has none. The wheel's slots and its current filter are
// renamed with them unless `wheel` is false; a slot whose lights lost their
// name keeps it.
function relabelled(dump, names, { wheel = true } = {}) {
  const states = dump[NIGHT].states;
  const label = (name) => (name in names ? names[name] : name);
  const slots = states[WHEEL].attributes.options.map(
    (slot) => (wheel ? label(slot) ?? slot : slot));
  const lights = states[HFR].attributes.recent_lights.map(
    (light) => ({ ...light, filter: label(light.filter) }));
  const byFilter = Object.fromEntries(
    Object.entries(states[AVG_HFR].attributes.by_filter)
      .map(([name, row]) => [label(name), row])
      .filter(([name]) => name !== null)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
  return rig(dump, NIGHT)
    .override(HFR, states[HFR].state, { ...states[HFR].attributes, recent_lights: lights })
    .override(AVG_HFR, states[AVG_HFR].state, { ...states[AVG_HFR].attributes, by_filter: byFilter })
    .override(FILTER, label(states[FILTER].state) ?? "unknown", states[FILTER].attributes)
    .override(WHEEL, wheel ? label(states[WHEEL].state) ?? states[WHEEL].state : states[WHEEL].state,
      { ...states[WHEEL].attributes, options: slots });
}

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

  // The same wheel under the names other rigs give it — bandwidths, spelled
  // out, any case. Its canvas ops must match `session`'s: a filter's colour is
  // its passband's, not its label's.
  wheel_names: {
    hass: (dump) =>
      relabelled(dump, {
        B: "Blue", L: "Lum", O: "OIII 3nm", R: "red", S: "SII 3nm",
      }).build(),
  },

  // A one-shot-colour rig's wheel of dual-band and broadband filters, named as
  // its owner typed them. Only UV reads as a passband (L); the other four take
  // spares in slot order, those that could pass for the wheel's G or H last,
  // so no two share one.
  dual_band: {
    hass: (dump) =>
      relabelled(dump, {
        L: "UV", R: "LPro", B: "L-eNhance", O: "HaOiii", S: "SiiOiii",
      }).build(),
  },

  // Names the wheel does not list, as renaming a slot mid-session leaves the
  // lights taken before it: each takes a spare in name order, the least like
  // the wheel's own passbands first.
  off_wheel: {
    hass: (dump) =>
      relabelled(dump, { B: "L-eNhance", L: "L-eXtreme" }, { wheel: false }).build(),
  },

  // A second luminance slot, a Clear beside the L: the first takes L's hue and
  // the Clear the first spare colour, so the two chips differ.
  second_luminance: { hass: (dump) => relabelled(dump, { B: "Clear" }).build() },

  // Every R light with no filter name, as a wheel that dropped out for them
  // leaves them: nine lights over two targets, grey and hollow.
  unfiltered: { hass: (dump) => relabelled(dump, { R: null }).build() },

  // The same night with the average-HFR sensor disabled, so no breakdown and
  // no chips. The named lights still say it is no one-shot-colour night: the
  // unnamed ones stay grey rather than taking a chart's colour.
  unfiltered_no_breakdown: {
    hass: (dump) => relabelled(dump, { R: null }).without("session_avg_hfr").build(),
  },

  // No light with a filter name, as a one-shot-colour camera with no wheel
  // reports them: no chips, and each chart in its own colour.
  one_shot_colour: {
    hass: (dump) =>
      relabelled(dump, { B: null, L: null, O: null, R: null, S: null })
        .without("filter_wheel_filter")
        .build(),
  },

  // No lights in the session, so no charts: the waiting panel under the
  // header's session totals.
  waiting: { hass: (dump) => rig(dump, "site_configured").build() },
};

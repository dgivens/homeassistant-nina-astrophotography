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

// The night with its filters renamed by `names`, captured name to new, where
// null takes the name away. Only labels change: each light, breakdown row and
// the last-filter reading keeps what the integration published, re-sorted by
// name as it sorts them, and a filter named null loses its row as a light
// with no filter has none.
function relabelled(dump, names) {
  const states = dump[NIGHT].states;
  const label = (name) => (name in names ? names[name] : name);
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
    .override(FILTER, label(states[FILTER].state) ?? "unknown", states[FILTER].attributes);
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

  // Filters with no fixed colour, which take one hashed from the name alone.
  other_names: {
    hass: (dump) =>
      relabelled(dump, { B: "L-eNhance", L: "L-eXtreme" }).build(),
  },

  // Every R light with no filter name, as a wheel that dropped out for them
  // leaves them: nine lights over two targets, grey, hollow and dashed.
  unfiltered: { hass: (dump) => relabelled(dump, { R: null }).build() },

  // No light with a filter name, as a one-shot-colour camera with no wheel
  // reports them: no chips, and each chart in its own colour.
  one_shot_colour: {
    hass: (dump) =>
      relabelled(dump, { B: null, L: null, O: null, R: null, S: null }).build(),
  },

  // No lights in the session, so no charts: the waiting panel under the
  // header's session totals.
  waiting: { hass: (dump) => rig(dump, "site_configured").build() },
};

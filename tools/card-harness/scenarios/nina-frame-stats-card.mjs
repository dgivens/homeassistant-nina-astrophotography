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
 * filter scenarios relabel that night rather than invent one: the series is
 * the whole night's 55 lights, so the breakdown and the last-filter reading
 * are rebuilt from it and stay consistent with it.
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

const round = (value, places) => Math.round(value * 10 ** places) / 10 ** places;

// The night with each light's filter replaced by `relabel(light, i)`, and
// everything the card reads that is tied to it rebuilt to match: the
// breakdown, sorted by name as the integration sorts it, and the newest
// light's filter, `unknown` when it has none.
function refiltered(dump, relabel) {
  const night = rig(dump, NIGHT);
  const states = dump[NIGHT].states;
  const lights = states[HFR].attributes.recent_lights.map(
    (light, i) => ({ ...light, filter: relabel(light, i) }));
  const groups = {};
  for (const light of lights) {
    if (light.filter !== null) (groups[light.filter] ??= []).push(light);
  }
  const byFilter = Object.fromEntries(Object.keys(groups).sort().map((name) => {
    const members = groups[name];
    return [name, {
      count: members.length,
      hfr_mean: round(members.reduce((sum, l) => sum + l.hfr, 0) / members.length, 3),
      integration_hours: round(members.reduce((sum, l) => sum + l.exposure, 0) / 3600, 2),
    }];
  }));
  const newest = lights[lights.length - 1].filter;
  return night
    .override(HFR, states[HFR].state, { ...states[HFR].attributes, recent_lights: lights })
    .override(AVG_HFR, states[AVG_HFR].state, { ...states[AVG_HFR].attributes, by_filter: byFilter })
    .override(FILTER, newest ?? "unknown", states[FILTER].attributes);
}

const renamed = (names) => (light) => names[light.filter] ?? light.filter;

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
      refiltered(dump, renamed({
        B: "Blue", L: "Lum", O: "OIII 3nm", R: "red", S: "SII 3nm",
      })).build(),
  },

  // Filters with no fixed colour, which take one hashed from the name. Two of
  // them, so they must not share a colour.
  other_names: {
    hass: (dump) =>
      refiltered(dump, renamed({ B: "UV/IR Cut", L: "L-eXtreme" })).build(),
  },

  // The Wizard Nebula's five R lights with no filter, as a wheel that dropped
  // out for that target leaves them: a grey no chip shares, beside R's four
  // remaining lights.
  unfiltered: {
    hass: (dump) =>
      refiltered(dump, (light) =>
        light.target === "Wizard Nebula" ? null : light.filter).build(),
  },

  // No lights in the session, so no charts: the waiting panel under the
  // header's session totals.
  waiting: { hass: (dump) => rig(dump, "site_configured").build() },
};

/**
 * Rig states for `nina-weather-card`, composed out of the committed dump.
 *
 * `site_configured` carries a real ObservingConditions station — eleven of its
 * fourteen channels, a connected safety monitor and a safe verdict — so the
 * atmosphere cells, the wind rose and the banner all render off captured data.
 * `equipment_disconnected` has no station and no monitor at all.
 *
 * Three channels this source reports as `"NaN"` have no entity anywhere in the
 * corpus: cloud cover, sky quality and star FWHM. Their cells therefore render
 * as `—` in every scenario below, and the sky-quality section — a bar, a label
 * and a scale — never renders at all. Nothing here can cover it without
 * inventing a channel, which is what `render.html` against a live rig is for.
 */

import { rig } from "../hass.mjs";

const UP = "site_configured";
const SAFETY = "binary_sensor.n_i_n_a_safety_monitor_unsafe";
const TEMPERATURE = "sensor.n_i_n_a_weather_temperature";

// No `draw` hook: the wind rose is painted from the frame the render queues,
// which the runner fires. Its arguments are then the card's own, read through
// whichever path the scenario put it on.

export const scenarios = {
  // Every id resolved, a connected station and a safe monitor.
  station: { hass: (dump) => rig(dump, UP).build() },

  // The same rig with no registry, which is the prefix fallback. Its ops must
  // match `station`'s: the same entities, reached the other way. No `prefix:` —
  // the point is the id the card builds unaided.
  templated: { hass: (dump) => rig(dump, UP).unresolvable().build() },

  // The pulsing banner. The verdict is invented: the monitor has reported safe
  // in every capture, and a rig that is imaging by definition has not tripped
  // it. Nothing else moves, so the conditions beneath still read as the benign
  // ones that were captured — this scenario is for the banner, not for a night
  // that would actually have closed the roof.
  unsafe: { hass: (dump) => rig(dump, UP).override(SAFETY, "on").build() },

  // Connected, with no reading yet — the third state, and the one the card
  // exists to keep out of the safe branch. Also invented: it is what the
  // monitor reports in the seconds after it connects, which no capture caught.
  unread: { hass: (dump) => rig(dump, UP).override(SAFETY, "unknown").build() },

  // The dew alert, which needs the air within 3 °C of the dew point. The
  // capture is 27.1 °C over a 20.5 °C dew point — a dawn-flats reading with 6.6
  // °C of margin — so the temperature is the one field moved, down to a night
  // that would be dewing. The humidity beside it does not follow it down; as
  // above, the alert is what this scenario is for.
  dew: { hass: (dump) => rig(dump, UP).override(TEMPERATURE, 22.0).build() },

  // No station and no monitor, which is what a fresh install shows: the
  // not-connected panel in place of the whole body, under a grey banner.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },
};

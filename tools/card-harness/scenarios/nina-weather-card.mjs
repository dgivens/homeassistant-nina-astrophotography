/**
 * Rig states for `nina-weather-card`, composed out of the committed dump.
 *
 * `site_configured` carries a real ObservingConditions station — ten of its
 * thirteen channels and the source naming it, a connected safety monitor and a
 * safe verdict — so the atmosphere cells, the wind rose and the banner all
 * render off captured data. `equipment_disconnected` has no weather device and
 * no monitor; its one weather entity is the hub's source, reading `unknown`,
 * which is what drives the not-connected panel.
 *
 * Three channels this source reports as `"NaN"` have no entity anywhere in the
 * corpus: cloud cover, sky quality and star FWHM. Their cells therefore render
 * as `—` in every scenario below, and the sky-quality section — a bar, a label
 * and a scale — never renders at all. Nothing here can cover it without
 * inventing a channel, which is what `render.html` against a live rig is for.
 */

import { rig } from "../hass.mjs";

const UP = "site_configured";
const US = "site_configured_us_customary";
const SAFETY = "binary_sensor.n_i_n_a_safety_monitor_unsafe";
const TEMPERATURE = "sensor.n_i_n_a_weather_temperature";
const HUMIDITY = "sensor.n_i_n_a_weather_humidity";

// No `draw` hook: the wind rose is painted from the frame the render queues,
// which the runner fires. `_drawWindRose` takes the direction and the speed as
// arguments, so a hook would have to pass them in by hand — and `station` and
// `templated` would then no longer be comparing the ids the card resolved.

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

  // The same verdict with the monitor's connectivity entity gone, which is what
  // disabling a diagnostic entity looks like to a card: no registry row and no
  // state. The banner must still read UNSAFE — that is the whole ordering of
  // the branches — so this is the one scenario that would catch it silently
  // going grey.
  unsafe_undiagnosed: {
    hass: (dump) =>
      rig(dump, UP).override(SAFETY, "on").without("safety_monitor_connected").build(),
  },

  // Connected, with no reading yet — the third state, and the one the card
  // exists to keep out of the safe branch. Also invented: it is what the
  // monitor reports in the seconds after it connects, which no capture caught.
  unread: { hass: (dump) => rig(dump, UP).override(SAFETY, "unknown").build() },

  // The dew alert, which needs the air within 3 °C of the dew point. The
  // capture is a dawn-flats reading — 27.1 °C over a 20.5 °C dew point, with
  // 67.3% humidity, a self-consistent triple — so it has 6.6 °C of margin.
  //
  // Two fields are invented, not one: cooling the air to 22.0 °C over the same
  // dew point *raises* the relative humidity, and 20.5 °C at 22.0 °C is 91%.
  // Moving the temperature alone would put an impossible pair on screen and
  // leave the humidity cell in its benign colour on the one night it should be
  // flagged.
  dew: {
    hass: (dump) =>
      rig(dump, UP).override(TEMPERATURE, 22.0).override(HUMIDITY, 91.0).build(),
  },

  // The station on a US customary instance: Home Assistant's own °F, mph, inHg
  // and in/h, each printed in its own unit at its own precision.
  us_customary: { hass: (dump) => rig(dump, US).build() },

  // A dew alert only °C can see. 23.0 °C over the 20.5 °C dew point is a
  // 2.5 °C margin, inside the 3 °C threshold — but 4.5 °F, which a threshold
  // read in °F would pass. Invented as `dew` is, as a self-consistent pair:
  // 73.4 °F is 23.0 °C, and 20.5 °C of dew point at 23.0 °C is 85.8%.
  dew_us_customary: {
    hass: (dump) =>
      rig(dump, US).override(TEMPERATURE, 73.4).override(HUMIDITY, 85.8).build(),
  },

  // No station and no monitor, which is what a fresh install shows: the
  // not-connected panel in place of the whole body, under a grey banner.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },
};

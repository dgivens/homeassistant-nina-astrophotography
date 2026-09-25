/**
 * Rig states for `nina-sky-map-card`, composed out of the committed dump.
 *
 * `site_configured` is the rig with everything up and an observing site;
 * `equipment_disconnected` is the same rig with the drivers down.
 */

import { rig } from "../hass.mjs";

const draw = (card) => card._drawFrame();
const FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip";

export const scenarios = {
  // Every id resolved, and the rig reporting where it is.
  tracking: { hass: (dump) => rig(dump, "site_configured").build(), draw },

  // The same rig with no registry, which is the prefix fallback. Its ops must
  // match `tracking`'s: the same entities, reached the other way.
  templated: {
    hass: (dump) => rig(dump, "site_configured").unresolvable().build(),
    config: { latitude: 31.5478 },
    draw,
  },

  // No site sensor, so Home Assistant's own latitude is what is left — a
  // different sky, and the one a hosted rig must not be drawn at.
  home_latitude: {
    hass: (dump) => rig(dump, "site_configured").without("site_latitude").build(),
    draw,
  },

  // Neither, which is a dashboard with no location configured at all.
  no_latitude: {
    hass: (dump) =>
      rig(dump, "site_configured").without("site_latitude").home(undefined).build(),
    draw,
  },

  // The time to the flip shown in hours, which must draw what `tracking` does.
  flip_in_hours: {
    hass: (dump) =>
      rig(dump, "site_configured").displayedIn(FLIP, "h", 1 / 60).build(),
    draw,
  },

  // Twenty minutes out, inside the warning window of a profile whose flip can
  // fire ten minutes before the countdown ends: the canvas warns. The reading is
  // invented — the corpus never caught a mount this close to its flip.
  flip_soon: {
    hass: (dump) => rig(dump, "site_configured").override(FLIP, 20).build(),
    draw,
  },

  // The drivers down: no stars, no pointing, and the disconnected chip.
  mount_down: { hass: (dump) => rig(dump, "equipment_disconnected").build(), draw },
};

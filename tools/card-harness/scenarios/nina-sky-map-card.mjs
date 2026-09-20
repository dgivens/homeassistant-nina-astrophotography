/**
 * Rig states for `nina-sky-map-card`, composed out of the committed dump.
 *
 * `site_configured` is the rig with everything up and an observing site;
 * `equipment_disconnected` is the same rig with the drivers down.
 */

import { rig } from "../hass.mjs";

const draw = (card) => card._drawFrame();

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

  // The drivers down: no stars, no pointing, and the disconnected chip.
  mount_down: { hass: (dump) => rig(dump, "equipment_disconnected").build(), draw },
};

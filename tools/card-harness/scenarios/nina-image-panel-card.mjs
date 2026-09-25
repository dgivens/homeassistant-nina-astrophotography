/**
 * Rig states for `nina-image-panel-card`, composed out of the committed dump.
 *
 * No image bytes are in the corpus, so no scenario shows a frame: every load
 * fails, the panel shows its no-image state and every thumbnail dims. What the
 * scenarios do reach is everything around the picture — the overlay pills, the
 * stats row, the header, the histogram off the newest frame's statistics, the
 * strip's filter labels — and, in `ops.mjs`, the image paths the card signs,
 * which name the entity the proxy resolves a rig by.
 *
 * `dawn_flats` is dumped from inside its own night: the last light's readings,
 * a 122-frame session, and a strip of twenty frames with the dawn flats newest.
 * The histogram is therefore a flat's, since index 0 is the newest frame of
 * any type while the pills and the stats row are the newest light's.
 *
 * `site_configured` is dumped on a later day than its night, so it has image
 * history but no session: a strip, no last-light readings, and the camera
 * exposing, which is the only capture where it is.
 */

import { rig } from "../hass.mjs";

const NIGHT = "dawn_flats";

// No `draw` hook: the histogram is painted synchronously from `set hass`.

export const scenarios = {
  // Every id resolved, and a whole night behind the panel.
  night: { hass: (dump) => rig(dump, NIGHT).build() },

  // The same rig with no registry, which is the prefix fallback. Its output
  // must match `night`'s: the same entities, reached the other way. No
  // `prefix:` — the point is the id the card builds unaided.
  templated: { hass: (dump) => rig(dump, NIGHT).unresolvable().build() },

  // Exposing, with frames in the history but no light this session.
  exposing: { hass: (dump) => rig(dump, "site_configured").build() },

  // The drivers down: no camera entities at all, and every reading unknown.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },
};

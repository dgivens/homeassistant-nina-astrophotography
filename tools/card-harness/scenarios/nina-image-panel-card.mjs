/**
 * Rig states for `nina-image-panel-card`, composed out of the committed dump.
 *
 * No image bytes are in the corpus, so no scenario shows a frame: every load
 * fails and the panel shows its no-image state, and in `render.html` every
 * thumbnail dims too. The load that succeeds — the frame on screen, the active
 * thumbnail following it — is reached by nothing here. What the scenarios do
 * reach is everything around the picture — the overlay pills, the stats row,
 * the header, the histogram, the strip's labels, all off the newest frame's
 * own `recent_frames` entry — and, in `ops.mjs`, the image paths the card
 * signs: the entity the proxy resolves a rig by, the frame's date, and which
 * frames a new save makes it fetch.
 *
 * `dawn_flats` is dumped from inside its own night, and all twenty
 * `recent_frames` are its dawn flats: the strip's six thumbnails are tagged
 * FLAT, and the readings are a flat's — ADU and a short exposure, no HFR, no
 * stars.
 *
 * `site_configured` is dumped on a later day than its night, so it has image
 * history but no session: a strip of lights with their own readings, no
 * session totals, and the camera exposing, which is the only capture where it
 * is.
 */

import { linkScenarios, rig } from "../hass.mjs";

const NIGHT = "dawn_flats";

// The night one frame earlier: its newest `recent_frames` entry not yet
// saved, which `after` then hands over as the save.
const MEAN_ADU = "sensor.n_i_n_a_last_image_mean_adu";
const before = (dump) => {
  const row = dump[NIGHT].states[MEAN_ADU];
  return rig(dump, NIGHT).override(MEAN_ADU, row.state, {
    ...row.attributes,
    recent_frames: row.attributes.recent_frames.slice(1),
  });
};

// No `draw` hook: the histogram is painted synchronously from `set hass`.

export const scenarios = {
  // Every id resolved, and a whole night behind the panel.
  night: { hass: (dump) => rig(dump, NIGHT).build() },

  // The same rig with no registry, which is the prefix fallback. Its output
  // must match `night`'s: the same entities, reached the other way. No
  // `prefix:` — the point is the id the card builds unaided.
  templated: { hass: (dump) => rig(dump, NIGHT).unresolvable().build() },

  // The exposure and the integration time shown in minutes, which must render
  // what `night` does.
  in_minutes: {
    hass: (dump) =>
      rig(dump, NIGHT)
        .displayedIn("sensor.n_i_n_a_last_image_exposure", "min", 1 / 60)
        .displayedIn("sensor.n_i_n_a_session_integration_time", "min", 60)
        .build(),
  },

  // No strip and no histogram, which must still describe the flat: the frame
  // on screen is read from the attribute, not from the strip.
  bare: {
    hass: (dump) => rig(dump, NIGHT).build(),
    config: { show_strip: false, show_histogram: false },
  },

  // Exposing, with lights in the history but none this session: the readings
  // are the frame's own, and the session totals empty.
  exposing: { hass: (dump) => rig(dump, "site_configured").build() },

  // The drivers down: no camera entities at all, no frames, and the session
  // totals zero.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },

  // The lost link: the badge names it, not the camera.
  ...linkScenarios(),

  // A frame saved: the panel signs the new frame's path, and a thumbnail for
  // it alone, while the five older tiles move along.
  saved: {
    hass: (dump) => before(dump).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
  },

  // The same with `refresh_on_save` off: the new thumbnail only, and the
  // frame on screen stays.
  saved_without_refresh: {
    hass: (dump) => before(dump).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
    config: { refresh_on_save: false },
  },
};

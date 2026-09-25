/**
 * Rig states for `nina-image-panel-card`, composed out of the committed dump.
 *
 * No image bytes are in the corpus, so no scenario shows a frame: every load
 * fails and the panel shows its no-image state, and in `render.html` every
 * thumbnail dims too. The load that succeeds — the frame on screen, the active
 * thumbnail following it — is reached by nothing here. What the scenarios do
 * reach is everything around the picture — the overlay pills, the stats row,
 * the header, the histogram off the newest frame's statistics, the strip's
 * filter labels — and, in `ops.mjs`, the image paths the card signs, which
 * name the entity the proxy resolves a rig by, and which saves it reloads on.
 *
 * `dawn_flats` is dumped from inside its own night: the last light's readings
 * and a 122-frame session of 55 lights, with the dawn flats after them. All
 * twenty `recent_frames` are those flats, so the strip's six thumbnails are
 * flats and so is the frame the histogram describes, while the pills and the
 * stats row are the newest light's — so each thumbnail is tagged FLAT, and the
 * pills and stats row are dimmed behind "Last light".
 *
 * `site_configured` is dumped on a later day than its night, so it has image
 * history but no session: a strip, no last-light readings, and the camera
 * exposing, which is the only capture where it is.
 *
 * `saves` and `saves_templated` render in `render.html` like `night`: only
 * `ops.mjs` fires their events.
 */

import { rig } from "../hass.mjs";

const NIGHT = "dawn_flats";

// A frame saved by this rig and one saved by another, which fire the same event
// type. The second rig is invented: the corpus holds one. Its instance name is
// the default one, so the slug that the fallback compares cannot tell it apart.
const saves = (dump) => {
  const [, entryId] = dump[NIGHT].devices.hub.identifiers.find(
    ([domain]) => domain === "nina_astrophotography",
  );
  return [
    { type: "nina_image_save", data: { entry_id: "another-rig", instance: "N.I.N.A." } },
    { type: "nina_image_save", data: { entry_id: entryId, instance: "N.I.N.A." } },
  ];
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

  // Exposing, with frames in the history but no light this session.
  exposing: { hass: (dump) => rig(dump, "site_configured").build() },

  // The drivers down: no camera entities at all, the last-light readings
  // unknown and the session totals zero.
  disconnected: { hass: (dump) => rig(dump, "equipment_disconnected").build() },

  // Two rigs saving. Resolved, the card reloads for its own rig's frame only:
  // one signed path, after the second event.
  saves: { hass: (dump) => rig(dump, NIGHT).build(), events: saves },

  // The same with no registry, where only the instance name is left to match
  // on — so both saves reload the panel.
  saves_templated: {
    hass: (dump) => rig(dump, NIGHT).unresolvable().build(),
    events: saves,
  },
};

/**
 * Entities for `nina-site-camera-card`, out of the committed dump.
 *
 * The card shows any camera or image entity, and reads nothing of the rig. The
 * dump holds two image entities, the last frame and the live stack, so they
 * stand in for a site's cameras: real rows, with a state that is the time of
 * their picture. A camera entity belongs to another integration, so the one
 * here is invented, in the shape core gives every camera.
 *
 * No picture's bytes are in the corpus, so every load fails and the card says
 * so; `pictured` points one at an image the repo does hold, for the browser.
 * What `ops.mjs` reaches is everything around the picture.
 */

import { rig } from "../hass.mjs";

const LIVE = "site_configured";
const FRAME = "image.n_i_n_a_last_frame";
const STACK = "image.n_i_n_a_livestack";
const PIER = "camera.pier";

const two = [
  { entity: FRAME, name: "Pier", url: "https://example.com/pier" },
  { entity: STACK },
];

// The live rig with one row's picture taken at another time, or from elsewhere.
const withFrame = (dump, state, picture) => {
  const row = dump[LIVE].states[FRAME];
  return rig(dump, LIVE).override(FRAME, state ?? row.state, {
    ...row.attributes,
    ...(picture ? { entity_picture: picture } : {}),
  });
};

// Core's camera row: `idle`, with the proxy path and its token.
const withCamera = (dump, state = "idle") =>
  rig(dump, LIVE).add(PIER, state, {
    access_token: "<per run>",
    entity_picture: `/api/camera_proxy/${PIER}?token=<per run>`,
    friendly_name: "Pier",
    supported_features: 0,
  });

export const scenarios = {
  // One camera: its own name under the title, and no chips.
  one: {
    hass: (dump) => rig(dump, LIVE).build(),
    config: { cameras: [{ entity: FRAME }] },
  },

  // Two, the first named and linked: chips, and Open over the picture.
  two: {
    hass: (dump) => rig(dump, LIVE).build(),
    config: { title: "Starfront", cameras: two },
  },

  // A picture the server holds, so the browser draws the frame around one.
  pictured: {
    hass: (dump) => withFrame(dump, null, "/docs/images/cards/sky-map.png").build(),
    config: { cameras: two },
  },

  // An image entity's picture moves with its state, and is asked for again.
  updated: {
    hass: (dump) => rig(dump, LIVE).build(),
    after: (dump) => [withFrame(dump, "2026-09-05T01:46:27.652839-05:00").build()],
    config: { cameras: [{ entity: FRAME }] },
  },

  // A camera entity: the proxy path asked for, stamped against the cache.
  camera: {
    hass: (dump) => withCamera(dump).build(),
    config: { cameras: [{ entity: PIER, url: "https://example.com/pier" }] },
  },

  // The camera's integration lost it: nothing asked for.
  unavailable: {
    hass: (dump) => withCamera(dump, "unavailable").build(),
    config: { cameras: [{ entity: PIER }] },
  },

  // An entity the instance does not have.
  missing: {
    hass: (dump) => rig(dump, LIVE).build(),
    config: { cameras: [{ entity: "camera.removed" }] },
  },

  // Fresh from the card picker on an instance with no camera.
  unconfigured: { hass: (dump) => rig(dump, LIVE).build() },

  // Folded to its header: nothing asked for.
  folded: {
    hass: (dump) => rig(dump, LIVE).build(),
    config: { cameras: two },
    folded: ["card"],
  },
};

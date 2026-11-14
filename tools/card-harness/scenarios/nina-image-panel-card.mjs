/**
 * Rig states for `nina-image-panel-card`, composed out of the committed dump.
 *
 * No image bytes are in the corpus, so no scenario shows a frame: every load
 * fails and the panel shows its no-image state, and in `render.html` every
 * thumbnail dims too. The load that succeeds — the frame on screen, the active
 * thumbnail following it — is reached by nothing here. What the scenarios do
 * reach is everything around the picture — the overlay pills, the stats row,
 * the header, the ADU range, the strip's labels, all off the newest frame's
 * own `recent_frames` entry — and, in `ops.mjs`, the image paths the card
 * signs: the entity the proxy resolves a rig by, the frame's date, and which
 * frames a new save makes it fetch.
 *
 * `dawn_flats` is dumped from inside its own night, and its newest twenty
 * `recent_frames` are its dawn flats: the strip's six thumbnails are tagged
 * FLAT, and the readings are a flat's — ADU and a short exposure, no HFR, no
 * stars. The twenty lights behind them are what "Lights only" shows.
 *
 * `site_configured` is dumped on a later day than its night, so it has image
 * history but no session: a strip of lights with their own readings, no
 * session totals, and the camera exposing, which is the only capture where it
 * is.
 */

import { linkScenarios, rig, unscaled } from "../hass.mjs";

const NIGHT = "dawn_flats";

// The night one frame earlier: its newest `recent_frames` entry not yet
// saved, which `after` then hands over as the save, and every other entry one
// frame younger. A real `recent_frames` would also hold the flat that is 21st
// after the save; nothing here reads it.
const MEAN_ADU = "sensor.n_i_n_a_last_image_mean_adu";
const CHOICE = "nina-image-panel-card:n_i_n_a:lights-only";
// The sensor between an integration's reload and its first poll: unavailable,
// with no `recent_frames`.
const reloading = (dump) => rig(dump, NIGHT).restored(MEAN_ADU).build();
const before = (dump) => {
  const row = dump[NIGHT].states[MEAN_ADU];
  return rig(dump, NIGHT).override(MEAN_ADU, row.state, {
    ...row.attributes,
    recent_frames: row.attributes.recent_frames
      .slice(1)
      .map((frame) => ({ ...frame, age: frame.age - 1 })),
  });
};

// No `draw` hook: the ADU range is painted synchronously from `set hass`.

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

  // No strip and no ADU range, which must still describe the flat: the frame
  // on screen is read from the attribute, not from the strip.
  bare: {
    hass: (dump) => rig(dump, NIGHT).build(),
    config: { show_strip: false, show_histogram: false },
  },

  // Exposing, with lights in the history but none this session: the readings
  // are the frame's own, and the session totals empty.
  exposing: { hass: (dump) => rig(dump, "site_configured").build() },

  // The night's flats from a 12- or 14-bit camera that does not scale to 16
  // bits. The ADU bar runs to that camera's full scale, so the whisker, median
  // and mean sit where `night` draws them, to well under a pixel. Only the
  // gridlines move, being in that camera's ADU: 10k is past a 12-bit camera's
  // full scale and left off, and at 14 bits its label sits left of its line.
  unscaled_12_bit: { hass: (dump) => unscaled(dump, NIGHT, 16).build() },
  unscaled_14_bit: { hass: (dump) => unscaled(dump, NIGHT, 4).build() },

  // `exposing`'s lights from a 12-bit camera: the background sits where
  // `exposing` draws it.
  exposing_12_bit: { hass: (dump) => unscaled(dump, "site_configured", 16).build() },

  // Four minutes into a ten-minute sub, the countdown and the bar. The dump is
  // taken at a later date than its capture, so its end has passed: this moves
  // the one reading a countdown needs to the harness's clock.
  counting_down: {
    hass: (dump) => {
      const end = "sensor.n_i_n_a_camera_exposure_end";
      const built = rig(dump, "site_configured")
        .override(end, new Date(Date.now() + 360_000).toISOString(),
          dump.site_configured.states[end].attributes)
        .build();
      built.states[end].last_changed = new Date(Date.now() - 240_000).toISOString();
      return built;
    },
  },

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

  // The same with `refresh_on_save` off. With a frame on screen that frame
  // stays; here every load fails, so the panel, showing none, takes the new one.
  saved_without_refresh: {
    hass: (dump) => before(dump).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
    config: { refresh_on_save: false },
  },

  // Folded to its header, which still counts the session: no frame, thumbnail
  // or ADU range is asked for, even as `saved` saves another.
  folded: {
    hass: (dump) => before(dump).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
    folded: ["card"],
  },

  // The ADU range folded to its heading: nothing drawn, the frame still loaded.
  folded_adu: { hass: (dump) => rig(dump, NIGHT).build(), folded: ["adu"] },

  // The strip folded to its heading: the frame loads, no thumbnail does.
  folded_strip: { hass: (dump) => rig(dump, NIGHT).build(), folded: ["strip"] },

  // The dawn flats passed over: the newest light on screen, and the strip its
  // lights, each fetched at its age behind the flats.
  lights_only: { hass: (dump) => rig(dump, NIGHT).build(), config: { lights_only: true } },

  // A flat saved while only lights are shown: no frame or thumbnail is fetched.
  lights_only_saved: {
    hass: (dump) => before(dump).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
    config: { lights_only: true },
  },

  // The button pressed over a flat: the newest light is fetched.
  lights_only_pressed: {
    hass: (dump) => rig(dump, NIGHT).build(),
    act: () => ({ press: pressLightsOnly }),
  },

  // Pressed over a flat while a newer flat is still loading: the newer flat
  // never reaches the screen, and the spinner stays until the light does.
  lights_only_pressed_mid_load: {
    hass: (dump) => before(dump).build(),
    after: (dump) => [rig(dump, NIGHT).build()],
    images: "hold",
    act: ({ load, log }) => {
      const look = (card) => log.push(screen(card));
      return {
        "older flat loads": load,
        "Lights only pressed": pressLightsOnly,
        "on screen": look,
        "newer flat loads": load,
        "still on screen": look,
        "light loads": load,
        "finally on screen": look,
      };
    },
  },

  // Pressed while the newest frame, a light, is still loading: that load stands,
  // and nothing is fetched twice.
  lights_only_pressed_mid_light_load: {
    hass: (dump) => rig(dump, "site_configured").build(),
    images: "hold",
    act: ({ load }) => ({ "Lights only pressed": pressLightsOnly, "light loads": load }),
  },

  // The integration reloaded while the newest frame loads: the frame is shown
  // when it lands, and stays as the sensor returns.
  reloaded_mid_load: {
    hass: (dump) => rig(dump, NIGHT).build(),
    images: "hold",
    act: ({ load, log, dump, hand }) => {
      const look = (card) => log.push(screen(card));
      return {
        "sensor unavailable": () => hand(reloading(dump)),
        "flat loads": load,
        "on screen": look,
        "sensor back": () => hand(rig(dump, NIGHT).build()),
        "still on screen": look,
      };
    },
  },

  // Pressed while the sensor is unavailable: the flat stays until the list is
  // back, then gives way to the newest light.
  lights_only_pressed_while_reloading: {
    hass: (dump) => rig(dump, NIGHT).build(),
    images: "hold",
    act: ({ load, log, dump, hand }) => {
      const look = (card) => log.push(screen(card));
      return {
        "flat loads": load,
        "sensor unavailable": () => hand(reloading(dump)),
        "Lights only pressed": pressLightsOnly,
        "on screen": look,
        "sensor back": () => hand(rig(dump, NIGHT).build()),
        "then on screen": look,
        "light loads": load,
        "finally on screen": look,
      };
    },
  },

  // A browser that pressed the button before: lights, with the option unset.
  lights_only_remembered: {
    hass: (dump) => rig(dump, NIGHT).build(),
    storage: { [CHOICE]: "1" },
  },

  // The same browser on a card with no strip, so no button to press again:
  // the card's own setting stands, and the flat is fetched.
  lights_only_remembered_without_strip: {
    hass: (dump) => rig(dump, NIGHT).build(),
    storage: { [CHOICE]: "1" },
    config: { show_strip: false },
  },

  // Pressed on, then off: the choice is stored only while it differs from the
  // card's setting.
  lights_only_pressed_twice: {
    hass: (dump) => rig(dump, NIGHT).build(),
    storage: {},
    act: () => ({ "pressed on": pressLightsOnly, "pressed off": pressLightsOnly }),
  },

  // Storage refused: the press outlasts the card being configured again, so
  // no flat is fetched after it.
  lights_only_storage_refused: {
    hass: (dump) => rig(dump, NIGHT).build(),
    storage: "refused",
    act: () => ({
      "Lights only pressed": pressLightsOnly,
      "configured again": (card) => card.setConfig({}),
    }),
  },

  // Only calibration frames listed: the panel says no light has been taken.
  // `recent_frames` would hold the night's lights; they are removed to reach it.
  lights_only_no_lights: {
    hass: (dump) => {
      const row = dump[NIGHT].states[MEAN_ADU];
      const frames = row.attributes.recent_frames.filter((f) => f.image_type !== "LIGHT");
      return rig(dump, NIGHT)
        .override(MEAN_ADU, row.state, { ...row.attributes, recent_frames: frames })
        .build();
    },
    config: { lights_only: true },
  },
};

function pressLightsOnly(card) {
  card.shadowRoot.getElementById("lights-only").click();
}

// The main image's frame, by the date in its path, and whether the spinner is up.
function screen(card) {
  const node = (id) => card.shadowRoot.getElementById(id);
  const img = node("main-img");
  const date = img.style.display === "none"
    ? null
    : new URL(img.src ?? "", "http://x").searchParams.get("date");
  const spinning = node("spinner").classList.contains("active");
  return `screen ${date ?? "none"}${spinning ? ", spinner" : ""}`;
}

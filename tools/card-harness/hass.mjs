/**
 * The `hass` object a card is handed, from the committed dump.
 *
 * Pure ESM with no imports, because both runners use it: `ops.mjs` under node
 * and `render.html` in a browser. Each loads
 * `tests/ha/snapshots/card_states.json` its own way and passes it in.
 *
 * Nothing here invents a reading. The dump is the fake rig's own output —
 * captured wire data, one mapper and one platform table later — so a scenario
 * composes by SUBTRACTING from a real rig, never by making one up. Where a
 * scenario does need a value the corpus cannot produce, `override` is the one
 * door, and it says so at the call site.
 */

/** Home Assistant's own location in the test instance, for the fallback path. */
export const HOME_LATITUDE = 32.87336;

// What a restored row keeps: the registry's name, icon, device class, unit and
// supported features, and the capability attributes of this integration's
// platforms.
const REGISTRY_ATTRIBUTES = new Set([
  "friendly_name", "icon", "device_class", "unit_of_measurement", "supported_features",
  "state_class", "options", "min", "max", "step", "mode", "supported_color_modes",
  "event_types",
]);

export class Rig {
  /**
   * @param {object} dump   one rig state out of `card_states.json`
   * @param {object} [config]  `hass.config`
   */
  constructor(dump, config = { latitude: HOME_LATITUDE }) {
    this._states = { ...dump.states };
    this._entities = { ...dump.entities };
    this._devices = dump.devices;
    this._config = config;
  }

  /** Drop entities by entity-id suffix, less the instance prefix. */
  without(...suffixes) {
    for (const id of Object.keys(this._states)) {
      const [, rest] = id.split(".");
      if (suffixes.some((suffix) => rest.endsWith(`_${suffix}`))) {
        delete this._states[id];
        delete this._entities[id];
      }
    }
    return this;
  }

  /**
   * Serve no registry, so every lookup falls back to the templated prefix:
   * what a card does on an instance it cannot identify (two rigs and no
   * `device_id:`), and a run whose output must match the resolved one's.
   */
  unresolvable() {
    this._entities = null;
    this._devices = null;
    return this;
  }

  /** Home Assistant's own latitude, or none at all. */
  home(latitude) {
    this._config = latitude === undefined ? {} : { latitude };
    return this;
  }

  /**
   * Replace one reading. The corpus cannot produce every state — say which at
   * the call site, the way a synthetic fixture has to.
   */
  override(entityId, state, attributes) {
    const row = this._states[entityId];
    if (!row) throw new Error(`${entityId} is not in the dump — nothing to override`);
    this._states[entityId] = {
      state: String(state),
      attributes: attributes ?? row.attributes,
    };
    return this;
  }

  /**
   * One reading in another unit, as picking a display unit for the entity
   * shows it: the same quantity, at `factor` of `unit` to the unit it had. Not
   * an invented reading, so its scenario must draw what the original does.
   */
  displayedIn(entityId, unit, factor) {
    const row = this._states[entityId];
    if (!row) throw new Error(`${entityId} is not in the dump — nothing to convert`);
    return this.override(entityId, parseFloat(row.state) * factor, {
      ...row.attributes,
      unit_of_measurement: unit,
    });
  }

  /**
   * Replace a row with core's placeholder for a registry row no entity has
   * claimed since the restart: `unavailable`, marked `restored`, over what the
   * registry holds of it (`RegistryEntry.write_unavailable_state`). An
   * entity's own attributes, such as `recent_frames`, are not among them.
   * Core's shape, not an invented reading.
   */
  restored(entityId) {
    const row = this._states[entityId];
    if (!row) throw new Error(`${entityId} is not in the dump — nothing to restore`);
    const kept = Object.entries(row.attributes).filter(([key]) => REGISTRY_ATTRIBUTES.has(key));
    return this.override(entityId, "unavailable", { ...Object.fromEntries(kept), restored: true });
  }

  /**
   * Drop every row but keep the registry: Home Assistant once it has started
   * and before the entry has set up, or while it retries its setup.
   */
  beforeSetup() {
    this._states = {};
    return this;
  }

  /** Stamp every row's `last_changed`, which the dump does not carry. */
  changedAt(date) {
    const stamp = date.toISOString();
    for (const [id, row] of Object.entries(this._states)) {
      this._states[id] = { ...row, last_changed: stamp };
    }
    return this;
  }

  build() {
    const hass = { states: this._states, config: this._config };
    if (this._entities) {
      hass.entities = this._entities;
      hass.devices = this._devices;
    }
    return hass;
  }
}

/**
 * @param {object} dump      the whole `card_states.json`
 * @param {string} rigState  which state in it
 */
export function rig(dump, rigState) {
  const state = dump[rigState];
  if (!state) {
    throw new Error(`no rig state "${rigState}" — have: ${Object.keys(dump).join(", ")}`);
  }
  return new Rig(state);
}

/**
 * Lost-link scenarios around the live `site_configured` rig, for every card
 * that shows one:
 *
 * - `unreachable` — no live view before it: must draw the lost link alone.
 * - `not_answering` — one missed poll, inside the grace: the held readings,
 *   marked stale.
 * - `lost` — live, then past the grace: the last live readings, marked stale.
 * - `recovered` — lost, then answering again: the live rig, not stale.
 * - `unreachable_templated` — no registry, so the card's templated ids.
 * - `not_loaded` — every row restored, as an entry that is not loaded leaves
 *   them: must draw the lost link alone.
 * - `restarted` — live, then Home Assistant restarting under the card: no
 *   rows, then every row restored. Must draw what `lost` does.
 */
export function linkScenarios() {
  const notLoaded = (dump) => {
    const rows = rig(dump, "site_configured");
    for (const id of Object.keys(dump.site_configured.states)) rows.restored(id);
    return rows.changedAt(new Date(Date.now() - 45_000)).build();
  };
  return {
    unreachable: { hass: (dump) => rig(dump, "nina_unreachable").build() },
    not_answering: {
      hass: (dump) =>
        rig(dump, "nina_not_answering").changedAt(new Date(Date.now() - 15_000)).build(),
    },
    lost: {
      hass: (dump) => rig(dump, "site_configured").build(),
      after: (dump) => [
        rig(dump, "nina_unreachable").changedAt(new Date(Date.now() - 45_000)).build(),
      ],
    },
    recovered: {
      hass: (dump) => rig(dump, "site_configured").build(),
      after: (dump) => [
        rig(dump, "nina_unreachable").build(),
        rig(dump, "site_configured").build(),
      ],
    },
    unreachable_templated: {
      hass: (dump) => rig(dump, "nina_unreachable").unresolvable().build(),
    },
    not_loaded: { hass: notLoaded },
    restarted: {
      hass: (dump) => rig(dump, "site_configured").build(),
      after: (dump) => [rig(dump, "site_configured").beforeSetup().build(), notLoaded(dump)],
    },
  };
}

/**
 * A meridian flip under way on the `site_configured` rig, for every card that
 * shows one. No capture caught a flip, so each reading is invented, with the
 * ones a flip ties to it: the guider stopped first, and while N.I.N.A. waits
 * for meridian + Min, tracking off and the countdown `unknown`.
 *
 * - `flip_waiting` — the slew four and a half minutes off.
 * - `flip_slewing` — the wait over and tracking back on, the countdown at the
 *   profile's ten-minute window, where the slew starts.
 *
 * `draw` is the card's hook, if it has one.
 */
export function flipScenarios(draw) {
  const FLIPPING = "binary_sensor.n_i_n_a_mount_meridian_flip";
  const flipping = (dump, slewsInMinutes) => {
    const slewsAt = new Date(Date.now() + slewsInMinutes * 60_000).toISOString();
    return rig(dump, "site_configured")
      .override(FLIPPING, "on", {
        ...dump.site_configured.states[FLIPPING].attributes,
        slews_at: slewsAt,
      })
      .override("switch.n_i_n_a_guider", "off")
      .override("sensor.n_i_n_a_guider_status", "Stopped");
  };
  const hook = draw ? { draw } : {};
  return {
    flip_waiting: {
      hass: (dump) =>
        flipping(dump, 4.5)
          .override("select.n_i_n_a_mount_tracking_rate", "Stopped")
          .override("sensor.n_i_n_a_mount_time_to_meridian_flip", "unknown")
          .build(),
      ...hook,
    },
    flip_slewing: {
      hass: (dump) =>
        flipping(dump, -0.5).override("sensor.n_i_n_a_mount_time_to_meridian_flip", 10).build(),
      ...hook,
    },
  };
}

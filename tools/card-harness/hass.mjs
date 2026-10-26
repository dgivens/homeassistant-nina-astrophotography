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
   * claimed since the restart: `unavailable`, marked `restored`, over its own
   * attributes. Core's shape, not an invented reading.
   */
  restored(entityId) {
    const row = this._states[entityId];
    if (!row) throw new Error(`${entityId} is not in the dump — nothing to restore`);
    return this.override(entityId, "unavailable", { ...row.attributes, restored: true });
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
 */
export function linkScenarios() {
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
    not_loaded: {
      hass: (dump) => {
        const notLoaded = rig(dump, "site_configured");
        for (const id of Object.keys(dump.site_configured.states)) notLoaded.restored(id);
        return notLoaded.changedAt(new Date(Date.now() - 45_000)).build();
      },
    },
  };
}

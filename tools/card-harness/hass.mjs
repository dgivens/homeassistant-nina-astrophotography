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
   * Serve no registry, so every lookup falls back to the templated prefix.
   * What a card does on an instance that cannot be identified — two rigs and no
   * `device_id:` — and the comparison that says a conversion changed nothing.
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

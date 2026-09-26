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

  /**
   * Replace a row with Home Assistant's restored placeholder — `unavailable`,
   * marked `restored`, over the row's own attributes — as core leaves one for a
   * registry row no entity has claimed since the restart. Fabricated, but core's
   * own shape rather than an invented reading.
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

// A hub row none of the cards reads, standing in for an orphan: a registry row
// no entity claims, which reads `unavailable` for ever.
const ORPHAN = "sensor.n_i_n_a_wait_ends_at";

/**
 * The lost-link scenarios every card that tells one carries, around the live
 * `site_configured` rig:
 *
 * - `unreachable` — N.I.N.A. not answering, seen by a card with nothing live
 *   to keep.
 * - `blip` — live, then one missed poll: must still draw the live rig.
 * - `lost` — live, then a link down past the grace period: `unreachable`.
 * - `unreachable_templated` — `unreachable` with no registry, where the card's
 *   own templated hub ids are what is left to tell it by.
 * - `orphaned_row` — live beside an orphaned hub row: must draw the live rig.
 *
 * `Date.now()` is pinned in `ops.mjs`, so `blip` and `lost` are fixed
 * distances into the grace period.
 */
export function linkScenarios() {
  const downFor = (ms) => ({
    hass: (dump) => rig(dump, "site_configured").build(),
    after: (dump) => [
      rig(dump, "nina_unreachable").changedAt(new Date(Date.now() - ms)).build(),
    ],
  });
  return {
    unreachable: { hass: (dump) => rig(dump, "nina_unreachable").build() },
    blip: downFor(10_000),
    lost: downFor(45_000),
    unreachable_templated: {
      hass: (dump) => rig(dump, "nina_unreachable").unresolvable().build(),
    },
    orphaned_row: { hass: (dump) => rig(dump, "site_configured").restored(ORPHAN).build() },
  };
}

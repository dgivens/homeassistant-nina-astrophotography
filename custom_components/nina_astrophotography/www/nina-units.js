/**
 * Readings in the unit Home Assistant shows them in.
 *
 * Not a card, so not in `frontend.py`'s `CARD_FILENAMES`.
 *
 * Home Assistant converts a state into the instance's unit system, or into a
 * unit the user picked for that entity, before a card sees it: a wind speed
 * published in m/s arrives in km/h on a metric instance and in mph on a US
 * customary one. The unit it chose is the state's `unit_of_measurement`, and
 * the precision to show it at is the registry's `display_precision`, already
 * scaled for that unit. A card prints the reading in that unit and converts it
 * only to compare it against a threshold of its own.
 */

// Every unit Home Assistant can show these quantities in, as maps into and out
// of its family's base unit. The factors are core's (`util/unit_conversion.py`),
// and `tests/ha/test_card_units.py` holds this table to them.
const scaled = (family, factor) => ({
  family,
  toBase: (value) => value * factor,
  fromBase: (value) => value / factor,
});

const UNITS = {
  "°C": { family: "temperature", toBase: (c) => c, fromBase: (c) => c },
  "°F": { family: "temperature", toBase: (f) => (f - 32) / 1.8, fromBase: (c) => c * 1.8 + 32 },
  "K": { family: "temperature", toBase: (k) => k - 273.15, fromBase: (c) => c + 273.15 },

  "m/s": scaled("speed", 1),
  "km/h": scaled("speed", 1 / 3.6),
  "mph": scaled("speed", 0.44704),
  "kn": scaled("speed", 1852 / 3600),
  "ft/s": scaled("speed", 0.3048),
  "in/s": scaled("speed", 0.0254),
  "mm/s": scaled("speed", 0.001),
  "m/min": scaled("speed", 1 / 60),
  // Core rounds to a whole force on the way in, so the way out is approximate.
  "Beaufort": {
    family: "speed",
    toBase: (force) => 0.836 * force ** 1.5,
    fromBase: (ms) => Math.round((ms / 0.836) ** (2 / 3)),
  },

  "mm/h": scaled("rain", 1),
  "mm/d": scaled("rain", 1 / 24),
  "in/h": scaled("rain", 25.4),
  "in/d": scaled("rain", 25.4 / 24),

  "hPa": scaled("pressure", 1),
  "mbar": scaled("pressure", 1),
  "Pa": scaled("pressure", 0.01),
  "mPa": scaled("pressure", 0.00001),
  "kPa": scaled("pressure", 10),
  "cbar": scaled("pressure", 10),
  "bar": scaled("pressure", 1000),
  "mmHg": scaled("pressure", 1.33322387415),
  "inHg": scaled("pressure", 33.86388640341),
  "inH₂O": scaled("pressure", 2.490889083333348),
  "psi": scaled("pressure", 68.94757),

  "μs": scaled("duration", 0.000001),
  "ms": scaled("duration", 0.001),
  "s": scaled("duration", 1),
  "min": scaled("duration", 60),
  "h": scaled("duration", 3600),
  "d": scaled("duration", 86400),
  "w": scaled("duration", 604800),
};

/**
 * `value` in `from`, converted to `to` — or `null` when either unit is one
 * this table does not hold, or the two measure different things.
 */
export function convert(value, from, to) {
  if (!Number.isFinite(value)) return null;
  if (from === to) return value;
  const source = UNITS[from];
  const target = UNITS[to];
  if (!source || !target || source.family !== target.family) return null;
  return target.fromBase(source.toBase(value));
}

/**
 * A difference between two readings, converted: a 3 °C margin is 5.4 °F, not
 * the 37.4 °F that converting it as a temperature gives.
 */
export function interval(delta, from, to) {
  const moved = convert(delta, from, to);
  return moved === null ? null : moved - convert(0, from, to);
}

/**
 * An entity's state as `{value, unit, precision}`, or `null` when it is
 * missing or not a number — `unknown` and `unavailable` included.
 */
export function quantity(hass, id) {
  const entity = hass?.states?.[id];
  const value = parseFloat(entity?.state);
  if (!Number.isFinite(value)) return null;
  return {
    value,
    unit: entity.attributes?.unit_of_measurement ?? null,
    precision: hass.entities?.[id]?.display_precision ?? null,
  };
}

/** A quantity converted to `unit`, or `null` if it has none or cannot be. */
export function inUnit(r, unit) {
  return r ? convert(r.value, r.unit, unit) : null;
}

/**
 * A quantity's number as Home Assistant would print it, or `null` for none.
 * `decimals` is only for an entity the registry gives no precision.
 */
export function displayed(r, decimals) {
  return r ? r.value.toFixed(r.precision ?? decimals) : null;
}

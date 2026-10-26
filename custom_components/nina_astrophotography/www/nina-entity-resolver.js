/**
 * Resolve a rig's entity ids from the Home Assistant registries.
 *
 * Not a card, and not in `frontend.py`'s `CARD_FILENAMES`: it defines no custom
 * element, so registering it as a Lovelace resource would load it on every
 * dashboard to no effect. A card imports it from the same static route.
 *
 * Under `has_entity_name` an entity id is `slugify(device name) + "_" +
 * slugify(entity name)`, so a card that templates a configured prefix onto a
 * hardcoded suffix breaks whenever either name is not what it assumed — a
 * renamed device, or ids generated under a different area (see the README's
 * troubleshooting section). `translation_key` survives both.
 *
 * `frontend.py` serves this with no cache headers and no version query, so a
 * card and this module can skew across an upgrade — as any two cards already
 * can.
 */

const DOMAIN = "nina_astrophotography";

// A hub carries a `nina_astrophotography` identifier and, unlike every child
// device, no `via_device_id` (device.py `device_identifiers`, `child_device_info`).
function hubs(devices) {
  return Object.values(devices).filter(
    (device) =>
      !device.via_device_id &&
      device.identifiers?.some(([domain]) => domain === DOMAIN),
  );
}

// One rig needs no configuration. Two or more are ambiguous, so fall back to
// the configured device — which may name the hub or any one piece of its
// equipment, since a child names its hub in `via_device_id`.
function hubOf(devices, configuredDeviceId) {
  if (!devices) return null;
  const found = hubs(devices);
  const configured = configuredDeviceId && devices[configuredDeviceId];
  return (
    (found.length === 1
      ? found[0].id
      : configured && (configured.via_device_id ?? configured.id)) || null
  );
}

/**
 * Map `"<domain>.<translation_key>"` onto the live entity id, for one rig.
 *
 * Keyed on the domain too, because `translation_key` is unique only per domain —
 * the focuser position exists as both a sensor and a number.
 *
 * Always an object, never null, and empty rather than partial when the rig
 * cannot be identified. A missing entry is the caller's cue to fall back: an
 * entity with no translation key, or a disabled one, which core omits from the
 * registry payload the frontend receives and so can never resolve.
 *
 * @param {object} hass the Home Assistant object a card is handed
 * @param {string} [configuredDeviceId] only consulted for two or more rigs
 * @returns {Object<string, string>}
 */
export function resolveEntities(hass, configuredDeviceId) {
  const map = {};
  const devices = hass?.devices;
  const hubId = hubOf(devices, configuredDeviceId);
  if (!hubId) return map;

  const rig = new Set([hubId]);
  for (const device of Object.values(devices)) {
    if (device.via_device_id === hubId) rig.add(device.id);
  }

  for (const entity of Object.values(hass.entities ?? {})) {
    if (!entity.translation_key || !rig.has(entity.device_id)) continue;
    const domain = entity.entity_id.split(".")[0];
    map[`${domain}.${entity.translation_key}`] = entity.entity_id;
  }
  return map;
}

/**
 * One card's entity ids: resolved from the registry, else `prefix` templated
 * onto a slug. A new config builds a new one, which re-resolves on the next
 * `refresh`.
 */
export class RigEntities {
  /**
   * @param {string} prefix the configured instance prefix, the fallback
   * @param {string} [deviceId] only consulted for two or more rigs
   */
  constructor(prefix, deviceId) {
    this._prefix = prefix;
    this._deviceId = deviceId;
    this._map = {};
    this._from = null;
  }

  /**
   * Re-resolve if the registry changed.
   *
   * The frontend replaces `hass.entities` only when the registry itself
   * changes, so this walks it on a rename, not on every state tick.
   * `hass.devices` needs no second memo key: every device change that alters
   * the map arrives with an entity-registry change too.
   */
  refresh(hass) {
    if (hass.entities === this._from) return;
    this._from = hass.entities;
    this._map = resolveEntities(hass, this._deviceId);
  }

  /** The entity id for `translation_key` `key`, else `<domain>.<prefix>_<slug>`. */
  id(domain, key, slug = key) {
    return this._map[`${domain}.${key}`] ?? `${domain}.${this._prefix}_${slug}`;
  }
}

// Hub rows created on every setup. They go `unavailable` only once the
// coordinator stops holding the last data: a rig with every driver down still
// reports them. Two, so disabling one cannot blind the check.
const HELD_ROWS = [
  ["binary_sensor", "sequencer_running"],
  ["sensor", "session_image_count"],
];

/**
 * The link to N.I.N.A., read from the rig's `reachable` row.
 *
 * That row turns `off` on the first missed poll and stays available, so it
 * says when N.I.N.A. went quiet but not when the grace period ran out; the
 * held rows going `unavailable` say that. It is created on every setup, so a
 * restored copy means the entry is not loaded. Should it be disabled, the
 * held rows alone still tell a lost link, though not since when.
 *
 * @param {object} hass the Home Assistant object a card is handed
 * @param {RigEntities} rig the card's entity ids, refreshed from `hass` here
 * @returns {{since: number|null, lost: boolean}} `since`, when N.I.N.A.
 *   stopped answering (epoch ms), `null` while it answers; `lost`, past the
 *   grace period
 */
export function linkState(hass, rig) {
  rig.refresh(hass);
  const row = (domain, key) => hass.states?.[rig.id(domain, key)];
  const reachable = row("binary_sensor", "reachable");
  const failed = reachable?.attributes?.restored === true;
  const quiet = failed || reachable?.state === "off";
  const lost =
    failed || HELD_ROWS.some(([domain, key]) => row(domain, key)?.state === "unavailable");
  return { since: quiet ? Date.parse(reachable.last_changed) || null : null, lost };
}

/** Whether `hass` holds the rig's rows at all, which it does not until the entry sets up. */
function reported(hass, rig) {
  return [["binary_sensor", "reachable"], ...HELD_ROWS].some(
    ([domain, key]) => hass.states?.[rig.id(domain, key)] !== undefined,
  );
}

/**
 * What a card draws from while N.I.N.A. is not answering: the last `hass` in
 * which the link was up, kept in memory, so the readings stay on screen marked
 * stale rather than turning to `unavailable`.
 *
 * Inside the grace period Home Assistant still holds the readings, so `hass`
 * itself is drawn. Past it, only a card that saw the link up has anything to
 * show; one loaded during the outage draws the lost link. A `hass` without the
 * rig's rows, as Home Assistant starting up or an entry retrying its setup
 * hands a card, is not the link up and never replaces the view kept. Nothing
 * is stored across a reload: readings from last night are not worth showing.
 */
export class LinkView {
  constructor() {
    this._live = null;
  }

  /**
   * @param {object} hass the Home Assistant object a card is handed
   * @param {RigEntities} rig the card's entity ids
   * @returns {{hass: object, since: number|null, lost: boolean, stale: boolean}}
   *   `hass` to draw readings from; `since` and `lost` as `linkState` gives
   *   them; `stale`, readings drawn but not current
   */
  read(hass, rig) {
    const { since, lost } = linkState(hass, rig);
    if (!lost && reported(hass, rig)) this._live = hass;
    return {
      hass: lost ? this._live ?? hass : hass,
      since,
      lost,
      stale: lost ? this._live !== null : since !== null,
    };
  }

  /** Forget the last live view, as a new config must. */
  reset() {
    this._live = null;
  }
}

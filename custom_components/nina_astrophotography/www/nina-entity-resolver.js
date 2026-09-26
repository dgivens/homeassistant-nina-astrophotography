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
 * troubleshooting table). `translation_key` survives both.
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
 * This integration's entity ids on the hub, for `linkLostSince`; `null` when
 * the rig cannot be identified.
 *
 * No hub entity overrides `available`, so these go `unavailable` only when the
 * coordinator fails: a rig with every driver down still reports `off` and `0`.
 * All of them, so disabling a few cannot blind the check. Other integrations'
 * helpers linked to the hub are left out; they go unavailable on their own.
 *
 * Walks the whole registry: memoise it as `resolveEntities` is.
 *
 * @param {object} hass the Home Assistant object a card is handed
 * @param {string} [configuredDeviceId] only consulted for two or more rigs
 * @returns {string[]|null}
 */
export function hubEntityIds(hass, configuredDeviceId) {
  const hubId = hubOf(hass?.devices, configuredDeviceId);
  if (!hubId) return null;
  return Object.values(hass.entities ?? {})
    .filter((entity) => entity.device_id === hubId && entity.platform === DOMAIN)
    .map((entity) => entity.entity_id);
}

/**
 * When N.I.N.A. stopped answering (epoch ms), or `null` while it answers: the
 * earliest `last_changed` of the rows that count.
 *
 * A restored row counts only when every row is restored — an entry that failed
 * to load. Beside live rows it is an entity not created this run (first-sight,
 * like the live stack, or an orphan): `unavailable` regardless of the link,
 * and changed at Home Assistant's start.
 *
 * @param {object} hass the Home Assistant object a card is handed
 * @param {string[]} ids rows that go `unavailable` only with the link:
 *   `hubEntityIds`, or a card's templated hub ids when that is `null`
 * @returns {number|null}
 */
export function linkLostSince(hass, ids) {
  const rows = ids.map((id) => hass.states?.[id]).filter(Boolean);
  const down = rows.filter((row) => row.state === "unavailable");
  const fresh = down.filter((row) => !row.attributes?.restored);
  // A lone restored row cannot tell a failed entry from an orphan.
  const failed = rows.length > 1 && down.length === rows.length;
  const lost = fresh.length ? fresh : failed ? down : [];
  if (!lost.length) return null;
  return Math.min(...lost.map((row) => Date.parse(row.last_changed) || 0));
}

// One failed poll makes every entity unavailable; on a remote link that is
// routine while the rig images on.
export const LINK_GRACE_MS = 30_000;

/**
 * Keeps a card's last live view through a failed poll, which would otherwise
 * draw every reading `unavailable`.
 *
 * A card calls `hold(since)` before rendering: `true` means keep what is on
 * screen, and `onExpire` fires when the grace period ends. Nothing is held
 * without a live view to keep (a fresh load, a new config).
 *
 * The wait is capped at LINK_GRACE_MS: `since` is on Home Assistant's clock,
 * `Date.now()` on the browser's. A detached card's timer is left to run.
 */
export class LinkGrace {
  /** @param {function(): void} onExpire re-renders the card */
  constructor(onExpire) {
    this._onExpire = onExpire;
    this._live = false;
    this._timer = null;
  }

  /**
   * @param {number|null} since `linkLostSince`, or `null` for a live link
   * @returns {boolean} whether to keep the last view rather than render
   */
  hold(since) {
    this._clear();
    if (since !== null && this._live) {
      const wait = Math.min(LINK_GRACE_MS, since + LINK_GRACE_MS - Date.now());
      if (wait > 0) {
        this._timer = setTimeout(() => {
          this._timer = null;
          this._onExpire();
        }, wait);
        return true;
      }
    }
    this._live = since === null;
    return false;
  }

  /** Whether a hold is in progress. */
  get holding() {
    return this._timer !== null;
  }

  /** Forget the live view, as a new config must. */
  reset() {
    this._clear();
    this._live = false;
  }

  _clear() {
    clearTimeout(this._timer);
    this._timer = null;
  }
}

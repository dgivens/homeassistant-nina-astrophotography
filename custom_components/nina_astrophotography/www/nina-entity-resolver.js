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
 * The hub's own entity ids, the rows `linkLostSince` reads; `null` when the rig
 * cannot be identified, as `resolveEntities` would resolve nothing.
 *
 * The hub has no driver of its own to lose, so no hub entity overrides
 * `available`: its rows read `unavailable` only when the coordinator's poll
 * fails, and a rig with every driver down still reports `off` and `0` there.
 * Every enabled row, so a user disabling any few of them cannot blind the
 * check; a disabled one is absent from `hass.entities`. Only this
 * integration's: a helper linked to the hub, such as a template sensor, can
 * read `unavailable` for reasons of its own.
 *
 * A walk of the whole registry, so a card memoises it as it does
 * `resolveEntities`.
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
 * When N.I.N.A. stopped answering, in epoch ms, or `null` while it answers,
 * read off rows that go `unavailable` only with the link: `hubEntityIds`, or a
 * card's own prefix-templated hub ids when the rig cannot be identified.
 *
 * A row Home Assistant restored from the registry counts only when every row
 * is one, which is an entry that failed to load — N.I.N.A. unreachable. A
 * restored row beside live ones is an entity not created this run: one created
 * on first sight, like the live stack before a stack exists, or an orphan no
 * entity claims any more. Either reads `unavailable` until it is, and its
 * `last_changed` is Home Assistant's start, not the moment a link went down.
 *
 * Since the earliest `last_changed` among the rows that count; a row without
 * one is taken as lost long since.
 *
 * @param {object} hass the Home Assistant object a card is handed
 * @param {string[]} ids the rows to read
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

// A single failed poll makes every entity unavailable for one ten-second
// interval, and on a remote link that is routine while the rig images on.
export const LINK_GRACE_MS = 30_000;

/**
 * Hold a card's last live view through a lost link's grace period.
 *
 * Every reading is `unavailable` for the length of a failed poll, which would
 * draw the rig as stopped. A card asks `hold(since)` before it renders: `true`
 * means keep what is on screen, and `onExpire` fires once the grace period
 * runs out so the card can render the lost link. A card with nothing live on
 * screen — a fresh load, or a new config — holds nothing and shows the lost
 * link at once.
 *
 * A detached card's timer is left to run: it renders once into a card no one
 * sees, which is then current if it is attached again.
 *
 * The wait is capped at the grace period: `since` is Home Assistant's clock and
 * `Date.now()` the browser's, and a browser running behind would otherwise
 * hold for as long as it lags.
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

  /** Whether the last `hold` kept the view, and its grace period still runs. */
  get holding() {
    return this._timer !== null;
  }

  /** Nothing on screen is live any more: a new config names another rig. */
  reset() {
    this._clear();
    this._live = false;
  }

  _clear() {
    clearTimeout(this._timer);
    this._timer = null;
  }
}

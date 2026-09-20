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
  if (!devices) return map;

  // One rig needs no configuration. Two or more are ambiguous, so fall back to
  // the configured device — which may name the hub or any one piece of its
  // equipment, since a child names its hub in `via_device_id`.
  const found = hubs(devices);
  const configured = configuredDeviceId && devices[configuredDeviceId];
  const hubId =
    found.length === 1
      ? found[0].id
      : configured && (configured.via_device_id ?? configured.id);
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

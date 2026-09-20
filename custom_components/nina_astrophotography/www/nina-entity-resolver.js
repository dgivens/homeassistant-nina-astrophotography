/**
 * Resolve a rig's entity ids from the Home Assistant registries.
 *
 * NOT a card, and deliberately not in `frontend.py`'s `CARD_FILENAMES`: it
 * defines no custom element, so registering it as a Lovelace resource would
 * load it standalone on every dashboard to no effect. A card reaches it with
 * `import "./nina-entity-resolver.js"`, an ordinary same-origin module fetch
 * from the same static route (`frontend.py`), with no registration step.
 *
 * Why this exists: entity ids are `slugify(device name) + "_" + slugify(entity
 * name)` under `has_entity_name`, so templating one configured prefix onto a
 * hardcoded suffix breaks whenever those names are not what the card assumed —
 * a user renaming a device, or Home Assistant generating ids under a different
 * area because the hub was placed in one after some equipment had already
 * connected (see the README's troubleshooting table). `translation_key` is the
 * only handle that survives both, and the registry carries it.
 *
 * `StaticPathConfig(..., False)` (`frontend.py`) sets no cache headers and the
 * registered URLs carry no version query, so a card and this module can skew
 * across an upgrade — the same exposure the cards already have between
 * themselves.
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
 * Keyed on the domain as well as the key because `translation_key` is unique
 * only per domain — the focuser position exists as both a sensor and a number.
 *
 * Always returns an object, so a caller needs no null handling. It is empty
 * rather than partial whenever the rig cannot be identified, and entities
 * missing from it are the caller's cue to fall back: an entity with no
 * translation key, or one that ships disabled — core omits `disabled_by`
 * entities from the registry payload the frontend receives, so a disabled
 * entity can never resolve.
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

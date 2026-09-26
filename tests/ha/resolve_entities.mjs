// Print a `nina-entity-resolver.js` result as JSON, for `test_entity_resolver.py`
// and `test_card_states.py`.
//
// Node so that the module under test is the one a browser loads; a Python
// reimplementation would only prove itself right.
//
// Usage: node resolve_entities.mjs <payload.json> [device_id] [fn]
//
// `fn` is `resolveEntities` (the default) or `linkLostSince`, which reads the
// rows a card would: the hub's, or the payload's `fallback` ids when the rig
// cannot be identified.
import { readFile } from "node:fs/promises";

import {
  hubEntityIds,
  linkLostSince,
  resolveEntities,
} from "../../custom_components/nina_astrophotography/www/nina-entity-resolver.js";

const RUN = {
  resolveEntities,
  linkLostSince: (hass, deviceId) =>
    linkLostSince(hass, hubEntityIds(hass, deviceId) ?? hass.fallback),
};

const [payload, deviceId, fn = "resolveEntities"] = process.argv.slice(2);
const hass = JSON.parse(await readFile(payload, "utf8"));

process.stdout.write(JSON.stringify(RUN[fn](hass, deviceId || undefined)));

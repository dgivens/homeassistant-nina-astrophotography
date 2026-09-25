// Print `resolveEntities` output as JSON, for `test_entity_resolver.py`.
//
// Node so that the module under test is the one a browser loads; a Python
// reimplementation would only prove itself right.
//
// Usage: node resolve_entities.mjs <payload.json> [device_id]
import { readFile } from "node:fs/promises";

import { resolveEntities } from "../../custom_components/nina_astrophotography/www/nina-entity-resolver.js";

const [payload, deviceId] = process.argv.slice(2);
const hass = JSON.parse(await readFile(payload, "utf8"));

process.stdout.write(JSON.stringify(resolveEntities(hass, deviceId || undefined)));

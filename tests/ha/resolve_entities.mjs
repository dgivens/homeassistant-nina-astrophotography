// Run the shipped resolver against a registry snapshot taken from a real Home
// Assistant instance in `test_entity_resolver.py`, and print the map it returns
// as JSON.
//
// Node rather than a Python reimplementation of the same logic: the point is to
// exercise the module the browser actually loads. A second implementation would
// only ever prove itself right.
//
// Usage: node resolve_entities.mjs <payload.json> [device_id]
import { readFile } from "node:fs/promises";

import { resolveEntities } from "../../custom_components/nina_astrophotography/www/nina-entity-resolver.js";

const [payload, deviceId] = process.argv.slice(2);
const hass = JSON.parse(await readFile(payload, "utf8"));

process.stdout.write(JSON.stringify(resolveEntities(hass, deviceId || undefined)));

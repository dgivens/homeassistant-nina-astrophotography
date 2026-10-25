// Print `nina-units.js` results as JSON, for `test_card_units.py`.
//
// Node so that the module under test is the one a browser loads.
//
// Usage: node convert_units.mjs <cases.json>, each case `[fn, ...args]` with
// `fn` one of the module's exports.
import { readFile } from "node:fs/promises";

import * as units from "../../custom_components/nina_astrophotography/www/nina-units.js";

const cases = JSON.parse(await readFile(process.argv[2], "utf8"));

process.stdout.write(JSON.stringify(cases.map(([fn, ...args]) => units[fn](...args))));

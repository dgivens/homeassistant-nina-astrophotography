// Print `nina-units.js` conversions as JSON, for `test_card_units.py`.
//
// Node so that the module under test is the one a browser loads.
//
// Usage: node convert_units.mjs <cases.json>, each case `[fn, value, from, to]`
// with `fn` one of `convert` and `interval`.
import { readFile } from "node:fs/promises";

import * as units from "../../custom_components/nina_astrophotography/www/nina-units.js";

const cases = JSON.parse(await readFile(process.argv[2], "utf8"));

process.stdout.write(
  JSON.stringify(cases.map(([fn, value, from, to]) => units[fn](value, from, to))),
);

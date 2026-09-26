// Run `LinkGrace` through a script of steps under a fake clock, for
// `test_link_grace.py`.
//
// Node so that the module under test is the one a browser loads.
//
// Usage: node link_grace.mjs <scripts.json>, a script of steps per case name.
//
// Each step is `{"at": ms, "hold": since}` (since may be null) or
// `{"at": ms, "reset": true}`. Prints, per case and per `hold`, whether it held
// and the delay of the redraw it armed.
import { readFile } from "node:fs/promises";

import { LinkGrace } from "../../custom_components/nina_astrophotography/www/nina-entity-resolver.js";

const [path] = process.argv.slice(2);
const scripts = JSON.parse(await readFile(path, "utf8"));

let now = 0;
let armed = null;
Date.now = () => now;
globalThis.setTimeout = (_callback, delay) => {
  armed = delay;
  return 1;
};
globalThis.clearTimeout = () => {
  armed = null;
};

function run(steps) {
  const grace = new LinkGrace(() => {});
  const out = [];
  for (const step of steps) {
    now = step.at;
    if (step.reset) {
      grace.reset();
    } else {
      out.push([grace.hold(step.hold), armed]);
    }
  }
  return out;
}

const results = Object.entries(scripts).map(([name, steps]) => [name, run(steps)]);
process.stdout.write(JSON.stringify(Object.fromEntries(results)));

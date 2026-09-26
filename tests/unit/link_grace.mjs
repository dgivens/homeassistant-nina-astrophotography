// Run `LinkGrace` through scripts of steps on a fake clock, for
// `test_link_grace.py`.
//
// Usage: node link_grace.mjs <scripts.json>, a list of steps per case name.
// A step is `{"at": ms, "hold": since}` or `{"at": ms, "reset": true}`. Prints,
// per case, `[held, armed]` for each `hold`.
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

/**
 * Print a card's rendered HTML and every canvas op, for one scenario.
 *
 *   node tools/card-harness/ops.mjs <card.js> <scenario> [--html]
 *
 * The point is the diff. Record a card before a refactor and after it; an
 * output that has not moved says the change was a refactor, and a diff is the
 * list of what it altered:
 *
 *   CARD=custom_components/nina_astrophotography/www/nina-sky-map-card.js
 *   git show <before>:$CARD > /tmp/before.js
 *   node tools/card-harness/ops.mjs /tmp/before.js tracking --card=nina-sky-map-card \
 *     > /tmp/before.txt
 *   node tools/card-harness/ops.mjs $CARD tracking | diff /tmp/before.txt -
 *
 * The card is a path, so an older copy of one can be run against the same data.
 * Its scenarios come from `scenarios/<card name>.mjs`, named after the card
 * rather than the path — hence `--card` when the two differ, as they do for a
 * copy pulled out of git.
 */

import { readFile } from "node:fs/promises";
import { basename, dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { install } from "./dom.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const DUMP = join(HERE, "..", "..", "tests", "ha", "snapshots", "card_states.json");

const [card, name, ...flags] = process.argv.slice(2);
if (!card || !name) {
  console.error("usage: node ops.mjs <card.js> <scenario> [--card=<name>] [--html]");
  process.exit(2);
}

const dump = JSON.parse(await readFile(DUMP, "utf8"));

const which =
  flags.find((flag) => flag.startsWith("--card="))?.slice("--card=".length) ??
  basename(card, ".js");
const file = join(HERE, "scenarios", `${which}.mjs`);
let scenarios;
try {
  ({ scenarios } = await import(pathToFileURL(file).href));
} catch {
  console.error(`no scenarios for "${which}" (${file}) — pass --card=<card name>`);
  process.exit(2);
}
const scenario = scenarios[name];
if (!scenario) {
  console.error(`no scenario "${name}" — have: ${Object.keys(scenarios).join(", ")}`);
  process.exit(2);
}

const { log, element, html, nodes, frame } = install(scenario.viewport);

// The card registers its element as a side effect of being imported, and logs
// its version banner doing it. Stdout is the record, so the banner goes aside.
const banner = console.info;
console.info = (...args) => process.stderr.write(`${args.join(" ")}\n`);
await import(pathToFileURL(card).href);
console.info = banner;
const Card = element();
if (!Card) {
  console.error(`${card} defined no custom element`);
  process.exit(1);
}

const instance = new Card();
instance.setConfig(scenario.config ?? {});
const hass = scenario.hass(dump);
// The image panel signs each image path before loading it. The path names the
// entity the proxy resolves a rig by, so the request is the record; the answer
// is the path unsigned, which nothing serves.
hass.callWS = async (message) => {
  log.push(`callWS ${JSON.stringify(message)}`);
  return { path: message.path };
};
instance.hass = hass;
// Node fires no animation frames, so the one the render queued is run here;
// a scenario's `draw` replaces it — see the README.
if (scenario.draw) {
  scenario.draw(instance);
} else {
  frame();
}

// A load the card started — a signed path, then the image behind it — settles
// on later ticks, and what it leaves on screen is part of the output.
await new Promise((resolve) => setTimeout(resolve));

if (flags.includes("--html")) {
  console.log("--- html ---");
  console.log(html().replace(/\s+/g, " ").trim());
  console.log("--- nodes ---");
  console.log(nodes());
  console.log("--- canvas ---");
}
console.log(log.join("\n"));

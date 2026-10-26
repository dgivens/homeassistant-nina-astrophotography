// Run `LinkView` through scripts of the `hass` a card is handed, for
// `test_link_view.py`.
//
// Usage: node link_view.mjs <scripts.json>, a list of steps per case name. A
// step names a rig state from `RIG` below, or is "reset". Prints, per case,
// `[drawn, since, lost, stale]` for each read, `drawn` naming the state drawn.
import { readFile } from "node:fs/promises";

import { LinkView } from "../../custom_components/nina_astrophotography/www/nina-entity-resolver.js";

const HUB = "binary_sensor.rig_sequencer_running";
const REACHABLE = "binary_sensor.rig_reachable";
const QUIET_AT = "2026-10-26T02:00:00+00:00";

const row = (state, changed) => ({ state, attributes: {}, last_changed: changed });
// The rig as the coordinator publishes it: answering, one missed poll inside
// the grace, and past it.
const RIG = {
  live: { [HUB]: row("on"), [REACHABLE]: row("on") },
  quiet: { [HUB]: row("on"), [REACHABLE]: row("off", QUIET_AT) },
  lost: { [HUB]: row("unavailable", QUIET_AT), [REACHABLE]: row("off", QUIET_AT) },
};

const [path] = process.argv.slice(2);
const scripts = JSON.parse(await readFile(path, "utf8"));

function run(steps) {
  const view = new LinkView();
  const out = [];
  for (const step of steps) {
    if (step === "reset") {
      view.reset();
      continue;
    }
    const { hass, since, lost, stale } = view.read(
      { name: step, states: RIG[step] }, [HUB], REACHABLE);
    out.push([hass.name, since, lost, stale]);
  }
  return out;
}

const results = Object.entries(scripts).map(([name, steps]) => [name, run(steps)]);
process.stdout.write(JSON.stringify(Object.fromEntries(results)));

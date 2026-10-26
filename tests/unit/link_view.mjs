// Run `LinkView` through scripts of the `hass` a card is handed, for
// `test_link_view.py`.
//
// Usage: node link_view.mjs <scripts.json>, a list of steps per case name. A
// step names a rig state from `RIG` below, or is "reset". Prints, per case,
// `[drawn, since, lost, stale]` for each read, `drawn` naming the state drawn.
import { readFile } from "node:fs/promises";

import {
  LinkView,
  RigEntities,
} from "../../custom_components/nina_astrophotography/www/nina-entity-resolver.js";

const HELD = "binary_sensor.rig_sequencer_running";
const REACHABLE = "binary_sensor.rig_reachable";
const QUIET_AT = "2026-10-26T02:00:00+00:00";

const row = (state, changed, attributes = {}) =>
  ({ state, attributes, last_changed: changed });
// The rig as the coordinator publishes it: answering, one missed poll inside
// the grace, and past it; with `reachable` disabled; and as core restores it
// for an entry that failed to load.
const RIG = {
  live: { [HELD]: row("on"), [REACHABLE]: row("on") },
  quiet: { [HELD]: row("on"), [REACHABLE]: row("off", QUIET_AT) },
  lost: { [HELD]: row("unavailable", QUIET_AT), [REACHABLE]: row("off", QUIET_AT) },
  lost_unreported: { [HELD]: row("unavailable", QUIET_AT) },
  failed: { [REACHABLE]: row("unavailable", QUIET_AT, { restored: true }) },
};

const [path] = process.argv.slice(2);
const scripts = JSON.parse(await readFile(path, "utf8"));

function run(steps) {
  // No registry, so every id is the `rig` prefix templated onto its key.
  const rig = new RigEntities("rig");
  const view = new LinkView();
  const out = [];
  for (const step of steps) {
    if (step === "reset") {
      view.reset();
      continue;
    }
    const { hass, since, lost, stale } = view.read({ name: step, states: RIG[step] }, rig);
    out.push([hass.name, since, lost, stale]);
  }
  return out;
}

const results = Object.entries(scripts).map(([name, steps]) => [name, run(steps)]);
process.stdout.write(JSON.stringify(Object.fromEntries(results)));

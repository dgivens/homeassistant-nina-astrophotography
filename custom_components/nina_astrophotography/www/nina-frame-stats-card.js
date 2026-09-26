/**
 * N.I.N.A. Frame Statistics Card
 * Displays per-frame HFR trend, star count, ADU sparklines and per-filter
 * frame counts for the session's recent lights, published by the integration
 * so they survive a page reload.
 *
 * Ships with the integration and registers itself as a dashboard resource —
 * nothing to copy or add under Resources. One rig needs no configuration at
 * all: the card finds its own session sensors in the registry.
 *   type: custom:nina-frame-stats-card
 *   device_id: abc123      # which rig, for two or more; any one of its devices
 *   prefix: n_i_n_a        # fallback only, for the entities that cannot resolve
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import { resolveEntities } from "./nina-entity-resolver.js";
import { quantityIn } from "./nina-units.js";

const VERSION = "2.0.0";

// A reading Home Assistant has no value for is not a number to print.
function shown(value) {
  return value === null || value === undefined || value === "—"
    || value === "unknown" || value === "unavailable" ? "—" : value;
}

// A filter keeps its colour from night to night, whichever others the session
// used: the chips are the charts' legend, and an imager reads R as red. The
// common passbands take their own hue; Ha is rose rather than red so that an
// HaRGB night keeps it apart from R, and SII sits far enough from B that a
// deuteranope can still tell them apart.
const PASSBANDS = {
  L: "#e4e7ed", R: "#f0524a", G: "#5fcf6a", B: "#4f8ff7",
  Ha: "#ff6fa8", OIII: "#35cfd4", SII: "#c65cd6",
};
const ALIASES = [
  ["L", ["l", "lum", "lumi", "luminance", "luminence"]],
  ["R", ["r", "red"]],
  ["G", ["g", "grn", "green"]],
  ["B", ["b", "blu", "blue"]],
  ["Ha", ["h", "ha", "halpha", "hα"]],
  ["OIII", ["o", "oiii", "o3"]],
  ["SII", ["s", "sii", "s2"]],
];
const PASSBAND_OF = new Map(
  ALIASES.flatMap(([band, keys]) => keys.map((key) => [key, band])));

// A slot that passes the whole visible band reads as luminance, but only
// stands in for one: where the wheel also holds an L, the L keeps its hue.
const STAND_INS = new Set(["clear", "open", "empty", "none", "uv"]);
const UV_IR_CUT = /uvir|iruv|ircut|irblock/;

// A slot is as often named for its maker as for its passband.
const MAKERS = /\b(astrodon|astronomik|antlia|baader|chroma|idas|optolong|zwo)\b/g;

// Case, a bandwidth or size, a note, a maker and punctuation do not change the
// passband: "Ha 3nm", "H-alpha", "Chroma Ha 5nm" and "HA" are one filter.
function stripped(name) {
  return String(name).toLowerCase()
    .replace(/\(.*?\)/g, "")
    .replace(/\d+([.,]\d+)?\s*(nm|mm)\b|\d+([.,]\d+)?\s*"/g, "")
    .replace(MAKERS, "");
}

function filterKey(name) {
  return stripped(name).replace(/[^\p{L}\p{N}]/gu, "");
}

// A bare trailing number is read as a bandwidth only where what is left is a
// passband — "Ha7", Astronomik's "L-2" — so it never turns a dual-band name
// into one.
function lookup(key) {
  const bare = key.replace(/\d+$/, "");
  if (PASSBAND_OF.has(key)) return { band: PASSBAND_OF.get(key), standIn: false };
  if (PASSBAND_OF.has(bare)) return { band: PASSBAND_OF.get(bare), standIn: false };
  if (STAND_INS.has(key) || STAND_INS.has(bare) || UV_IR_CUT.test(key)) {
    return { band: "L", standIn: true };
  }
  return null;
}

// The passband a name reads as, as `{band, standIn}`, or null. A name whose
// last word is its only passband word reads as that one — "Deep-Sky R",
// "Astrodon E-Series B", "Antlia 3nm Pro Ha" — but "L Pro" or "Ha OIII" do not.
function passband(name) {
  const whole = lookup(filterKey(name));
  if (whole !== null) return whole;
  const words = stripped(name).split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const found = words.map(lookup);
  const last = found[found.length - 1];
  return last && found.filter(Boolean).length === 1 ? last : null;
}

// Any other filter. Eight, so that an 8-position wheel of filters matching no
// passband still draws every slot apart. Chosen for perceptual distance from
// each other and the passband hues on the card's background, weighing hue and
// saturation over lightness since a thin line shows those most, with and
// without a colour-vision deficiency, and none pale enough to pass for L's
// white. Ordered most distinct first.
const OTHER_COLOURS = [
  "#daff24", "#ff00bf", "#24ffc8", "#da886c",
  "#0db9f2", "#ff6a00", "#e1da89", "#9c6bff",
];

// The passband hues each spare could pass for on a thin line: CIEDE2000 below
// 12 in normal vision, or below 7 under a colour-vision deficiency. On a wheel
// that already draws some of them, a spare goes back by how many.
const TWINS = new Map([
  ["#ff00bf", [PASSBANDS.Ha, PASSBANDS.OIII, PASSBANDS.SII]],
  ["#24ffc8", [PASSBANDS.OIII]],
  ["#da886c", [PASSBANDS.R, PASSBANDS.G, PASSBANDS.Ha]],
  ["#0db9f2", [PASSBANDS.B, PASSBANDS.OIII, PASSBANDS.SII]],
  ["#ff6a00", [PASSBANDS.R]],
  ["#e1da89", [PASSBANDS.G]],
  ["#9c6bff", [PASSBANDS.B, PASSBANDS.SII]],
]);

function spares(drawn) {
  const twins = (colour) => (TWINS.get(colour) ?? []).filter((hue) => drawn.has(hue)).length;
  return [...OTHER_COLOURS].sort((a, b) => twins(a) - twins(b));
}

// A light with no filter name among named ones, which no chip uses.
const NO_FILTER = "#8a909c";

// FNV-1a: stable across browsers and sessions.
function nameHash(text) {
  let hash = 0x811c9dc5;
  for (const ch of text) hash = Math.imul(hash ^ ch.codePointAt(0), 0x01000193);
  return hash >>> 0;
}

// A wheel's names are whatever its owner typed — "HaOiii", "LPro" — so most
// match no passband. Its slot list is the stable set. A slot named for a
// passband takes that passband's hue, then a stand-in such as "Clear" takes
// L's if no slot is named L; every other slot, a second slot for a passband
// included, takes the next spare in slot order, so no two chips look alike
// while spares remain. A colour follows the slot, not the glass in it, and
// once Home Assistant has seen the wheel it changes only when the wheel is
// reconfigured.
function wheelColours(slots) {
  const colours = new Map();
  const unique = [...new Set(slots)];
  for (const standIns of [false, true]) {
    for (const slot of unique) {
      const match = passband(slot);
      const hue = match && PASSBANDS[match.band];
      if (match?.standIn === standIns && !colours.has(slot)
          && ![...colours.values()].includes(hue)) {
        colours.set(slot, hue);
      }
    }
  }
  const order = spares(new Set(colours.values()));
  let next = 0;
  for (const slot of unique) {
    if (!colours.has(slot)) colours.set(slot, order[next++ % order.length]);
  }
  return colours;
}

// Every name's colour: the wheel's slots, then any name the wheel does not
// list — a slot renamed since the light was taken — which takes its
// passband's hue, or else a spare the wheel neither uses nor draws a near
// twin of, in name order. Those names change only with the wheel, so the order
// is as stable as the wheel. With no wheel to read, each name is hashed
// instead: a night's names then grow as it goes, and an order would move them.
function filterColours(slots, names) {
  const colours = wheelColours(slots);
  const drawn = new Set(colours.values());
  const free = spares(drawn).filter((c) => !drawn.has(c));
  const unlisted = [...new Set(names)].filter((n) => n !== null && !colours.has(n)).sort();
  let next = 0;
  for (const name of unlisted) {
    const match = passband(name);
    if (match !== null) {
      colours.set(name, PASSBANDS[match.band]);
    } else if (slots.length && free.length) {
      colours.set(name, free[next++ % free.length]);
    } else {
      const key = filterKey(name) || String(name).toLowerCase();
      colours.set(name, OTHER_COLOURS[nameHash(key) % OTHER_COLOURS.length]);
    }
  }
  return colours;
}

const STYLE = `
  :host {
    --card-bg: var(--ha-card-background, var(--card-background-color, #1c1c2e));
    --card-border: var(--divider-color, rgba(255,255,255,0.1));
    --accent: #7b8de8;
    --accent2: #5bcfcf;
    --warn: #f4a261;
    --danger: #e76f51;
    --success: #57cc99;
    --muted: rgba(255,255,255,0.45);
    --text: rgba(255,255,255,0.92);
    font-family: var(--primary-font-family, Roboto, sans-serif);
  }
  ha-card {
    background: var(--card-bg);
    color: var(--text);
    border: 1px solid var(--card-border);
    border-radius: 16px;
    overflow: hidden;
    padding: 0;
  }
  .header {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 18px 10px;
    border-bottom: 1px solid var(--card-border);
    background: rgba(123,141,232,0.08);
  }
  .header .title { font-size: 1.05rem; font-weight: 600; flex: 1; }
  .header .subtitle { font-size: 0.72rem; color: var(--muted); margin-top: 1px; }
  .body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 14px; }

  /* ── Stat row ── */
  .stat-row { display: flex; gap: 8px; }
  .stat-box {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 10px 12px;
    display: flex; flex-direction: column; gap: 2px;
  }
  .stat-box .label { font-size: 0.6rem; font-weight: 600; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }
  .stat-box .value { font-size: 1.05rem; font-weight: 700; }
  .stat-box .sub { font-size: 0.65rem; color: var(--muted); }
  .stat-box.trend-improving { border-color: rgba(87,204,153,0.4); }
  .stat-box.trend-degrading { border-color: rgba(231,111,81,0.4); }
  .stat-box.trend-stable    { border-color: rgba(91,207,207,0.3); }

  /* ── Chart section ── */
  .chart-section { display: flex; flex-direction: column; gap: 4px; }
  .chart-label { font-size: 0.62rem; font-weight: 700; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }
  canvas { width: 100%; border-radius: 6px; display: block; }

  /* ── Filter bar ── */
  .filter-bar { display: flex; flex-wrap: wrap; gap: 6px; }
  .filter-chip {
    display: flex; align-items: center; gap: 5px;
    border-radius: 20px; padding: 4px 10px;
    font-size: 0.7rem; font-weight: 600;
    border: 1px solid transparent;
  }
  .filter-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

  /* ── No data ── */
  .no-data {
    text-align: center; padding: 28px 16px;
    color: var(--muted); font-size: 0.85rem;
  }
  .no-data .icon { font-size: 2rem; margin-bottom: 8px; }
`;

// Below 3% of the rolling mean the trend is noise. Relative, not absolute:
// 0.05 px is coarse on a 1.3 px rig and meaningless on a 3.5 px one.
const TREND_EPSILON = 0.03;

function hfrTrend(recent, previous, delta) {
  if (recent === null || previous === null) return "unknown";
  if (Math.abs(delta) < TREND_EPSILON * recent) return "stable";
  return delta < 0 ? "improving" : "degrading";
}

class NinaFrameStatsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hfr = [];
    this._stars = [];
    this._adu = [];
    this._filters = [];
    this._boundaries = [];
  }

  setConfig(config) {
    this._config = config || {};
    this._prefix = this._config.prefix || DEFAULT_PREFIX;
    // A new config may name a different rig: make the next `set hass` re-resolve.
    this._resolved = {};
    this._resolvedFrom = null;
  }

  set hass(hass) {
    this._hass = hass;
    // The frontend replaces `hass.entities` only when the registry itself
    // changes, so this walks it on a rename, not on every state tick.
    // `hass.devices` needs no second memo key: every device change that alters
    // the map arrives with an entity-registry change too.
    if (hass.entities !== this._resolvedFrom) {
      this._resolvedFrom = hass.entities;
      this._resolved = resolveEntities(hass, this._config.device_id);
    }
    this._updateData();
    this._render();
  }

  // The resolved entity id for a `translation_key`, falling back to a prefixed
  // `slug` when there is nothing to resolve: an entity with no translation key,
  // a disabled one, or a rig the resolver cannot identify.
  //
  // `slug` is the entity-id suffix — the device name plus the entity name — so
  // it is not always the key. A hub sensor adds nothing past the instance
  // name; the filter wheel's select adds its device's.
  _eid(domain, key, slug = key) {
    return this._resolved[`${domain}.${key}`] ?? `${domain}.${this._prefix}_${slug}`;
  }

  _state(id, fallback = null) {
    const e = this._hass?.states[id];
    return e ? e.state : fallback;
  }

  _attr(id, attr, fallback = null) {
    const e = this._hass?.states[id];
    return e ? (e.attributes[attr] ?? fallback) : fallback;
  }

  // The series is the last-HFR sensor's `recent_lights` attribute (oldest
  // first, bounded, lights only), re-read on every update so a page reload
  // keeps it. An unavailable entity carries no attributes at all, so one
  // failed poll keeps the last series rather than blanking the charts.
  _updateData() {
    const entity = this._hass?.states[this._eid("sensor", "last_image_hfr")];
    if (entity?.state === "unavailable") return;
    const lights = entity?.attributes.recent_lights ?? [];
    this._hfr = lights.map((light) => light.hfr ?? null);
    this._stars = lights.map((light) => light.stars ?? null);
    this._adu = lights.map((light) => light.mean ?? null);
    this._filters = lights.map((light) => light.filter ?? null);
    // A new target or exposure length moves star count and ADU by whole
    // factors — a galaxy field against a Milky Way one — which would
    // otherwise read as clouds rolling in.
    this._boundaries = lights.flatMap((light, i) =>
      i > 0 && (light.target !== lights[i - 1].target
                || light.exposure !== lights[i - 1].exposure) ? [i] : []);
  }

  _mean(values) {
    const known = values.filter((v) => v !== null);
    return known.length
      ? known.reduce((total, v) => total + v, 0) / known.length
      : null;
  }

  _render() {
    const h = this._hass;
    if (!h) return;

    // `_state`'s fallback covers a missing entity only; `shown` covers one
    // that exists and reads `unknown` or `unavailable`, which would otherwise
    // print as the word.
    //
    // Lights, not frames: the count sensor's state includes the flats, and
    // everything beside it — the integration, the HFR figures, the chips — is
    // lights only.
    const lightCount   = shown(this._attr(this._eid("sensor", "session_image_count"), "light_count"));
    // Durations in the units printed beside them, whichever each is shown in.
    const hours        = quantityIn(this._hass, this._eid("sensor", "session_integration_time"), "h");
    const integration  = hours === null ? "—" : hours.toFixed(1);
    const lastHfr      = this._state(this._eid("sensor", "last_image_hfr"), "—");
    const lastStars    = shown(this._state(this._eid("sensor", "last_image_star_count")));
    const lastFilter   = shown(this._state(this._eid("sensor", "last_image_filter")));
    const exposure     = quantityIn(this._hass, this._eid("sensor", "last_image_exposure"), "s");
    const lastExposure = exposure ? exposure.toFixed(0) : "—";
    const avgHfrId = this._eid("sensor", "session_avg_hfr");
    const sessionAvgHfr = this._state(avgHfrId, "—");
    const sessionBestHfr = this._state(this._eid("sensor", "session_best_hfr"), "—");
    // The session breakdown rides on the average-HFR sensor, one row per
    // filter: {count, integration_hours, hfr_mean}.
    const byFilter = this._attr(avgHfrId, "by_filter", {}) || {};

    // The last five frames against the five before them, in the newest
    // frame's filter only: filters differ by tenths of a pixel, so an LRGB or
    // SHO rotation would otherwise read as a trend. No trend until ten.
    const trendFilter = this._filters[this._filters.length - 1] ?? null;
    const sameFilter = this._hfr.filter(
      (hfr, i) => hfr !== null && this._filters[i] === trendFilter);
    const rolling  = this._mean(sameFilter.slice(-10));
    const recent   = this._mean(sameFilter.slice(-5));
    const previous = sameFilter.length < 10
      ? null : this._mean(sameFilter.slice(-10, -5));
    const trendDelta = recent !== null && previous !== null ? recent - previous : 0;
    const trend = hfrTrend(recent, previous, trendDelta);
    const rollingHfr = rolling === null ? "—" : rolling.toFixed(2);

    const trendIcon = trend === "improving" ? "↘" : trend === "degrading" ? "↗" : "→";
    const trendLabel = trend === "improving"
      ? `${trendIcon} Improving (${trendDelta.toFixed(3)} px)`
      : trend === "degrading"
      ? `${trendIcon} Degrading (+${Math.abs(trendDelta).toFixed(3)} px)`
      : trend === "stable"
      ? `${trendIcon} Stable`
      : "—";

    const hasData = this._hfr.some(v => v !== null);

    const slots = this._attr(this._eid("select", "filter", "filter_wheel_filter"), "options") ?? [];
    const colours = filterColours(slots, [...Object.keys(byFilter), ...this._filters]);
    // In wheel order, as an imager reads a wheel; names it does not list last.
    const slotOf = (name) => (slots.includes(name) ? slots.indexOf(name) : slots.length);
    const filterEntries = Object.entries(byFilter).sort(([a], [b]) => slotOf(a) - slotOf(b));
    const chipless = filterEntries.length === 0;
    // N.I.N.A. names a filter only while a wheel is connected, so a night with
    // no chips and no named light is usually a one-shot-colour camera: its
    // lights have nothing to be told apart from, and null leaves each to the
    // chart's own colour. The series has a say as well as the chips, so a
    // breakdown that goes missing cannot recolour a wheel's dropout.
    const ownColours = chipless && this._filters.every((name) => name === null);
    const lightColours = this._filters.map((name) =>
      (ownColours ? null : name === null ? NO_FILTER : colours.get(name)));
    const filterChipsHtml = filterEntries.map(([name, row]) => {
      const colour = colours.get(name);
      return `<div class="filter-chip" style="background:${colour}22;border-color:${colour}55">
        <div class="filter-dot" style="background:${colour}"></div>
        <span>${name}: ${row?.count ?? 0}</span>
      </div>`;
    }).join("");

    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <span style="font-size:1.3rem">📊</span>
          <div>
            <div class="title">Frame Statistics</div>
            <div class="subtitle">${lightCount} lights · ${integration} h · ${lastFilter}</div>
          </div>
        </div>
        <div class="body">
          ${!hasData ? `
            <div class="no-data">
              <div class="icon">🔭</div>
              <div>Waiting for lights…</div>
              <div style="font-size:0.72rem;margin-top:4px">Statistics will appear once N.I.N.A. saves a light frame</div>
            </div>
          ` : `
            <!-- KPI row -->
            <div class="stat-row">
              <div class="stat-box trend-${trend}">
                <div class="label">Last HFR</div>
                <div class="value">${parseFloat(lastHfr) ? parseFloat(lastHfr).toFixed(2) : "—"} <span style="font-size:0.7rem;font-weight:400;color:var(--muted)">px</span></div>
                <div class="sub">Rolling avg: ${parseFloat(rollingHfr) ? parseFloat(rollingHfr).toFixed(2) : "—"} px</div>
              </div>
              <div class="stat-box">
                <div class="label">Stars</div>
                <div class="value">${lastStars}</div>
                <div class="sub">Last frame</div>
              </div>
              <div class="stat-box">
                <div class="label">Exposure</div>
                <div class="value">${lastExposure} <span style="font-size:0.7rem;font-weight:400;color:var(--muted)">s</span></div>
                <div class="sub">${lastFilter}</div>
              </div>
            </div>

            <!-- Trend + session row -->
            <div class="stat-row">
              <div class="stat-box trend-${trend}">
                <div class="label">HFR Trend</div>
                <div class="value" style="font-size:0.85rem">${trendLabel}</div>
                <div class="sub">Last 5 vs prev 5 ${trendFilter ?? ""} frames</div>
              </div>
              <div class="stat-box">
                <div class="label">Session avg / best</div>
                <div class="value" style="font-size:0.85rem">${parseFloat(sessionAvgHfr) ? parseFloat(sessionAvgHfr).toFixed(2) : "—"} / ${parseFloat(sessionBestHfr) ? parseFloat(sessionBestHfr).toFixed(2) : "—"} <span style="font-size:0.65rem;color:var(--muted)">px</span></div>
                <div class="sub">${lightCount} lights</div>
              </div>
            </div>

            <!-- HFR sparkline -->
            <div class="chart-section">
              <div class="chart-label">HFR per frame</div>
              <canvas id="hfr-chart" height="64"></canvas>
            </div>

            <!-- Stars sparkline -->
            <div class="chart-section">
              <div class="chart-label">Star count per frame</div>
              <canvas id="stars-chart" height="48"></canvas>
            </div>

            <!-- ADU sparkline -->
            <div class="chart-section">
              <div class="chart-label">Mean ADU per frame</div>
              <canvas id="adu-chart" height="48"></canvas>
            </div>

            <!-- Filter breakdown -->
            ${!chipless ? `
              <div class="chart-section">
                <div class="chart-label">Frames per filter</div>
                <div class="filter-bar">${filterChipsHtml}</div>
              </div>
            ` : ""}
          `}
        </div>
      </ha-card>
    `;

    this.shadowRoot.innerHTML = html;

    if (hasData) {
      requestAnimationFrame(() => {
        this._drawSparkline("hfr-chart", this._hfr, "#7b8de8", true, lightColours);
        this._drawSparkline("stars-chart", this._stars, "#5bcfcf", false, lightColours);
        this._drawSparkline("adu-chart", this._adu, "#f4a261", false, lightColours);
      });
    }
  }

  _drawSparkline(canvasId, data, fillColour, showAvgLine, colours) {
    const canvas = this.shadowRoot.getElementById(canvasId);
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth || 300;
    const H = canvas.offsetHeight || 64;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const valid = data.filter(v => v !== null && v !== undefined);
    if (valid.length < 2) return;

    const minVal = Math.min(...valid) * 0.95;
    const maxVal = Math.max(...valid) * 1.05;
    const range = maxVal - minVal || 1;
    const pad = { l: 4, r: 4, t: 6, b: 4 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    const xOf = i => pad.l + (i / (data.length - 1)) * plotW;
    const yOf = v => v === null || v === undefined
      ? null
      : pad.t + plotH - ((v - minVal) / range) * plotH;

    // Subtle grid
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    ctx.lineWidth = 0.5;
    for (let g = 0; g <= 3; g++) {
      const y = pad.t + (g / 3) * plotH;
      ctx.beginPath(); ctx.moveTo(pad.l, y); ctx.lineTo(W - pad.r, y); ctx.stroke();
    }

    // Target or exposure changes, midway between the two frames either side.
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 3]);
    for (const i of this._boundaries) {
      const x = (xOf(i - 1) + xOf(i)) / 2;
      ctx.beginPath(); ctx.moveTo(x, pad.t); ctx.lineTo(x, H - pad.b); ctx.stroke();
    }
    ctx.setLineDash([]);

    // Filled area under line
    ctx.beginPath();
    let started = false;
    const firstValid = data.findIndex(v => v !== null);
    for (let i = firstValid; i < data.length; i++) {
      const y = yOf(data[i]);
      if (y === null) continue;
      if (!started) { ctx.moveTo(xOf(i), y); started = true; }
      else ctx.lineTo(xOf(i), y);
    }
    // Close to baseline
    const lastValid = data.length - 1 - [...data].reverse().findIndex(v => v !== null);
    ctx.lineTo(xOf(lastValid), H - pad.b);
    ctx.lineTo(xOf(firstValid), H - pad.b);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, pad.t, 0, H);
    grad.addColorStop(0, fillColour + "44");
    grad.addColorStop(1, fillColour + "06");
    ctx.fillStyle = grad;
    ctx.fill();

    // An unnamed light beside named ones is grey, and hollow too, since an L
    // dot drawn at 60% is much the same grey.
    const colourOf = (i) => colours[i] ?? fillColour;
    const hollow = (i) => colours[i] === NO_FILTER;

    // Main line, coloured by filter.
    for (let i = 1; i < data.length; i++) {
      const y0 = yOf(data[i - 1]);
      const y1 = yOf(data[i]);
      if (y0 === null || y1 === null) continue;
      const col = colourOf(i);
      ctx.beginPath();
      ctx.moveTo(xOf(i - 1), y0);
      ctx.lineTo(xOf(i), y1);
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.8;
      ctx.stroke();
    }

    // Average line
    if (showAvgLine && valid.length > 0) {
      const avg = valid.reduce((a, b) => a + b, 0) / valid.length;
      const yAvg = yOf(avg);
      if (yAvg !== null) {
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = "rgba(255,255,255,0.25)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.l, yAvg);
        ctx.lineTo(W - pad.r, yAvg);
        ctx.stroke();
        ctx.setLineDash([]);
        // avg label
        ctx.fillStyle = "rgba(255,255,255,0.4)";
        ctx.font = "9px sans-serif";
        ctx.fillText(`avg ${avg.toFixed(2)}`, W - pad.r - 48, yAvg - 3);
      }
    }

    // Dots on each data point
    for (let i = 0; i < data.length; i++) {
      const y = yOf(data[i]);
      if (y === null) continue;
      const isLast = i === data.length - 1;
      const col = colourOf(i);
      ctx.beginPath();
      ctx.arc(xOf(i), y, isLast ? 3.5 : 2, 0, Math.PI * 2);
      if (hollow(i)) {
        ctx.strokeStyle = col;
        ctx.lineWidth = 1.2;
        ctx.stroke();
        continue;
      }
      ctx.fillStyle = isLast ? col : col + "99";
      ctx.fill();
      if (isLast) {
        ctx.strokeStyle = "rgba(255,255,255,0.6)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }

    // Latest value label
    const lastY = yOf(data[data.length - 1]);
    if (lastY !== null) {
      const v = data[data.length - 1];
      const label = typeof v === "number" && v > 100
        ? Math.round(v).toString()
        : typeof v === "number"
        ? v.toFixed(2)
        : "";
      ctx.font = "bold 10px sans-serif";
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.fillText(label, xOf(data.length - 1) + 4, Math.max(lastY, 14));
    }
  }

  getCardSize() { return 7; }

  static getConfigForm() { return configForm(); }

  static getStubConfig() { return {}; }
}

// Guarded: a stale 1.4.5 `/local/nina-frame-stats-card.js` resource left over
// from a manual install defines the same tag. A second `define` throws
// `NotSupportedError` and aborts the rest of this module — including the
// `customCards.push` below — so whichever copy loses the race silently
// disappears from the picker instead of just being redundant.
if (!customElements.get("nina-frame-stats-card")) {
  customElements.define("nina-frame-stats-card", NinaFrameStatsCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-frame-stats-card",
  name: "N.I.N.A. Frame Statistics Card",
  description: "Live per-frame HFR trend, star count, ADU, and filter breakdown.",
  preview: true,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-FRAME-STATS-CARD %c v${VERSION} `,
  "background:#5bcfcf;color:#1c1c2e;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px",
  "background:#1c1c2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

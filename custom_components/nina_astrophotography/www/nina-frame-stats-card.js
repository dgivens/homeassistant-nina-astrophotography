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
import { inUnit, quantity } from "./nina-units.js";

const VERSION = "2.0.0";

// A reading Home Assistant has no value for is not a number to print.
function shown(value) {
  return value === null || value === undefined || value === "—"
    || value === "unknown" || value === "unavailable" ? "—" : value;
}

const FILTER_COLOURS = [
  "#7b8de8", "#5bcfcf", "#f4a261", "#57cc99",
  "#e76f51", "#a8dadc", "#c77dff", "#ffd166",
];

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
  // it is not always the key. On this card it always is: every read is a hub
  // sensor, and the hub adds nothing past the instance name.
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
    const hours        = inUnit(quantity(this._hass, this._eid("sensor", "session_integration_time")), "h");
    const integration  = hours === null ? "—" : hours.toFixed(1);
    const lastHfr      = this._state(this._eid("sensor", "last_image_hfr"), "—");
    const lastStars    = shown(this._state(this._eid("sensor", "last_image_star_count")));
    const lastFilter   = shown(this._state(this._eid("sensor", "last_image_filter")));
    const lastExposure = inUnit(quantity(this._hass, this._eid("sensor", "last_image_exposure")), "s");
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

    // One colour per filter, shared by the chips and the sparklines, so the
    // chips are the charts' legend: the session's filters in the chips' order,
    // then any the series holds that the breakdown does not.
    this._colours = new Map();
    for (const name of [...Object.keys(byFilter), ...this._filters]) {
      if (name !== null && !this._colours.has(name)) {
        this._colours.set(name, FILTER_COLOURS[this._colours.size % FILTER_COLOURS.length]);
      }
    }

    const filterEntries = Object.entries(byFilter);
    const filterChipsHtml = filterEntries.map(([name, row]) => {
      const colour = this._colours.get(name);
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
                <div class="value">${lastExposure ? lastExposure.toFixed(0) : "—"} <span style="font-size:0.7rem;font-weight:400;color:var(--muted)">s</span></div>
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
            ${filterEntries.length > 0 ? `
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
        this._drawSparkline("hfr-chart", this._hfr, "#7b8de8", true);
        this._drawSparkline("stars-chart", this._stars, "#5bcfcf", false);
        this._drawSparkline("adu-chart", this._adu, "#f4a261", false);
      });
    }
  }

  _drawSparkline(canvasId, data, defaultColor, showAvgLine) {
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
    grad.addColorStop(0, defaultColor + "44");
    grad.addColorStop(1, defaultColor + "06");
    ctx.fillStyle = grad;
    ctx.fill();

    // A frame with no filter — a rig without a wheel — takes the chart's own
    // colour. It has no chip; in a night that mixes the two, that colour can
    // coincide with the first few filters' chips.
    const colourOf = (i) => this._colours.get(this._filters[i]) ?? defaultColor;

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

/**
 * N.I.N.A. Frame Statistics Card
 * Displays live per-frame HFR trend, star count, ADU sparklines and
 * per-filter frame counts — all driven by IMAGE-SAVE WebSocket events.
 *
 * Installation:
 *   1. Copy to /config/www/nina-frame-stats-card.js
 *   2. Add resource: /local/nina-frame-stats-card.js (JavaScript Module)
 *   3. Add card:
 *        type: custom:nina-frame-stats-card
 */

const VERSION = "1.0.0";

// Entity ids are prefixed with the instance name (device names drive entity
// ids since 2.0). Default "nina"; override with `prefix:` in the card config
// when you run more than one N.I.N.A. instance.
function withPrefix(entityId, prefix) {
  const dot = entityId.indexOf(".");
  return entityId.slice(0, dot + 1) + (prefix || "nina") + "_" + entityId.slice(dot + 1);
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

class NinaFrameStatsCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hfr = [];
    this._stars = [];
    this._adu = [];
    this._filters = [];
  }

  setConfig(config) {     this._prefix = (config && config.prefix) || "nina";
this._config = config || {}; }

  set hass(hass) {
    this._hass = hass;
    this._updateData();
    this._render();
  }

  _state(id, fallback = null) {
    const e = this._hass?.states[withPrefix(id, this._prefix)];
    return e ? e.state : fallback;
  }

  _attr(id, attr, fallback = null) {
    const e = this._hass?.states[id];
    return e ? (e.attributes[attr] ?? fallback) : fallback;
  }

  _updateData() {
    // Pull sparkline data from the dedicated sensor's extra attributes
    this._hfr    = this._attr("sensor.frame_sparkline_data", "hfr_sparkline", []) || [];
    this._stars  = this._attr("sensor.frame_sparkline_data", "stars_sparkline", []) || [];
    this._adu    = this._attr("sensor.frame_sparkline_data", "adu_sparkline", []) || [];
    this._filters = this._attr("sensor.frame_sparkline_data", "filter_timeline", []) || [];
  }

  _render() {
    const h = this._hass;
    if (!h) return;

    const frameCount   = this._state("sensor.session_frame_count", "0");
    const integration  = this._state("sensor.session_integration_time", "—");
    const lastHfr      = this._state("sensor.last_frame_hfr", "—");
    const rollingHfr   = this._state("sensor.rolling_avg_hfr_10", "—");
    const lastStars    = this._state("sensor.last_frame_stars", "—");
    const lastFilter   = this._state("sensor.last_frame_filter", "—");
    const lastExposure = this._state("sensor.last_frame_exposure", "—");
    const trend        = this._state("sensor.hfr_trend", "unknown");
    const trendDelta   = parseFloat(this._state("sensor.hfr_trend_delta", "0")) || 0;
    const sessionAvgHfr = this._state("sensor.session_avg_hfr", "—");
    const sessionBestHfr = this._state("sensor.session_best_hfr", "—");
    const filterCounts = this._attr("sensor.frames_per_filter", "frames_per_filter", {}) || {};

    const trendIcon = trend === "improving" ? "↘" : trend === "degrading" ? "↗" : "→";
    const trendLabel = trend === "improving"
      ? `${trendIcon} Improving (${trendDelta > 0 ? "+" : ""}${trendDelta.toFixed(3)} px)`
      : trend === "degrading"
      ? `${trendIcon} Degrading (+${Math.abs(trendDelta).toFixed(3)} px)`
      : trend === "stable"
      ? `${trendIcon} Stable`
      : "—";

    const hasData = this._hfr.filter(v => v !== null).length > 0;

    // Build filter chip HTML
    const filterEntries = Object.entries(filterCounts);
    const filterChipsHtml = filterEntries.map(([name, count], i) => {
      const colour = FILTER_COLOURS[i % FILTER_COLOURS.length];
      return `<div class="filter-chip" style="background:${colour}22;border-color:${colour}55">
        <div class="filter-dot" style="background:${colour}"></div>
        <span>${name}: ${count}</span>
      </div>`;
    }).join("");

    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <span style="font-size:1.3rem">📊</span>
          <div>
            <div class="title">Frame Statistics</div>
            <div class="subtitle">${frameCount} frames · ${integration} min · ${lastFilter}</div>
          </div>
        </div>
        <div class="body">
          ${!hasData ? `
            <div class="no-data">
              <div class="icon">🔭</div>
              <div>Waiting for frames…</div>
              <div style="font-size:0.72rem;margin-top:4px">Statistics will appear once N.I.N.A. saves an image</div>
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
                <div class="value">${parseFloat(lastExposure) ? parseFloat(lastExposure).toFixed(0) : "—"} <span style="font-size:0.7rem;font-weight:400;color:var(--muted)">s</span></div>
                <div class="sub">${lastFilter}</div>
              </div>
            </div>

            <!-- Trend + session row -->
            <div class="stat-row">
              <div class="stat-box trend-${trend}">
                <div class="label">HFR Trend</div>
                <div class="value" style="font-size:0.85rem">${trendLabel}</div>
                <div class="sub">Last 5 vs prev 5 frames</div>
              </div>
              <div class="stat-box">
                <div class="label">Session avg / best</div>
                <div class="value" style="font-size:0.85rem">${parseFloat(sessionAvgHfr) ? parseFloat(sessionAvgHfr).toFixed(2) : "—"} / ${parseFloat(sessionBestHfr) ? parseFloat(sessionBestHfr).toFixed(2) : "—"} <span style="font-size:0.65rem;color:var(--muted)">px</span></div>
                <div class="sub">${frameCount} frames total</div>
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
        this._drawSparkline("hfr-chart", this._hfr, this._filters, "#7b8de8", true);
        this._drawSparkline("stars-chart", this._stars, this._filters, "#5bcfcf", false);
        this._drawSparkline("adu-chart", this._adu, this._filters, "#f4a261", false);
      });
    }
  }

  _drawSparkline(canvasId, data, filters, defaultColor, showAvgLine) {
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

    // Main line, coloured by filter
    for (let i = 1; i < data.length; i++) {
      const y0 = yOf(data[i - 1]);
      const y1 = yOf(data[i]);
      if (y0 === null || y1 === null) continue;
      const filterIdx = filters.length > 0
        ? (FILTER_COLOURS.indexOf(FILTER_COLOURS[
            [...new Set(filters)].indexOf(filters[i]) % FILTER_COLOURS.length
          ]))
        : -1;
      const col = filterIdx >= 0
        ? FILTER_COLOURS[[...new Set(filters)].indexOf(filters[i]) % FILTER_COLOURS.length]
        : defaultColor;
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
      const col = filters.length > 0
        ? FILTER_COLOURS[[...new Set(filters)].indexOf(filters[i]) % FILTER_COLOURS.length]
        : defaultColor;
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

  static getStubConfig() { return {}; }
}

customElements.define("nina-frame-stats-card", NinaFrameStatsCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-frame-stats-card",
  name: "N.I.N.A. Frame Statistics Card",
  description: "Live per-frame HFR trend, star count, ADU, and filter breakdown.",
  preview: true,
});

console.info(
  `%c NINA-FRAME-STATS-CARD %c v${VERSION} `,
  "background:#5bcfcf;color:#1c1c2e;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px",
  "background:#1c1c2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

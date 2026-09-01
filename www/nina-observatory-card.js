/**
 * N.I.N.A. Observatory Card
 * A custom Lovelace card providing a full astrophotography session dashboard.
 *
 * Installation:
 *   1. Copy this file to /config/www/nina-observatory-card.js
 *   2. In Lovelace resources, add:
 *        URL:  /local/nina-observatory-card.js
 *        Type: JavaScript Module
 *   3. Add the card to a dashboard:
 *        type: custom:nina-observatory-card
 */

const VERSION = "1.0.0";

// Entity ids are prefixed with the instance name (device names drive entity
// ids since 2.0). Default "nina"; override with `prefix:` in the card config
// when you run more than one N.I.N.A. instance.
function withPrefix(entityId, prefix) {
  const dot = entityId.indexOf(".");
  return entityId.slice(0, dot + 1) + (prefix || "nina") + "_" + entityId.slice(dot + 1);
}


// ─── Helpers ──────────────────────────────────────────────────────────────────

function state(hass, entity_id, fallback = "—") {
  const e = hass.states[entity_id];
  return e ? e.state : fallback;
}

function attr(hass, entity_id, attribute, fallback = "—") {
  const e = hass.states[entity_id];
  return e ? (e.attributes[attribute] ?? fallback) : fallback;
}

function isOn(hass, entity_id) {
  return state(hass, entity_id) === "on";
}

function numState(hass, entity_id, decimals = 1, fallback = "—") {
  const v = parseFloat(state(hass, entity_id, NaN));
  return isNaN(v) ? fallback : v.toFixed(decimals);
}

function statusDot(on) {
  return `<span class="dot ${on ? "dot-on" : "dot-off"}"></span>`;
}

// ─── Template ────────────────────────────────────────────────────────────────

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

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px 10px;
    border-bottom: 1px solid var(--card-border);
    background: rgba(123,141,232,0.08);
  }
  .header .title {
    font-size: 1.05rem;
    font-weight: 600;
    flex: 1;
    letter-spacing: .3px;
  }
  .header .subtitle {
    font-size: 0.72rem;
    color: var(--muted);
    margin-top: 1px;
  }
  .nina-icon { font-size: 1.4rem; }

  /* ── Section grid ── */
  .body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 12px; }

  /* ── Session banner ── */
  .session-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: rgba(91,207,207,0.08);
    border: 1px solid rgba(91,207,207,0.2);
    border-radius: 10px;
    padding: 10px 14px;
  }
  .session-banner .target { font-size: 1rem; font-weight: 600; color: var(--accent2); }
  .session-banner .progress-track {
    width: 130px;
    height: 6px;
    background: rgba(255,255,255,0.1);
    border-radius: 3px;
    overflow: hidden;
  }
  .session-banner .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    border-radius: 3px;
    transition: width 0.6s ease;
  }
  .session-banner .frame-count { font-size: 0.75rem; color: var(--muted); text-align: right; }

  /* ── Equipment status row ── */
  .equip-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .equip-chip {
    display: flex;
    align-items: center;
    gap: 5px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--card-border);
    border-radius: 20px;
    padding: 4px 10px;
    font-size: 0.72rem;
    font-weight: 500;
  }
  .equip-chip.connected { border-color: rgba(87,204,153,0.4); }
  .equip-chip.disconnected { opacity: 0.5; }

  /* ── Section ── */
  .section { display: flex; flex-direction: column; gap: 6px; }
  .section-title {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    padding-bottom: 2px;
    border-bottom: 1px solid var(--card-border);
  }
  .metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 7px;
  }
  .metric {
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .metric .label { font-size: 0.62rem; color: var(--muted); font-weight: 500; }
  .metric .value { font-size: 0.88rem; font-weight: 600; }
  .metric .unit { font-size: 0.6rem; color: var(--muted); margin-left: 2px; }

  /* ── Guiding section ── */
  .guider-row { display: flex; gap: 8px; align-items: flex-start; }
  .guider-meter {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 8px 10px;
  }
  .rms-bars { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
  .rms-bar-wrap { display: flex; align-items: center; gap: 6px; }
  .rms-label { width: 28px; font-size: 0.65rem; color: var(--muted); }
  .rms-track {
    flex: 1; height: 5px; background: rgba(255,255,255,0.1);
    border-radius: 3px; overflow: hidden;
  }
  .rms-fill {
    height: 100%; border-radius: 3px;
    transition: width 0.5s ease;
  }
  .rms-fill.ra { background: var(--accent); }
  .rms-fill.dec { background: var(--accent2); }
  .rms-fill.warn { background: var(--warn); }
  .rms-fill.danger { background: var(--danger); }
  .rms-value { width: 40px; font-size: 0.65rem; text-align: right; }

  /* ── Buttons row ── */
  .btn-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .nina-btn {
    flex: 1;
    min-width: 80px;
    padding: 8px 12px;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    background: rgba(255,255,255,0.06);
    color: var(--text);
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    text-align: center;
    transition: background 0.15s, transform 0.1s;
    display: flex; align-items: center; justify-content: center; gap: 5px;
  }
  .nina-btn:hover { background: rgba(255,255,255,0.12); }
  .nina-btn:active { transform: scale(0.97); }
  .nina-btn.primary { background: rgba(123,141,232,0.18); border-color: var(--accent); color: var(--accent); }
  .nina-btn.danger  { background: rgba(231,111,81,0.15); border-color: var(--danger); color: var(--danger); }
  .nina-btn.success { background: rgba(87,204,153,0.15); border-color: var(--success); color: var(--success); }
  .nina-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  /* ── Status dots ── */
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
  .dot-on  { background: var(--success); box-shadow: 0 0 5px var(--success); }
  .dot-off { background: var(--muted); }

  /* ── Image stats ── */
  .img-stats-row {
    display: flex; gap: 8px;
  }
  .img-stat {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 6px 8px;
    text-align: center;
  }
  .img-stat .label { font-size: 0.58rem; color: var(--muted); }
  .img-stat .value { font-size: 0.9rem; font-weight: 700; }

  /* ── Flip alert ── */
  .flip-alert {
    display: flex; align-items: center; gap: 8px;
    background: rgba(244,162,97,0.12);
    border: 1px solid rgba(244,162,97,0.4);
    border-radius: 8px; padding: 7px 12px;
    font-size: 0.78rem; color: var(--warn);
  }
`;

// ─── Card class ──────────────────────────────────────────────────────────────

class NinaObservatoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {
        this._prefix = (config && config.prefix) || "nina";
this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _callService(domain, service, data = {}) {
    this._hass.callService(domain, service, data);
  }

  _render() {
    const h = this._hass;
    if (!h) return;

    // Bind the instance prefix once so the helpers below stay entity-id-only.
    const p = this._prefix;
    const st = (id, fb) => st(withPrefix(id, p), fb);
    const on = (id) => on(withPrefix(id, p));

    const seqRunning  = on("binary_sensor.sequence_running");
    const camConnected = on("binary_sensor.camera_connected");
    const mntConnected = on("binary_sensor.mount_connected");
    const focConnected = on("binary_sensor.focuser_connected");
    const fwConnected  = on("binary_sensor.filter_wheel_connected");
    const gdrConnected = on("binary_sensor.guider_connected");
    const domeConnected = on("binary_sensor.dome_connected");

    const guiding      = on("binary_sensor.guider_active");
    const cooling      = on("binary_sensor.camera_cooling");
    const parked       = on("binary_sensor.mount_parked");
    const tracking     = on("binary_sensor.mount_tracking");
    const domeOpen     = on("binary_sensor.dome_shutter_open");

    const target       = st("sensor.sequence_target", "No target");
    const progress     = parseFloat(st("sensor.sequence_progress", "0")) || 0;
    const frameCount   = st("sensor.session_image_count", "0");

    const camTemp      = numState(h, "sensor.camera_temperature");
    const camTargTemp  = numState(h, "sensor.camera_target_temperature");
    const coolerPwr    = numState(h, "sensor.camera_cooler_power", 0);
    const camGain      = st("sensor.camera_gain");
    const camFilter    = st("sensor.filter_wheel_current_filter");

    const mntRa        = numState(h, "sensor.mount_ra", 4);
    const mntDec       = numState(h, "sensor.mount_dec", 3);
    const mntAlt       = numState(h, "sensor.mount_altitude", 1);
    const mntAz        = numState(h, "sensor.mount_azimuth", 1);
    const ttf          = parseFloat(st("sensor.mount_time_to_meridian_flip", "999")) || 999;

    const focPos       = st("sensor.focuser_position");
    const focTemp      = numState(h, "sensor.focuser_temperature");

    const rmsTotal     = parseFloat(numState(h, "sensor.guider_rms_total", 2, "0"));
    const rmsRa        = parseFloat(numState(h, "sensor.guider_rms_ra", 2, "0"));
    const rmsDec       = parseFloat(numState(h, "sensor.guider_rms_dec", 2, "0"));

    const hfr          = numState(h, "sensor.last_image_hfr", 2);
    const stars        = st("sensor.last_image_star_count");
    const meanAdu      = st("sensor.last_image_mean_adu");

    // RMS bar widths (max = 4 arcsec = 100%)
    const rmsMax = 4;
    const pct = (v) => Math.min((v / rmsMax) * 100, 100).toFixed(1);
    const rmsClass = (v) => v > 3 ? "danger" : v > 1.5 ? "warn" : "";

    // Meridian flip warning
    const showFlipWarning = tracking && ttf < 15 && ttf > 0;

    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <!-- Header -->
        <div class="header">
          <span class="nina-icon">🔭</span>
          <div>
            <div class="title">N.I.N.A. Observatory</div>
            <div class="subtitle">Advanced API v2 · ${seqRunning ? "Session active" : "Standby"}</div>
          </div>
          ${statusDot(seqRunning)}
        </div>

        <div class="body">

          <!-- Session banner -->
          <div class="session-banner">
            <div>
              <div class="target">${seqRunning ? target : "—"}</div>
              <div style="font-size:0.68rem;color:var(--muted);margin-top:2px;">${seqRunning ? "Imaging" : "Sequence not running"}</div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
              <div class="progress-track">
                <div class="progress-fill" style="width:${progress}%"></div>
              </div>
              <div class="frame-count">${progress.toFixed(0)}% · ${frameCount} frames</div>
            </div>
          </div>

          <!-- Equipment chips -->
          <div class="equip-row">
            ${chip("Camera", camConnected)}
            ${chip("Mount", mntConnected)}
            ${chip("Focuser", focConnected)}
            ${chip("Filter Wheel", fwConnected)}
            ${chip("Guider", gdrConnected)}
            ${domeConnected ? chip("Dome", domeConnected) : ""}
          </div>

          <!-- Flip warning -->
          ${showFlipWarning ? `
            <div class="flip-alert">
              ⚠️ Meridian flip in <strong style="margin:0 4px;">${ttf.toFixed(0)} min</strong>
            </div>
          ` : ""}

          <!-- Camera section -->
          <div class="section">
            <div class="section-title">Camera ${cooling ? "· ❄️ Cooling" : ""}</div>
            <div class="metric-grid">
              ${metric("Temp", camTemp, "°C")}
              ${metric("Setpoint", camTargTemp, "°C")}
              ${metric("Cooler", coolerPwr + "%", "")}
              ${metric("Gain", camGain, "")}
              ${metric("Filter", camFilter, "")}
            </div>
          </div>

          <!-- Mount section -->
          <div class="section">
            <div class="section-title">Mount · ${parked ? "Parked" : tracking ? "Tracking" : "Idle"}</div>
            <div class="metric-grid">
              ${metric("RA", mntRa, "h")}
              ${metric("Dec", mntDec, "°")}
              ${metric("Alt", mntAlt, "°")}
              ${metric("Az", mntAz, "°")}
              ${ttf < 999 ? metric("Flip in", ttf.toFixed(0), "min") : ""}
            </div>
          </div>

          <!-- Focuser section -->
          <div class="section">
            <div class="section-title">Focuser</div>
            <div class="metric-grid">
              ${metric("Position", focPos, "steps")}
              ${metric("Temp", focTemp, "°C")}
            </div>
          </div>

          <!-- Guiding section -->
          ${gdrConnected ? `
            <div class="section">
              <div class="section-title">Guiding · ${guiding ? "Active" : "Stopped"}</div>
              <div class="guider-meter">
                <div style="font-size:0.72rem;color:var(--muted);">
                  Total RMS: <strong style="color:var(--text)">${rmsTotal.toFixed(2)}"</strong>
                </div>
                <div class="rms-bars">
                  <div class="rms-bar-wrap">
                    <span class="rms-label">RA</span>
                    <div class="rms-track"><div class="rms-fill ra ${rmsClass(rmsRa)}" style="width:${pct(rmsRa)}%"></div></div>
                    <span class="rms-value">${rmsRa.toFixed(2)}"</span>
                  </div>
                  <div class="rms-bar-wrap">
                    <span class="rms-label">Dec</span>
                    <div class="rms-track"><div class="rms-fill dec ${rmsClass(rmsDec)}" style="width:${pct(rmsDec)}%"></div></div>
                    <span class="rms-value">${rmsDec.toFixed(2)}"</span>
                  </div>
                </div>
              </div>
            </div>
          ` : ""}

          <!-- Last image stats -->
          <div class="section">
            <div class="section-title">Last Image</div>
            <div class="img-stats-row">
              ${imgStat("HFR", hfr + " px")}
              ${imgStat("Stars", stars)}
              ${imgStat("Mean ADU", meanAdu)}
            </div>
          </div>

          <!-- Controls -->
          <div class="section">
            <div class="section-title">Controls</div>
            <div class="btn-row">
              ${seqRunning
                ? `<button class="nina-btn danger" id="btn-stop">⏹ Stop Sequence</button>`
                : `<button class="nina-btn success" id="btn-start">▶ Start Sequence</button>`
              }
              ${parked
                ? `<button class="nina-btn primary" id="btn-unpark">⬆ Unpark</button>`
                : `<button class="nina-btn" id="btn-park">⏸ Park</button>`
              }
              <button class="nina-btn" id="btn-af">🔍 Auto Focus</button>
              ${domeConnected
                ? domeOpen
                  ? `<button class="nina-btn" id="btn-dome-close">🔒 Close Dome</button>`
                  : `<button class="nina-btn primary" id="btn-dome-open">🔓 Open Dome</button>`
                : ""
              }
            </div>
            <div class="btn-row">
              ${cooling
                ? `<button class="nina-btn" id="btn-warm">🌡 Warm Camera</button>`
                : `<button class="nina-btn primary" id="btn-cool">❄ Cool Camera</button>`
              }
              ${guiding
                ? `<button class="nina-btn danger" id="btn-stop-guide">◼ Stop Guiding</button>`
                : `<button class="nina-btn success" id="btn-start-guide">▶ Start Guiding</button>`
              }
              <button class="nina-btn" id="btn-clear-cal">⟲ Clear Calibration</button>
            </div>
          </div>

        </div><!-- end body -->
      </ha-card>
    `;

    this.shadowRoot.innerHTML = html;
    this._attachListeners();
  }

  _attachListeners() {
    const bind = (id, fn) => {
      const el = this.shadowRoot.getElementById(id);
      if (el) el.addEventListener("click", fn);
    };
    const svc = (s, d) => this._callService("nina_astrophotography", s, d);

    bind("btn-start",      () => svc("sequence_start"));
    bind("btn-stop",       () => svc("sequence_stop"));
    bind("btn-park",       () => svc("mount_park"));
    bind("btn-unpark",     () => svc("mount_unpark"));
    bind("btn-af",         () => svc("focuser_auto_focus"));
    bind("btn-dome-open",  () => svc("dome_open"));
    bind("btn-dome-close", () => svc("dome_close"));
    bind("btn-cool",       () => svc("camera_cool", { temperature: -10, minutes: 15 }));
    bind("btn-warm",       () => svc("camera_warm", { minutes: 20 }));
    bind("btn-start-guide",() => svc("guider_start"));
    bind("btn-stop-guide", () => svc("guider_stop"));
    bind("btn-clear-cal",  () => svc("guider_clear_calibration"));
  }

  getCardSize() { return 8; }

  static getConfigElement() {
    return document.createElement("nina-observatory-card-editor");
  }

  static getStubConfig() {
    return {};
  }
}

// ─── Tiny render helpers ──────────────────────────────────────────────────────

function chip(label, connected) {
  return `<div class="equip-chip ${connected ? "connected" : "disconnected"}">
    ${statusDot(connected)} ${label}
  </div>`;
}

function metric(label, value, unit) {
  return `<div class="metric">
    <div class="label">${label}</div>
    <div class="value">${value}<span class="unit">${unit}</span></div>
  </div>`;
}

function imgStat(label, value) {
  return `<div class="img-stat">
    <div class="label">${label}</div>
    <div class="value">${value}</div>
  </div>`;
}

// ─── Register ────────────────────────────────────────────────────────────────

customElements.define("nina-observatory-card", NinaObservatoryCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-observatory-card",
  name: "N.I.N.A. Observatory Card",
  description: "Full session dashboard for N.I.N.A. astrophotography software.",
  preview: true,
  documentationURL: "https://github.com/christian-photo/ninaAPI",
});

console.info(
  `%c NINA-OBSERVATORY-CARD %c v${VERSION} `,
  "background:#7b8de8;color:#fff;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px",
  "background:#1c1c2e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

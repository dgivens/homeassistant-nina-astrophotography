/**
 * N.I.N.A. Weather & Safety Card  v1.0.0
 *
 * Displays weather station data and safety monitor status from N.I.N.A.
 * Works with any ASCOM ObservingConditions driver or weather station
 * connected in N.I.N.A. (OpenWeatherMap, Pegasus UPB, AAG CloudWatcher, etc.)
 *
 * Installation:
 *   1. Copy to /config/www/nina-weather-card.js
 *   2. Add resource: /local/nina-weather-card.js (JavaScript Module)
 *   3. Add card:  type: custom:nina-weather-card
 */

const VERSION = "1.0.0";

// Entity ids are prefixed with the instance name (device names drive entity
// ids since 2.0). Default "nina"; override with `prefix:` in the card config
// when you run more than one N.I.N.A. instance.
function withPrefix(entityId, prefix) {
  const dot = entityId.indexOf(".");
  return entityId.slice(0, dot + 1) + (prefix || "nina") + "_" + entityId.slice(dot + 1);
}


const STYLE = `
  :host {
    --bg:      var(--ha-card-background, var(--card-background-color, #1c1c2e));
    --border:  var(--divider-color, rgba(255,255,255,0.1));
    --accent:  #7b8de8;
    --accent2: #5bcfcf;
    --warn:    #f4a261;
    --danger:  #e76f51;
    --success: #57cc99;
    --muted:   rgba(255,255,255,0.45);
    --text:    rgba(255,255,255,0.92);
    font-family: var(--primary-font-family, Roboto, sans-serif);
  }
  ha-card {
    background: var(--bg); color: var(--text);
    border: 1px solid var(--border);
    border-radius: 16px; overflow: hidden; padding: 0;
  }
  .header {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px 10px;
    border-bottom: 1px solid var(--border);
    background: rgba(123,141,232,0.07);
  }
  .title { font-size: 1rem; font-weight: 600; flex: 1; }
  .sub { font-size: 0.68rem; color: var(--muted); margin-top: 1px; }

  /* ── Safety banner ── */
  .safety-banner {
    display: flex; align-items: center; gap: 12px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    transition: background 0.4s, border-color 0.4s;
  }
  .safety-banner.safe {
    background: rgba(87,204,153,0.10);
    border-bottom-color: rgba(87,204,153,0.25);
  }
  .safety-banner.unsafe {
    background: rgba(231,111,81,0.14);
    border-bottom-color: rgba(231,111,81,0.35);
    animation: pulse-unsafe 2s ease-in-out infinite;
  }
  .safety-banner.unknown {
    background: rgba(255,255,255,0.04);
  }
  @keyframes pulse-unsafe {
    0%,100%{ background: rgba(231,111,81,0.14); }
    50%    { background: rgba(231,111,81,0.22); }
  }
  .safety-icon { font-size: 1.8rem; flex-shrink: 0; }
  .safety-text .label { font-size: 1rem; font-weight: 700; }
  .safety-text .detail { font-size: 0.68rem; color: var(--muted); margin-top: 2px; }
  .safety-text .safe   { color: var(--success); }
  .safety-text .unsafe { color: var(--danger); }
  .safety-text .unknown{ color: var(--muted); }

  /* ── Grid ── */
  .body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 10px; }

  .section-title {
    font-size: 0.6rem; font-weight: 700; letter-spacing: .8px;
    text-transform: uppercase; color: var(--muted);
    padding-bottom: 4px; border-bottom: 1px solid var(--border);
  }

  .weather-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 7px;
  }
  .w-cell {
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border);
    border-radius: 9px; padding: 9px 11px;
    display: flex; flex-direction: column; gap: 3px;
    transition: border-color 0.2s;
  }
  .w-cell.warn  { border-color: rgba(244,162,97,0.45); }
  .w-cell.danger{ border-color: rgba(231,111,81,0.55); }
  .w-cell .icon { font-size: 1rem; margin-bottom: 1px; }
  .w-cell .lbl  { font-size: 0.6rem; font-weight: 600; letter-spacing: .5px; text-transform: uppercase; color: var(--muted); }
  .w-cell .val  { font-size: 0.9rem; font-weight: 700; }
  .w-cell .unit { font-size: 0.6rem; color: var(--muted); margin-left: 2px; }
  .w-cell.na    { opacity: 0.38; }

  /* ── Wind rose ── */
  .wind-rose-wrap {
    display: flex; gap: 10px; align-items: center;
  }
  .wind-rose {
    position: relative; width: 64px; height: 64px; flex-shrink: 0;
  }
  .wind-rose canvas { position: absolute; inset: 0; }
  .wind-info { flex: 1; display: flex; flex-direction: column; gap: 4px; }
  .wind-row  { display: flex; align-items: center; gap: 6px; font-size: 0.75rem; }
  .wind-row .lbl { color: var(--muted); min-width: 54px; font-size: 0.65rem; }

  /* ── Sky quality bar ── */
  .sq-wrap { display: flex; flex-direction: column; gap: 4px; }
  .sq-bar-track {
    height: 8px; background: rgba(255,255,255,0.08);
    border-radius: 4px; overflow: hidden;
  }
  .sq-bar-fill {
    height: 100%; border-radius: 4px;
    transition: width 0.6s ease;
  }
  .sq-labels { display: flex; justify-content: space-between; font-size: 0.58rem; color: var(--muted); }

  /* ── Dew point warning ── */
  .dew-alert {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 12px; border-radius: 8px;
    background: rgba(244,162,97,0.12);
    border: 1px solid rgba(244,162,97,0.35);
    font-size: 0.75rem; color: var(--warn);
  }

  /* ── Not connected ── */
  .not-connected {
    padding: 24px 16px; text-align: center;
    color: var(--muted); font-size: 0.8rem;
  }
  .not-connected .hint { font-size: 0.66rem; margin-top: 6px; opacity: 0.7; }
`;

const DEG_LABELS = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
                    "S","SSW","SW","WSW","W","WNW","NW","NNW"];

function degToCompass(deg) {
  if (deg === null || isNaN(deg)) return "—";
  return DEG_LABELS[Math.round(deg / 22.5) % 16];
}

class NinaWeatherCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  setConfig(config) {     this._prefix = (config && config.prefix) || "nina";
this._config = config || {}; }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _deviceModel(entityId) {
    // hass.devices is populated by recent frontends; degrade quietly if not.
    try {
      const ent = this._hass?.entities?.[entityId];
      return ent && this._hass?.devices?.[ent.device_id]?.model || null;
    } catch (e) {
      return null;
    }
  }

  _s(id, fb = null) {
    const e = this._hass?.states?.[withPrefix(id, this._prefix)];
    return e ? e.state : fb;
  }
  _f(id, fb = null) {
    const v = parseFloat(this._s(id));
    return isNaN(v) ? fb : v;
  }
  _on(id) { return this._s(id) === "on"; }

  _render() {
    if (!this._hass) return;

    // Safety monitor
    const safetyConnected = this._on("binary_sensor.safety_monitor_connected");
    // safety_monitor_safe uses the SAFETY device class: "on" = UNSAFE
    const isUnsafe = this._on("binary_sensor.safety_monitor_safe");
    const isSafe   = safetyConnected && !isUnsafe;

    // Weather
    const wxConnected = this._on("binary_sensor.weather_station_connected");
    const temp    = this._f("sensor.weather_station_temperature");
    const humid   = this._f("sensor.weather_station_humidity");
    const dewPt   = this._f("sensor.weather_station_dew_point");
    const windSpd = this._f("sensor.weather_station_wind_speed");
    const windDir = this._f("sensor.weather_station_wind_direction");
    const windGst = this._f("sensor.weather_station_wind_gust");
    const press   = this._f("sensor.weather_station_barometric_pressure");
    const cloud   = this._f("sensor.weather_station_cloud_cover");
    const rain    = this._f("sensor.weather_station_rain_rate");
    const skyQ    = this._f("sensor.weather_station_sky_quality");
    const skyB    = this._f("sensor.weather_station_sky_brightness");
    const skyT    = this._f("sensor.weather_station_sky_temperature");
    const seeing  = this._f("sensor.weather_station_atmospheric_seeing");
    // The driver name moved to the device registry in 2.0, so read it from the
    // weather device when the frontend exposes one, else fall back to a label.
    const wxName  = this._deviceModel("binary_sensor.weather_station_connected")
                    || "Weather Station";

    // Dew threat: temp within 3°C of dew point
    const dewThreat = temp !== null && dewPt !== null && (temp - dewPt) < 3;

    // Safety banner content
    let safetyIcon, safetyLabelCls, safetyLabel, safetyDetail, bannerCls;
    if (!safetyConnected) {
      safetyIcon = "🔘"; safetyLabelCls = "unknown";
      safetyLabel = "Safety monitor not connected";
      safetyDetail = "Connect a safety monitor in N.I.N.A. to enable automated abort";
      bannerCls = "safety-banner unknown";
    } else if (isSafe) {
      safetyIcon = "✅"; safetyLabelCls = "safe";
      safetyLabel = "Conditions safe";
      safetyDetail = "Safety monitor reports all conditions within limits";
      bannerCls = "safety-banner safe";
    } else {
      safetyIcon = "⚠️"; safetyLabelCls = "unsafe";
      safetyLabel = "UNSAFE — conditions exceeded";
      safetyDetail = "Automated abort should be triggered if configured";
      bannerCls = "safety-banner unsafe";
    }

    // Sky quality: Bortle-ish mapping (mag/arcsec²)
    // 22+ = Bortle 1-2 (excellent), 20-22 = good, 18-20 = moderate, <18 = poor
    let sqPct = 0, sqLabel = "—", sqColor = "#7b8de8";
    if (skyQ !== null) {
      sqPct   = Math.min(100, Math.max(0, ((skyQ - 16) / (22.5 - 16)) * 100));
      sqLabel = skyQ >= 21.5 ? "Excellent" : skyQ >= 20 ? "Good" : skyQ >= 18.5 ? "Moderate" : "Poor";
      sqColor = skyQ >= 21.5 ? "#57cc99" : skyQ >= 20 ? "#5bcfcf" : skyQ >= 18.5 ? "#f4a261" : "#e76f51";
    }

    const cell = (icon, label, val, unit, warnIf = false, dangerIf = false, naIf = false) => {
      const cls = naIf ? "w-cell na" : dangerIf ? "w-cell danger" : warnIf ? "w-cell warn" : "w-cell";
      const valStr = val !== null ? String(val) : "—";
      return `<div class="${cls}">
        <div class="icon">${icon}</div>
        <div class="lbl">${label}</div>
        <div class="val">${valStr}<span class="unit">${unit}</span></div>
      </div>`;
    };

    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5bcfcf" stroke-width="1.5" stroke-linecap="round">
            <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>
          </svg>
          <div>
            <div class="title">${wxName}</div>
            <div class="sub">${wxConnected ? "Connected" : "Not connected"} · N.I.N.A. weather station</div>
          </div>
        </div>

        <!-- Safety banner -->
        <div class="${bannerCls}">
          <div class="safety-icon">${safetyIcon}</div>
          <div class="safety-text">
            <div class="label ${safetyLabelCls}">${safetyLabel}</div>
            <div class="detail">${safetyDetail}</div>
          </div>
        </div>

        ${!wxConnected ? `
          <div class="not-connected">
            <div>No weather station connected</div>
            <div class="hint">Connect an ASCOM ObservingConditions or weather driver in N.I.N.A.<br>
              Compatible: OpenWeatherMap, Pegasus UPB, AAG CloudWatcher, ASCOM Alpaca, and others.</div>
          </div>
        ` : `
        <div class="body">

          ${dewThreat ? `
            <div class="dew-alert">
              ⚠ Dew alert — temperature (${temp?.toFixed(1)}°C) within ${(temp - dewPt).toFixed(1)}°C of dew point (${dewPt?.toFixed(1)}°C)
            </div>
          ` : ""}

          <!-- Temperature & humidity -->
          <div class="section-title">Atmosphere</div>
          <div class="weather-grid">
            ${cell("🌡", "Temperature", temp?.toFixed(1) ?? null, "°C", temp !== null && temp > 25, temp !== null && temp < -10)}
            ${cell("💧", "Humidity", humid?.toFixed(0) ?? null, "%", humid !== null && humid > 85, humid !== null && humid > 95)}
            ${cell("🌫", "Dew Point", dewPt?.toFixed(1) ?? null, "°C", dewThreat, false)}
            ${cell("📊", "Pressure", press?.toFixed(0) ?? null, "hPa", false, false, press === null)}
          </div>

          <!-- Wind -->
          <div class="section-title">Wind</div>
          <div class="wind-rose-wrap">
            <div class="wind-rose">
              <canvas id="wind-rose-canvas" width="64" height="64"></canvas>
            </div>
            <div class="wind-info">
              <div class="wind-row">
                <span class="lbl">Speed</span>
                <span style="font-weight:700;color:${windSpd !== null && windSpd > 12 ? "var(--danger)" : windSpd !== null && windSpd > 8 ? "var(--warn)" : "var(--text)"}">
                  ${windSpd !== null ? windSpd.toFixed(1) + " m/s" : "—"}
                </span>
              </div>
              <div class="wind-row">
                <span class="lbl">Gust</span>
                <span>${windGst !== null ? windGst.toFixed(1) + " m/s" : "—"}</span>
              </div>
              <div class="wind-row">
                <span class="lbl">Direction</span>
                <span>${windDir !== null ? windDir.toFixed(0) + "° " + degToCompass(windDir) : "—"}</span>
              </div>
            </div>
          </div>

          <!-- Sky conditions -->
          <div class="section-title">Sky conditions</div>
          <div class="weather-grid">
            ${cell("☁", "Cloud cover", cloud?.toFixed(0) ?? null, "%", cloud !== null && cloud > 60, cloud !== null && cloud > 85)}
            ${cell("🌧", "Rain rate", rain !== null ? rain.toFixed(2) : null, "mm/h", false, rain !== null && rain > 0)}
            ${cell("🌡", "Sky temp", skyT?.toFixed(1) ?? null, "°C", false, false, skyT === null)}
            ${cell("👁", "Seeing", seeing?.toFixed(1) ?? null, "\"", seeing !== null && seeing > 3, seeing !== null && seeing > 5, seeing === null)}
          </div>

          <!-- Sky quality -->
          ${skyQ !== null ? `
            <div class="section-title">Sky quality (SQM)</div>
            <div class="sq-wrap">
              <div style="display:flex;justify-content:space-between;align-items:baseline">
                <span style="font-size:0.85rem;font-weight:700">${skyQ.toFixed(2)} mag/arcsec²</span>
                <span style="font-size:0.72rem;color:${sqColor};font-weight:600">${sqLabel}</span>
              </div>
              <div class="sq-bar-track">
                <div class="sq-bar-fill" style="width:${sqPct.toFixed(0)}%;background:${sqColor}"></div>
              </div>
              <div class="sq-labels">
                <span>16 (city)</span>
                <span>19 (suburban)</span>
                <span>22+ (dark)</span>
              </div>
            </div>
          ` : ""}

          <!-- Sky brightness -->
          ${skyB !== null ? `
            ${cell("✨", "Sky brightness", skyB?.toFixed(2) ?? null, "lux", false, false, skyB === null)}
          ` : ""}

        </div>
        `}
      </ha-card>
    `;

    this.shadowRoot.innerHTML = html;

    // Draw wind rose after render
    if (wxConnected && windDir !== null) {
      requestAnimationFrame(() => this._drawWindRose(windDir, windSpd));
    }
  }

  _drawWindRose(dir, speed) {
    const canvas = this.shadowRoot.getElementById("wind-rose-canvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = 64, H = 64, cx = 32, cy = 32, r = 26;
    ctx.clearRect(0, 0, W, H);

    // Background circle
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(255,255,255,0.12)"; ctx.lineWidth = 1; ctx.stroke();

    // Cross-hairs
    for (const a of [0, 90, 180, 270]) {
      const rad = (a - 90) * Math.PI / 180;
      ctx.beginPath();
      ctx.moveTo(cx + (r - 6) * Math.cos(rad), cy + (r - 6) * Math.sin(rad));
      ctx.lineTo(cx + r * Math.cos(rad), cy + r * Math.sin(rad));
      ctx.strokeStyle = "rgba(255,255,255,0.2)"; ctx.lineWidth = 0.8; ctx.stroke();
    }

    // Cardinal labels
    ctx.font = "bold 7px sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.fillText("N", cx, cy - r + 4);
    ctx.fillText("S", cx, cy + r - 4);
    ctx.fillText("E", cx + r - 4, cy);
    ctx.fillText("W", cx - r + 4, cy);

    // Wind arrow — points FROM the direction wind is coming FROM (meteorological)
    const arrowRad = (dir - 90) * Math.PI / 180;  // rotate so 0° = North = up
    const speedRatio = speed !== null ? Math.min(1, (speed || 0) / 20) : 0.5;
    const arrowLen = 12 + speedRatio * 10;
    const endX = cx + Math.cos(arrowRad) * arrowLen;
    const endY = cy + Math.sin(arrowRad) * arrowLen;
    const startX = cx - Math.cos(arrowRad) * arrowLen;
    const startY = cy - Math.sin(arrowRad) * arrowLen;

    const color = speed !== null && speed > 12 ? "#e76f51" : speed !== null && speed > 8 ? "#f4a261" : "#5bcfcf";

    // Arrow shaft
    ctx.beginPath(); ctx.moveTo(startX, startY); ctx.lineTo(endX, endY);
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();

    // Arrowhead
    const headLen = 6, headAngle = 0.45;
    ctx.beginPath();
    ctx.moveTo(endX, endY);
    ctx.lineTo(endX - headLen * Math.cos(arrowRad - headAngle),
               endY - headLen * Math.sin(arrowRad - headAngle));
    ctx.moveTo(endX, endY);
    ctx.lineTo(endX - headLen * Math.cos(arrowRad + headAngle),
               endY - headLen * Math.sin(arrowRad + headAngle));
    ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.stroke();

    // Centre dot
    ctx.beginPath(); ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.3)"; ctx.fill();
  }

  getCardSize() { return 7; }
  static getStubConfig() { return {}; }
}

customElements.define("nina-weather-card", NinaWeatherCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-weather-card",
  name: "N.I.N.A. Weather & Safety Card",
  description: "Live weather station readings and safety monitor status from N.I.N.A.",
  preview: true,
});

console.info(
  `%c NINA-WEATHER-CARD %c v${VERSION} `,
  "background:#0d1b2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #5bcfcf",
  "background:#5bcfcf;color:#0d1b2e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

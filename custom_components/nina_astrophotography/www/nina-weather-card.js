/**
 * N.I.N.A. Weather & Safety Card
 *
 * Displays weather station data and safety monitor status from N.I.N.A.
 * Works with any ASCOM ObservingConditions driver or weather station
 * connected in N.I.N.A. (OpenWeatherMap, Pegasus UPB, AAG CloudWatcher, etc.)
 *
 * Ships with the integration and registers itself as a dashboard resource —
 * nothing to copy or add under Resources. One rig needs no configuration at
 * all: the card finds its own station in the registry.
 *   type: custom:nina-weather-card
 *   device_id: abc123      # which rig, for two or more; any one of its devices
 *   prefix: n_i_n_a        # fallback only, for the entities that cannot resolve
 *
 * The limits a reading is coloured by are options too, in °C and m/s whatever
 * unit Home Assistant shows the reading in:
 *   dew_margin: 3          # dew alert while the air is within this of its dew point
 *   wind_warn: 8           # and wind_danger: 12
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import { LinkView, RigEntities } from "./nina-entity-resolver.js";
import { displayed, interval, inUnit, missing, quantity } from "./nina-units.js";

const VERSION = "2.2.0";

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
  .safety-banner.unreachable {
    background: rgba(244,162,97,0.10);
    border-bottom-color: rgba(244,162,97,0.30);
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
  .safety-text .unreachable { color: var(--warn); }

  /* Readings N.I.N.A. has not confirmed since it stopped answering */
  .body.stale { opacity: 0.5; }

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

// Temperatures and the dew margin in °C, wind in m/s, humidity and cloud in %,
// seeing in arcsec.
const LIMITS = {
  dew_margin: 3,
  temperature_high: 25,
  temperature_low: -10,
  humidity_warn: 85,
  humidity_danger: 95,
  wind_warn: 8,
  wind_danger: 12,
  cloud_warn: 60,
  cloud_danger: 85,
  seeing_warn: 3,
  seeing_danger: 5,
};

// Coerced, because YAML hands back a string as readily as a number, and `null`
// for a key left empty. `Number` reads `null` and a blank string as 0.
function limit(value, fallback) {
  const text = typeof value === "string" ? value.trim() : value;
  const n = text === null || text === "" ? NaN : Number(text);
  return Number.isFinite(n) ? n : fallback;
}

// " since HH:MM", or nothing without a time.
function since(ms) {
  return ms
    ? ` since ${new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : "";
}

class NinaWeatherCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._view = new LinkView();
  }

  setConfig(config) {
    const cfg = config || {};
    this._config = cfg;
    this._limits = {
      dewMargin: limit(cfg.dew_margin, LIMITS.dew_margin),
      tempHigh: limit(cfg.temperature_high, LIMITS.temperature_high),
      tempLow: limit(cfg.temperature_low, LIMITS.temperature_low),
      humidWarn: limit(cfg.humidity_warn, LIMITS.humidity_warn),
      humidDanger: limit(cfg.humidity_danger, LIMITS.humidity_danger),
      windWarn: limit(cfg.wind_warn, LIMITS.wind_warn),
      windDanger: limit(cfg.wind_danger, LIMITS.wind_danger),
      cloudWarn: limit(cfg.cloud_warn, LIMITS.cloud_warn),
      cloudDanger: limit(cfg.cloud_danger, LIMITS.cloud_danger),
      seeingWarn: limit(cfg.seeing_warn, LIMITS.seeing_warn),
      seeingDanger: limit(cfg.seeing_danger, LIMITS.seeing_danger),
    };
    this._rig = new RigEntities(
      this._config.prefix || DEFAULT_PREFIX, this._config.device_id);
    this._view.reset();
  }

  set hass(hass) {
    this._hass = hass;
    this._rig.refresh(hass);
    this._render();
  }

  // Falls back to a prefixed `slug` when nothing resolves. `slug` is the
  // entity-id suffix and is rarely `key` here: the weather device supplies
  // "weather" and the monitor "safety monitor", which the channel keys omit.
  _eid(domain, key, slug = key) {
    return this._rig.id(domain, key, slug);
  }

  _s(id, fb = null) {
    const e = this._shown?.states?.[id];
    return e ? e.state : fb;
  }
  _f(id, fb = null) {
    const v = parseFloat(this._s(id));
    return isNaN(v) ? fb : v;
  }
  _q(id) { return quantity(this._shown, id); }

  _render() {
    if (!this._hass) return;
    const link = this._view.read(this._hass, this._rig);
    // While N.I.N.A. is not answering, the readings are its last ones.
    this._shown = link.hass;
    // Nothing to show at all: the link was lost before this card saw it up.
    const unreachable = link.lost && !link.stale;

    // Safety monitor
    const safetyLinkRow = this._shown.states?.[this._eid("binary_sensor", "safety_monitor_connected")];
    const safetyConnected = safetyLinkRow?.state === "on";
    // `on` means UNSAFE. Three states, not two: `unknown` is no reading yet,
    // and must not render as "safe".
    const unsafeState = this._s(
      this._eid("binary_sensor", "safety_unsafe", "safety_monitor_unsafe"));
    const isUnsafe = unsafeState === "on";
    const isSafe   = safetyConnected && unsafeState === "off";

    // The source is diagnostic and may be disabled, so nothing else depends on it.
    const source = this._s(this._eid("sensor", "weather_source"));
    const sourceLive = !missing(source);
    const channels = {
      temp: this._eid("sensor", "temperature", "weather_temperature"),
      humid: this._eid("sensor", "humidity", "weather_humidity"),
      dewPt: this._eid("sensor", "dew_point", "weather_dew_point"),
      windSpd: this._eid("sensor", "wind_speed", "weather_wind_speed"),
      windDir: this._eid("sensor", "wind_direction", "weather_wind_direction"),
      windGst: this._eid("sensor", "wind_gust", "weather_wind_gust"),
      press: this._eid("sensor", "pressure", "weather_pressure"),
      cloud: this._eid("sensor", "cloud_cover", "weather_cloud_cover"),
      rain: this._eid("sensor", "rain_rate", "weather_rain_rate"),
      skyQ: this._eid("sensor", "sky_quality", "weather_sky_quality"),
      skyB: this._eid("sensor", "sky_brightness", "weather_sky_brightness"),
      skyT: this._eid("sensor", "sky_temperature", "weather_sky_temperature"),
      seeing: this._eid("sensor", "star_fwhm", "weather_star_fwhm"),
    };
    // Connected when it names itself or any channel is available. A channel's
    // `unknown` means a missed poll, not a gone station; a restored row is
    // always `unavailable`.
    const wxConnected = !unreachable && (sourceLive || Object.values(channels).some((id) => {
      const state = this._s(id);
      return state !== null && state !== "unavailable";
    }));
    const wxName  = wxConnected && sourceLive ? source : "Weather station";
    const temp    = this._q(channels.temp);
    const humid   = this._f(channels.humid);
    const dewPt   = this._q(channels.dewPt);
    const windSpd = this._q(channels.windSpd);
    const windDir = this._f(channels.windDir);
    const windGst = this._q(channels.windGst);
    const press   = this._q(channels.press);
    const cloud   = this._f(channels.cloud);
    const rain    = this._q(channels.rain);
    const skyQ    = this._f(channels.skyQ);
    const skyB    = this._q(channels.skyB);
    const skyT    = this._q(channels.skyT);
    const seeing  = this._f(channels.seeing);

    const tempC  = inUnit(temp, "°C");
    const dewC   = inUnit(dewPt, "°C");
    const windMs = inUnit(windSpd, "m/s");

    const L = this._limits;
    // Dew threat: the air within `dew_margin` of its dew point.
    const dewMargin = tempC !== null && dewC !== null ? tempC - dewC : null;
    const dewThreat = dewMargin !== null && dewMargin < L.dewMargin;
    const windLevel = this._windLevel(windMs);
    const windColor = windLevel === "danger" ? "var(--danger)"
      : windLevel === "warn" ? "var(--warn)" : "var(--text)";

    // UNSAFE is tested first, so a disabled connectivity diagnostic cannot hide
    // a monitor reporting UNSAFE.
    let safetyIcon, safetyLabelCls, safetyLabel, safetyDetail;
    if (link.stale) {
      // A safe verdict nobody has confirmed is not one; the last reading is
      // still worth knowing.
      const last = isUnsafe ? "unsafe" : isSafe ? "safe" : "none";
      safetyIcon = "📡"; safetyLabelCls = "unreachable";
      safetyLabel = "Safety state unknown";
      safetyDetail = `No answer from N.I.N.A.${since(link.since)}. Its last reading: ${last}.`;
    } else if (isUnsafe) {
      safetyIcon = "⚠️"; safetyLabelCls = "unsafe";
      safetyLabel = "UNSAFE — conditions exceeded";
      safetyDetail = "Automated abort should be triggered if configured";
    } else if (unreachable) {
      safetyIcon = "📡"; safetyLabelCls = "unreachable";
      safetyLabel = "N.I.N.A. unreachable";
      safetyDetail = "Safety state unknown — Home Assistant automations cannot see the monitor or command the rig";
    } else if (!safetyConnected) {
      safetyIcon = "🔘"; safetyLabelCls = "unknown";
      safetyLabel = "Safety monitor not connected";
      safetyDetail = "Connect a safety monitor in N.I.N.A. to enable automated abort";
    } else if (!isSafe) {
      // Connected, but no reading yet — not the same thing as safe.
      safetyIcon = "🔘"; safetyLabelCls = "unknown";
      safetyLabel = "Safety monitor has no reading";
      safetyDetail = "The monitor is connected but has not reported yet";
    } else {
      safetyIcon = "✅"; safetyLabelCls = "safe";
      safetyLabel = "Conditions safe";
      safetyDetail = "Safety monitor reports all conditions within limits";
    }

    let wxStatus, noReadings, noReadingsHint;
    if (link.stale) {
      wxStatus = `N.I.N.A. ${link.lost ? "unreachable" : "not answering"} · last readings`;
    } else if (wxConnected) {
      wxStatus = "Connected · N.I.N.A. weather station";
    } else if (unreachable) {
      wxStatus = "N.I.N.A. unreachable · weather station";
      noReadings = "No weather readings";
      noReadingsHint = "Home Assistant has no link to N.I.N.A.; readings resume when it returns.";
    } else {
      wxStatus = "Not connected · N.I.N.A. weather station";
      noReadings = "No weather station connected";
      noReadingsHint = `Connect an ASCOM ObservingConditions or weather driver in N.I.N.A.<br>
              Compatible: OpenWeatherMap, Pegasus UPB, AAG CloudWatcher, ASCOM Alpaca, and others.`;
    }

    // SQM in mag/arcsec²: 21.5+ excellent, 20 good, 18.5 moderate, below that
    // poor. The bar spans 16 to 22.5.
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
    const qcell = (icon, label, q, decimals, ...flags) =>
      cell(icon, label, displayed(q, decimals), q?.unit ?? "", ...flags);
    const withUnit = (q, decimals) => q ? `${displayed(q, decimals)} ${q.unit ?? ""}`.trim() : "—";

    // The margin as printed: the difference of the two shown numbers, so
    // 20.54/20.46 °C both showing 20.5 reads "at" rather than "within 0.1".
    // Two units or precisions get the true margin instead.
    const places = temp?.precision ?? 1;
    const shownMargin = !dewThreat ? null
      : temp.unit === dewPt.unit && places === (dewPt.precision ?? 1)
        ? (Number(displayed(temp, 1)) - Number(displayed(dewPt, 1))).toFixed(places)
        : interval(dewMargin, "°C", temp.unit)?.toFixed(1);
    const atDewPoint = dewThreat && (dewMargin <= 0 || Number(shownMargin) <= 0);
    const tempShown = withUnit(temp, 1);
    const dewShown = withUnit(dewPt, 1);
    const dewWhere = atDewPoint
      ? `air at its dew point (${dewShown}); dew is forming`
      : `temperature (${tempShown}) within ${shownMargin} ${temp?.unit} of dew point (${dewShown})`;

    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5bcfcf" stroke-width="1.5" stroke-linecap="round">
            <path d="M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z"/>
          </svg>
          <div>
            <div class="title">${wxName}</div>
            <div class="sub">${wxStatus}</div>
          </div>
        </div>

        <!-- Safety banner -->
        <div class="safety-banner ${safetyLabelCls}">
          <div class="safety-icon">${safetyIcon}</div>
          <div class="safety-text">
            <div class="label ${safetyLabelCls}">${safetyLabel}</div>
            <div class="detail">${safetyDetail}</div>
          </div>
        </div>

        ${!wxConnected ? `
          <div class="not-connected">
            <div>${noReadings}</div>
            <div class="hint">${noReadingsHint}</div>
          </div>
        ` : `
        <div class="body${link.stale ? " stale" : ""}">

          ${dewThreat ? `
            <div class="dew-alert">
              ⚠ Dew alert — ${dewWhere}
            </div>
          ` : ""}

          <!-- Temperature & humidity -->
          <div class="section-title">Atmosphere</div>
          <div class="weather-grid">
            ${qcell("🌡", "Temperature", temp, 1, tempC !== null && tempC > L.tempHigh, tempC !== null && tempC < L.tempLow)}
            ${cell("💧", "Humidity", humid?.toFixed(0) ?? null, "%", humid !== null && humid > L.humidWarn, humid !== null && humid > L.humidDanger)}
            ${qcell("🌫", "Dew Point", dewPt, 1, dewThreat, false)}
            ${qcell("📊", "Pressure", press, 1, false, false, press === null)}
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
                <span style="font-weight:700;color:${windColor}">
                  ${withUnit(windSpd, 1)}
                </span>
              </div>
              <div class="wind-row">
                <span class="lbl">Gust</span>
                <span>${withUnit(windGst, 1)}</span>
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
            ${cell("☁", "Cloud cover", cloud?.toFixed(0) ?? null, "%", cloud !== null && cloud > L.cloudWarn, cloud !== null && cloud > L.cloudDanger, cloud === null)}
            ${qcell("🌧", "Rain rate", rain, 2, false, rain !== null && rain.value > 0, rain === null)}
            ${qcell("🌡", "Sky temp", skyT, 1, false, false, skyT === null)}
            ${cell("👁", "Seeing", seeing?.toFixed(1) ?? null, "\"", seeing !== null && seeing > L.seeingWarn, seeing !== null && seeing > L.seeingDanger, seeing === null)}
            ${qcell("✨", "Sky brightness", skyB, 2, false, false, skyB === null)}
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

        </div>
        `}
      </ha-card>
    `;

    this.shadowRoot.innerHTML = html;

    if (wxConnected && windDir !== null) {
      requestAnimationFrame(() => this._drawWindRose(windDir, windMs));
    }
  }

  // `"danger"`, `"warn"` or `null`, for a speed in m/s.
  _windLevel(speed) {
    if (speed === null) return null;
    return speed > this._limits.windDanger ? "danger"
      : speed > this._limits.windWarn ? "warn" : null;
  }

  // `speed` in m/s, whatever unit the sensor is shown in.
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

    // `dir` is meteorological, where the wind blows from; the head points there.
    const arrowRad = (dir - 90) * Math.PI / 180; // 0° = north = up
    const speedRatio = speed !== null ? Math.min(1, (speed || 0) / 20) : 0.5;
    const arrowLen = 12 + speedRatio * 10;
    const endX = cx + Math.cos(arrowRad) * arrowLen;
    const endY = cy + Math.sin(arrowRad) * arrowLen;
    const startX = cx - Math.cos(arrowRad) * arrowLen;
    const startY = cy - Math.sin(arrowRad) * arrowLen;

    const level = this._windLevel(speed);
    const color = level === "danger" ? "#e76f51" : level === "warn" ? "#f4a261" : "#5bcfcf";

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
  static getConfigForm() {
    const number = (unit, extra = {}) => ({
      selector: { number: { step: "any", mode: "box", unit_of_measurement: unit, ...extra } },
    });
    const percent = number("%", { min: 0, max: 100 });
    // Nameless, so each limit stays a top-level key instead of nesting under it.
    const pair = (schema) => ({ type: "grid", name: "", schema });
    return configForm([
      {
        type: "expandable",
        name: "",
        title: "Limits",
        schema: [
          {
            name: "dew_margin",
            label: "Dew margin",
            helper: "Show the dew alert while the air is within this of its dew point. "
              + "Smaller with dew heaters on the optics. In °C, whatever unit the "
              + "temperature is shown in.",
            default: LIMITS.dew_margin,
            ...number("°C", { min: 0 }),
          },
          pair([
            {
              name: "temperature_high",
              label: "Warm above",
              helper: "Warning. In °C.",
              default: LIMITS.temperature_high,
              ...number("°C"),
            },
            {
              name: "temperature_low",
              label: "Cold below",
              helper: "Danger. In °C.",
              default: LIMITS.temperature_low,
              ...number("°C"),
            },
          ]),
          pair([
            { name: "humidity_warn", label: "Humidity warning above", default: LIMITS.humidity_warn, ...percent },
            { name: "humidity_danger", label: "Humidity danger above", default: LIMITS.humidity_danger, ...percent },
          ]),
          pair([
            {
              name: "wind_warn",
              label: "Wind warning above",
              helper: "In m/s, whatever unit the speed is shown in: 1 m/s is 3.6 km/h or 2.24 mph.",
              default: LIMITS.wind_warn,
              ...number("m/s", { min: 0 }),
            },
            {
              name: "wind_danger",
              label: "Wind danger above",
              helper: "In m/s. Also colours the wind rose's arrow.",
              default: LIMITS.wind_danger,
              ...number("m/s", { min: 0 }),
            },
          ]),
          pair([
            { name: "cloud_warn", label: "Cloud warning above", default: LIMITS.cloud_warn, ...percent },
            { name: "cloud_danger", label: "Cloud danger above", default: LIMITS.cloud_danger, ...percent },
          ]),
          pair([
            {
              name: "seeing_warn",
              label: "Seeing warning above",
              helper: "Star FWHM.",
              default: LIMITS.seeing_warn,
              ...number("arcsec", { min: 0 }),
            },
            {
              name: "seeing_danger",
              label: "Seeing danger above",
              default: LIMITS.seeing_danger,
              ...number("arcsec", { min: 0 }),
            },
          ]),
        ],
      },
    ]);
  }

  static getStubConfig() { return {}; }
}

// Guarded: a stale 1.4.5 `/local/` resource defining the same tag would
// otherwise throw and abort the rest of this module.
if (!customElements.get("nina-weather-card")) {
  customElements.define("nina-weather-card", NinaWeatherCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-weather-card",
  name: "N.I.N.A. Weather & Safety Card",
  description: "Live weather station readings and safety monitor status from N.I.N.A.",
  preview: true,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-WEATHER-CARD %c v${VERSION} `,
  "background:#0d1b2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #5bcfcf",
  "background:#5bcfcf;color:#0d1b2e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

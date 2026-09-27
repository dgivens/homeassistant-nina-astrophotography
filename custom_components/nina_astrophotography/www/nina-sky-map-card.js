/**
 * N.I.N.A. Sky Map Card
 *
 * Displays a live all-sky stereographic projection showing where the
 * telescope is currently pointing, with altitude rings, cardinal directions,
 * a meridian line, and a trail of recent positions.
 *
 * Reads the mount's altitude, azimuth, RA, declination, sidereal time, time to
 * meridian flip and tracking rate, its park state, the sequence target, and the
 * site latitude the star field is projected from.
 *
 * Ships with the integration and registers itself as a dashboard resource —
 * nothing to copy or add under Resources. One rig needs no configuration at
 * all: the card finds its own equipment in the registry.
 *   type: custom:nina-sky-map-card
 *   trail_length: 60    # how many historical positions to keep (default 60)
 *   map_size: 320       # the map's width and height in px (default 320)
 *   device_id: abc123   # which rig, for two or more; any one of its devices
 *   latitude: 38.5      # override the site latitude N.I.N.A. reports
 *   prefix: n_i_n_a     # fallback only, for the entities that cannot resolve
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import { RigEntities } from "./nina-entity-resolver.js";
import { missing, quantityIn } from "./nina-units.js";

const VERSION = "2.0.0";

const DEFAULT_TRAIL_LENGTH = 60;
const DEFAULT_MAP_SIZE = 320;

// Projected at render time from RA/Dec and the mount's sidereal time, so the
// field rotates correctly.
const BRIGHT_STARS = [
  { name: "Sirius",    ra: 6.7525,  dec: -16.7161 },
  { name: "Canopus",   ra: 6.3992,  dec: -52.6956 },
  { name: "Arcturus",  ra: 14.2612, dec: 19.1822  },
  { name: "Vega",      ra: 18.6157, dec: 38.7837  },
  { name: "Capella",   ra: 5.2781,  dec: 45.9980  },
  { name: "Rigel",     ra: 5.2423,  dec: -8.2016  },
  { name: "Procyon",   ra: 7.6553,  dec: 5.2250   },
  { name: "Betelgeuse",ra: 5.9195,  dec: 7.4071   },
  { name: "Altair",    ra: 19.8464, dec: 8.8683   },
  { name: "Aldebaran", ra: 4.5987,  dec: 16.5093  },
  { name: "Antares",   ra: 16.4901, dec: -26.4320 },
  { name: "Spica",     ra: 13.4199, dec: -11.1614 },
  { name: "Pollux",    ra: 7.7553,  dec: 28.0262  },
  { name: "Fomalhaut", ra: 22.9608, dec: -29.6224 },
  { name: "Deneb",     ra: 20.6905, dec: 45.2803  },
  { name: "Regulus",   ra: 10.1395, dec: 11.9672  },
  { name: "Adhara",    ra: 6.9771,  dec: -28.9722 },
  { name: "Castor",    ra: 7.5767,  dec: 31.8883  },
  { name: "Shaula",    ra: 17.5600, dec: -37.1038 },
  { name: "Bellatrix", ra: 5.4188,  dec: 6.3497   },
  { name: "Mira",      ra: 2.3222,  dec: -2.9779  },
  { name: "Mimosa",    ra: 12.7953, dec: -59.6887 },
  { name: "Dubhe",     ra: 11.0621, dec: 61.7510  },
  { name: "Alkaid",    ra: 13.7923, dec: 49.3133  },
  { name: "Kaus Aust.", ra: 18.4028, dec: -34.3846 },
  { name: "Atria",     ra: 16.8113, dec: -69.0277 },
  { name: "Alhena",    ra: 6.6285,  dec: 16.3993  },
  { name: "Peacock",   ra: 20.4271, dec: -56.7350 },
  { name: "Menkent",   ra: 14.1114, dec: -36.3700 },
  { name: "Mirfak",    ra: 3.4053,  dec: 49.8612  },
  { name: "Nunki",     ra: 18.9211, dec: -26.2967 },
  { name: "Alphard",   ra: 9.4598,  dec: -8.6584  },
  { name: "Merak",     ra: 11.0306, dec: 56.3824  },
  { name: "Phecda",    ra: 11.8971, dec: 53.6948  },
  { name: "Megrez",    ra: 12.2570, dec: 57.0326  },
  { name: "Alioth",    ra: 12.9004, dec: 55.9598  },
  { name: "Mizar",     ra: 13.3988, dec: 54.9254  },
  { name: "Polaris",   ra: 2.5300,  dec: 89.2641  },
  { name: "Denebola",  ra: 11.8177, dec: 14.5720  },
  { name: "Alnitak",   ra: 5.6796,  dec: -1.9426  },
  { name: "Alnilam",   ra: 5.6033,  dec: -1.2019  },
  { name: "Mintaka",   ra: 5.5333,  dec: -0.2990  },
];

const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

function hmsToRad(h) { return h * 15 * DEG; }

/** Equatorial (ra_hours, dec_deg) → horizontal (alt_deg, az_deg), given
    observer latitude and local sidereal time. */
function equToHoriz(ra_h, dec_deg, lat_deg, lst_h) {
  const ha  = ((lst_h - ra_h + 24) % 24) * 15 * DEG;  // hour angle in radians
  const dec = dec_deg * DEG;
  const lat = lat_deg * DEG;
  const sinAlt = Math.sin(dec) * Math.sin(lat)
               + Math.cos(dec) * Math.cos(lat) * Math.cos(ha);
  const alt = Math.asin(Math.clamp ? Math.clamp(sinAlt, -1, 1)
                                   : Math.max(-1, Math.min(1, sinAlt))) * RAD;
  const cosAz = (Math.sin(dec) - Math.sin(alt * DEG) * Math.sin(lat))
              / (Math.cos(alt * DEG) * Math.cos(lat));
  const az0 = Math.acos(Math.max(-1, Math.min(1, cosAz))) * RAD;
  const az  = Math.sin(ha) > 0 ? 360 - az0 : az0;
  return { alt, az };
}

/** Stereographic projection: alt/az → unit circle (x,y), [-1,1].
    Zenith is centre, horizon the edge; az 0° (north) is up. */
function project(alt_deg, az_deg) {
  const r = Math.cos(alt_deg * DEG) / (1 + Math.sin(alt_deg * DEG));
  const a = (az_deg - 180) * DEG;   // rotate so N is up (canvas y increases down)
  return {
    x:  r * Math.sin(a),
    y: -r * Math.cos(a),
  };
}

const STYLE = `
  :host {
    --bg: var(--ha-card-background, var(--card-background-color, #12121e));
    --border: var(--divider-color, rgba(255,255,255,0.1));
    --accent: #7b8de8;
    --accent2: #5bcfcf;
    --warn: #f4a261;
    --danger: #e76f51;
    --success: #57cc99;
    --muted: rgba(255,255,255,0.4);
    --text: rgba(255,255,255,0.92);
    font-family: var(--primary-font-family, Roboto, sans-serif);
  }
  ha-card {
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    padding: 0;
    user-select: none;
  }
  .header {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px 10px;
    border-bottom: 1px solid var(--border);
    background: rgba(123,141,232,0.07);
  }
  .header .title { font-size: 1rem; font-weight: 600; flex: 1; }
  .header .sub { font-size: 0.68rem; color: var(--muted); margin-top: 1px; }

  .map-wrap {
    position: relative;
    padding: 12px 12px 4px;
    display: flex; justify-content: center;
  }
  canvas#sky { display: block; border-radius: 50%; cursor: crosshair; }

  /* Compass labels positioned around the canvas via JS */
  .compass-label {
    position: absolute;
    font-size: 0.65rem;
    font-weight: 700;
    color: rgba(255,255,255,0.45);
    letter-spacing: .5px;
    pointer-events: none;
    transform: translate(-50%, -50%);
  }

  .info-row {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr 1fr;
    gap: 1px;
    background: var(--border);
    border-top: 1px solid var(--border);
  }
  .info-cell {
    background: var(--bg);
    padding: 8px 10px;
    display: flex; flex-direction: column; gap: 1px;
  }
  .info-cell .lbl { font-size: 0.58rem; font-weight: 700; letter-spacing: .7px; text-transform: uppercase; color: var(--muted); }
  .info-cell .val { font-size: 0.82rem; font-weight: 600; }

  .status-bar {
    display: flex; align-items: center; gap: 6px;
    padding: 6px 14px 10px;
    font-size: 0.68rem; color: var(--muted);
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .dot.on  { background: var(--success); box-shadow: 0 0 5px var(--success); }
  .dot.warn { background: var(--warn); }
  .dot.off { background: var(--muted); }

  .no-mount {
    padding: 32px 16px; text-align: center;
    color: var(--muted); font-size: 0.82rem;
  }
  .no-mount .icon { font-size: 2.2rem; margin-bottom: 8px; }
`;

class NinaSkyMapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._trail = []; // {alt, az, ts}, recent pointing history
    this._lastAlt = null;
    this._lastAz  = null;
    this._animFrame = null;
    this._dpr = window.devicePixelRatio || 1;
  }

  setConfig(config) {
    // Per key: the editor sends a cleared field as `undefined`.
    this._config = {
      ...config,
      trail_length: config.trail_length ?? DEFAULT_TRAIL_LENGTH,
      map_size: config.map_size ?? DEFAULT_MAP_SIZE,
    };
    this._rig = new RigEntities(
      this._config.prefix || DEFAULT_PREFIX, this._config.device_id);
  }

  connectedCallback() {
    this._startAnimation();
  }

  disconnectedCallback() {
    if (this._animFrame) cancelAnimationFrame(this._animFrame);
  }

  set hass(hass) {
    this._hass = hass;
    this._rig.refresh(hass);
    this._updateTrail();
    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
    }
    this._updateInfoRow();
    this._updateStatusBar();
  }

  // Falls back to a prefixed `slug` when nothing resolves; every read here is
  // a mount entity whose name matches its key.
  _eid(domain, key, slug = key) {
    return this._rig.id(domain, key, slug);
  }

  _s(id, fallback = null) {
    const e = this._hass?.states[id];
    return e ? e.state : fallback;
  }
  _f(id) {
    const value = parseFloat(this._s(id));
    return Number.isFinite(value) ? value : null;
  }
  _on(id) { return this._s(id) === "on"; }
  // Time to the flip in minutes, whatever unit the sensor is shown in.
  _flipMinutes(id) {
    return quantityIn(this._hass, id, "min");
  }

  // A disconnected device makes its entities unavailable, so availability is
  // "connected". `unknown` also counts as disconnected.
  _available(id) {
    return !missing(this._s(id));
  }
  // Tracking is one of the mount's own rates, and `Stopped` is one of them.
  _tracking(id) {
    return this._available(id) && this._s(id) !== "Stopped";
  }

  // The star field's latitude: an explicit `latitude:`, else N.I.N.A.'s
  // configured site (readable with the mount disconnected), else Home
  // Assistant's own location.
  _latitude() {
    if (this._config.latitude !== undefined) return this._config.latitude;
    const site = this._f(this._eid("sensor", "site_latitude"));
    if (site !== null) return site;
    const home = this._hass?.config?.latitude;
    return Number.isFinite(home) ? home : 0;
  }

  _updateTrail() {
    const alt = this._f(this._eid("sensor", "mount_altitude")) ?? 0;
    const az  = this._f(this._eid("sensor", "mount_azimuth")) ?? 0;
    if (alt === this._lastAlt && az === this._lastAz) return;
    this._lastAlt = alt;
    this._lastAz  = az;
    if (alt > 0) {
      this._trail.push({ alt, az, ts: Date.now() });
      const maxLen = this._config.trail_length;
      if (this._trail.length > maxLen) this._trail.shift();
    }
  }

  _buildDOM() {
    const size = this._config.map_size;
    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <span style="font-size:1.3rem">🌌</span>
          <div>
            <div class="title" id="hdr-title">Sky Map</div>
            <div class="sub" id="hdr-sub">Telescope pointing</div>
          </div>
        </div>
        <div class="map-wrap" id="map-wrap">
          <canvas id="sky" width="${size * this._dpr}" height="${size * this._dpr}"
            style="width:${size}px;height:${size}px;"></canvas>
          <span class="compass-label" id="cl-n"  style="top:8px;   left:50%">N</span>
          <span class="compass-label" id="cl-s"  style="bottom:8px;left:50%">S</span>
          <span class="compass-label" id="cl-e"  style="top:50%;   right:6px">E</span>
          <span class="compass-label" id="cl-w"  style="top:50%;   left:6px">W</span>
        </div>
        <div class="info-row">
          <div class="info-cell"><div class="lbl">Altitude</div><div class="val" id="inf-alt">—</div></div>
          <div class="info-cell"><div class="lbl">Azimuth</div><div class="val" id="inf-az">—</div></div>
          <div class="info-cell"><div class="lbl">RA</div><div class="val" id="inf-ra">—</div></div>
          <div class="info-cell"><div class="lbl">Dec</div><div class="val" id="inf-dec">—</div></div>
        </div>
        <div class="status-bar" id="status-bar"></div>
      </ha-card>
    `;
    this.shadowRoot.innerHTML = html;
    this._canvas = this.shadowRoot.getElementById("sky");
    this._ctx    = this._canvas.getContext("2d");
    this._canvas.addEventListener("click", e => this._onCanvasClick(e));
    this._canvas.addEventListener("mousemove", e => this._onCanvasHover(e));
  }

  _updateInfoRow() {
    const set = (id, v) => {
      const el = this.shadowRoot?.getElementById(id);
      if (el) el.textContent = v;
    };

    // A down driver's `unavailable` parses to 0°, a pointing at the horizon,
    // not a blank; keep the dash instead.
    const raId = this._eid("sensor", "mount_right_ascension");
    if (this._available(raId)) {
      const alt = this._f(this._eid("sensor", "mount_altitude")) ?? 0;
      const az  = this._f(this._eid("sensor", "mount_azimuth")) ?? 0;
      const dec = this._f(this._eid("sensor", "mount_declination")) ?? 0;
      set("inf-alt",  alt.toFixed(1) + "°");
      set("inf-az",   az.toFixed(1)  + "°");
      set("inf-ra",   raToString(this._f(raId) ?? 0));
      set("inf-dec",  decToString(dec));
    } else {
      for (const cell of ["inf-alt", "inf-az", "inf-ra", "inf-dec"]) set(cell, "—");
    }

    // Gated on its own availability, not the mount's: the sequence outlives a
    // driver dropping out.
    const targetId = this._eid("sensor", "sequence_target");
    const target = this._available(targetId) ? this._s(targetId, "") : "";
    const ttf = this._flipMinutes(this._eid("sensor", "mount_time_to_meridian_flip"));

    const sub = this.shadowRoot?.getElementById("hdr-sub");
    if (sub) {
      sub.textContent = target
        ? `${target} · flip in ${ttf !== null ? ttf.toFixed(0) + " min" : "—"}`
        : "Telescope pointing";
    }
  }

  _updateStatusBar() {
    const bar = this.shadowRoot?.getElementById("status-bar");
    if (!bar) return;
    const connected = this._available(this._eid("sensor", "mount_right_ascension"));
    const tracking  = this._tracking(this._eid("select", "mount_tracking_rate"));
    const parked    = this._on(this._eid("binary_sensor", "mount_at_park"));

    const chips = [];
    if (!connected) {
      chips.push(`<span class="dot off"></span> Mount disconnected`);
    } else if (parked) {
      chips.push(`<span class="dot warn"></span> Parked`);
    } else if (tracking) {
      chips.push(`<span class="dot on"></span> Tracking`);
    } else {
      chips.push(`<span class="dot off"></span> Not tracking`);
    }
    bar.innerHTML = chips.join("&nbsp;&nbsp;");
  }

  // ── Canvas interaction ────────────────────────────────────────────────

  _canvasCoordToAltAz(cx, cy) {
    const size = this._config.map_size;
    const R = size / 2;
    const nx = (cx - R) / R;
    const ny = (cy - R) / R;
    const r  = Math.sqrt(nx * nx + ny * ny);
    if (r > 1) return null;
    const sinAlt = (1 - r * r) / (1 + r * r);
    const alt = Math.asin(sinAlt) * RAD;
    const az  = ((Math.atan2(nx, -ny) * RAD) + 360 + 180) % 360;
    return { alt: alt.toFixed(1), az: az.toFixed(1) };
  }

  _onCanvasClick(e) {
    const rect  = this._canvas.getBoundingClientRect();
    const coord = this._canvasCoordToAltAz(e.clientX - rect.left, e.clientY - rect.top);
    if (!coord) return;
    console.info(`[NINA Sky Map] Clicked: Alt ${coord.alt}° Az ${coord.az}°`);
  }

  _onCanvasHover(e) {}

  _startAnimation() {
    const loop = () => {
      if (this._canvas && this._ctx && this._hass) {
        this._drawFrame();
      }
      this._animFrame = requestAnimationFrame(loop);
    };
    loop();
  }

  _drawFrame() {
    const ctx  = this._ctx;
    const size = this._config.map_size;
    const dpr  = this._dpr;
    const W    = size * dpr;
    const H    = size * dpr;
    const cx   = W / 2;
    const cy   = H / 2;
    const R    = (size / 2 - 4) * dpr; // 4px margin

    ctx.clearRect(0, 0, W, H);

    const skyGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
    skyGrad.addColorStop(0,   "#0d1b2e");
    skyGrad.addColorStop(0.6, "#091525");
    skyGrad.addColorStop(1,   "#060e1a");
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.fillStyle = skyGrad;
    ctx.fill();

    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.clip();

    const proj = (alt, az) => {
      const p = project(alt, az);
      return { x: cx + p.x * R, y: cy + p.y * R };
    };

    for (const alt of [0, 15, 30, 45, 60, 75]) {
      const r_ring = Math.cos(alt * DEG) / (1 + Math.sin(alt * DEG)) * R;
      ctx.beginPath();
      ctx.arc(cx, cy, r_ring, 0, Math.PI * 2);
      ctx.strokeStyle = alt === 0 ? "rgba(255,255,255,0.25)" : "rgba(255,255,255,0.08)";
      ctx.lineWidth   = alt === 0 ? 1.5 * dpr : 0.5 * dpr;
      ctx.stroke();
      if (alt > 0 && alt < 75) {
        const lx = cx + 4 * dpr;
        const ly = cy - r_ring + 10 * dpr;
        ctx.fillStyle = "rgba(255,255,255,0.25)";
        ctx.font = `${9 * dpr}px sans-serif`;
        ctx.fillText(`${alt}°`, lx, ly);
      }
    }

    for (let az = 0; az < 360; az += 45) {
      const p = proj(0, az);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(p.x, p.y);
      ctx.strokeStyle = az % 90 === 0
        ? "rgba(255,255,255,0.12)"
        : "rgba(255,255,255,0.05)";
      ctx.lineWidth = 0.5 * dpr;
      ctx.setLineDash([4 * dpr, 6 * dpr]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // The flip fires at the sensor's own published offset, not zero.
    const flipId = this._eid("sensor", "mount_time_to_meridian_flip");
    const ttf = this._flipMinutes(flipId);
    const firesAt = parseFloat(
      this._hass?.states?.[flipId]?.attributes?.flip_fires_at_minutes) || 0;
    const flipSoon = ttf !== null && ttf > 0 && ttf < 15 + firesAt;
    const meridianColor = flipSoon
      ? `rgba(244, 162, 97, ${0.5 + 0.4 * Math.sin(Date.now() / 400)})`
      : "rgba(123,141,232,0.25)";
    ctx.beginPath();
    ctx.moveTo(cx, cy - R);
    ctx.lineTo(cx, cy + R);
    ctx.strokeStyle = meridianColor;
    ctx.lineWidth   = 1.5 * dpr;
    ctx.setLineDash([6 * dpr, 5 * dpr]);
    ctx.stroke();
    ctx.setLineDash([]);

    this._drawMilkyWay(ctx, cx, cy, R);

    const lat = this._latitude();
    const siderealId = this._eid("sensor", "mount_sidereal_time");
    const lst = this._f(siderealId) ?? 12; // noon fallback
    const connectedST = this._available(siderealId);

    if (connectedST) {
      for (const [idx, star] of BRIGHT_STARS.entries()) {
        const h = equToHoriz(star.ra, star.dec, lat, lst);
        if (h.alt < -5) continue;
        const p = proj(h.alt, h.az);
        // Brighter stars are listed first.
        const size_px = idx < 5 ? 2.5 : idx < 15 ? 1.8 : 1.2;
        const alpha = h.alt < 5
          ? 0.2 + (h.alt / 5) * 0.5
          : 0.3 + Math.random() * 0.05; // twinkle
        ctx.beginPath();
        ctx.arc(p.x, p.y, size_px * dpr, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(220, 230, 255, ${alpha})`;
        ctx.fill();
        if (idx < 8 && h.alt > 10) {
          ctx.font = `${8 * dpr}px sans-serif`;
          ctx.fillStyle = "rgba(180,190,255,0.45)";
          ctx.fillText(star.name, p.x + 4 * dpr, p.y - 3 * dpr);
        }
      }
    }

    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(87, 204, 153, 0.6)";
    ctx.lineWidth   = 2 * dpr;
    ctx.stroke();

    if (this._trail.length > 1) {
      ctx.beginPath();
      for (let i = 0; i < this._trail.length; i++) {
        const pt = this._trail[i];
        const p  = proj(pt.alt, pt.az);
        const alpha = (i / this._trail.length) * 0.6;
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }
      ctx.strokeStyle = "rgba(91,207,207,0.4)";
      ctx.lineWidth   = 1.5 * dpr;
      ctx.lineJoin    = "round";
      ctx.stroke();
    }

    const alt = this._f(this._eid("sensor", "mount_altitude")) ?? 0;
    const az  = this._f(this._eid("sensor", "mount_azimuth")) ?? 0;
    const isParked   = this._on(this._eid("binary_sensor", "mount_at_park"));
    const isTracking = this._tracking(this._eid("select", "mount_tracking_rate"));
    const isMounted  = this._available(this._eid("sensor", "mount_right_ascension"));

    if (isMounted && alt >= 0) {
      const p = proj(alt, az);

      const glowR = 14 * dpr;
      const glow  = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowR);
      const glowColor = isParked ? "244,162,97"
                      : isTracking ? "91,207,207"
                      : "123,141,232";
      glow.addColorStop(0,   `rgba(${glowColor},0.35)`);
      glow.addColorStop(1,   `rgba(${glowColor},0)`);
      ctx.beginPath();
      ctx.arc(p.x, p.y, glowR, 0, Math.PI * 2);
      ctx.fillStyle = glow;
      ctx.fill();

      const crossSize = 10 * dpr;
      ctx.strokeStyle = `rgba(${glowColor},0.7)`;
      ctx.lineWidth   = 1 * dpr;
      ctx.beginPath();
      ctx.moveTo(p.x - crossSize, p.y); ctx.lineTo(p.x + crossSize, p.y);
      ctx.moveTo(p.x, p.y - crossSize); ctx.lineTo(p.x, p.y + crossSize);
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(p.x, p.y, 6 * dpr, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${glowColor},0.9)`;
      ctx.lineWidth   = 1.5 * dpr;
      ctx.stroke();

      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.5 * dpr, 0, Math.PI * 2);
      ctx.fillStyle   = `rgba(${glowColor},1)`;
      ctx.fill();

      ctx.font      = `bold ${9 * dpr}px sans-serif`;
      ctx.fillStyle = `rgba(${glowColor},0.9)`;
      ctx.fillText(`${alt.toFixed(1)}°`, p.x + 10 * dpr, p.y - 8 * dpr);
    }

    ctx.beginPath();
    ctx.arc(cx, cy, 2.5 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.3)";
    ctx.fill();

    ctx.restore();

    if (flipSoon) {
      ctx.font      = `bold ${10 * dpr}px sans-serif`;
      ctx.fillStyle = "rgba(244,162,97,0.9)";
      ctx.textAlign = "center";
      ctx.fillText(`⚠ Flip in ${ttf.toFixed(0)} min`, cx, cy + R + 18 * dpr);
      ctx.textAlign = "start";
    }
  }

  _drawMilkyWay(ctx, cx, cy, R) {
    // A tilted, translucent ellipse; the galactic plane runs roughly NE–SW.
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(35 * DEG);
    const mwGrad = ctx.createLinearGradient(-R, 0, R, 0);
    mwGrad.addColorStop(0,   "rgba(120,140,200,0)");
    mwGrad.addColorStop(0.3, "rgba(120,140,200,0.05)");
    mwGrad.addColorStop(0.5, "rgba(150,170,220,0.08)");
    mwGrad.addColorStop(0.7, "rgba(120,140,200,0.05)");
    mwGrad.addColorStop(1,   "rgba(120,140,200,0)");
    ctx.fillStyle = mwGrad;
    ctx.beginPath();
    ctx.ellipse(0, 0, R * 0.92, R * 0.18, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  }

  static getConfigForm() {
    return configForm([
      {
        name: "trail_length",
        label: "Trail length",
        helper: "Past pointing positions to draw, one per poll: 60 is about 10 minutes "
          + "at the default interval. Starts empty when the page loads.",
        default: DEFAULT_TRAIL_LENGTH,
        selector: { number: { min: 0, mode: "box" } },
      },
      {
        name: "map_size",
        label: "Map size",
        helper: "Width and height. Fixed; does not follow the card's width.",
        default: DEFAULT_MAP_SIZE,
        selector: { number: { min: 200, max: 800, mode: "box", unit_of_measurement: "px" } },
      },
      {
        name: "latitude",
        label: "Latitude override",
        helper: "North positive. Moves only the star field. Leave empty to use the site "
          + "N.I.N.A. is configured for, then Home Assistant's location.",
        selector: { number: { min: -90, max: 90, step: "any", mode: "box", unit_of_measurement: "°" } },
      },
    ]);
  }
}

function raToString(ra_h) {
  if (!ra_h && ra_h !== 0) return "—";
  const h  = Math.floor(ra_h);
  const m  = Math.floor((ra_h - h) * 60);
  const s  = Math.floor(((ra_h - h) * 60 - m) * 60);
  return `${h}h ${m.toString().padStart(2,"0")}m ${s.toString().padStart(2,"0")}s`;
}

function decToString(dec) {
  if (dec === null || dec === undefined) return "—";
  const sign = dec >= 0 ? "+" : "−";
  const abs  = Math.abs(dec);
  const d    = Math.floor(abs);
  const m    = Math.floor((abs - d) * 60);
  const s    = Math.floor(((abs - d) * 60 - m) * 60);
  return `${sign}${d}° ${m.toString().padStart(2,"0")}′ ${s.toString().padStart(2,"0")}″`;
}

// Guarded: a stale 1.4.5 `/local/` resource defining the same tag would
// otherwise throw and abort the rest of this module.
if (!customElements.get("nina-sky-map-card")) {
  customElements.define("nina-sky-map-card", NinaSkyMapCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-sky-map-card",
  name: "N.I.N.A. Sky Map Card",
  description: "Live all-sky stereographic map showing telescope pointing, star field, and meridian.",
  preview: true,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-SKY-MAP-CARD %c v${VERSION} `,
  "background:#0d1b2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #5bcfcf",
  "background:#5bcfcf;color:#0d1b2e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

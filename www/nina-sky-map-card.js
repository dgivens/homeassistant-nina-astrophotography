/**
 * N.I.N.A. Sky Map Card  v1.0.0
 *
 * Displays a live all-sky stereographic projection showing where the
 * telescope is currently pointing, with altitude rings, cardinal directions,
 * a meridian line, and a trail of recent positions.
 *
 * Reads from (shown without the instance prefix the card adds at lookup time,
 * so sensor.mount_altitude resolves to sensor.nina_mount_altitude by default):
 *   sensor.mount_altitude                 (degrees, 0–90)
 *   sensor.mount_azimuth                  (degrees, 0–360, N=0)
 *   sensor.mount_ra                       (decimal hours)
 *   sensor.mount_dec                      (decimal degrees)
 *   sensor.mount_time_to_meridian_flip    (hours)
 *   sensor.sequence_target
 *   binary_sensor.mount_connected
 *   binary_sensor.mount_tracking
 *   binary_sensor.mount_parked
 *   binary_sensor.mount_slewing
 *
 * Installation:
 *   1. Copy to /config/www/nina-sky-map-card.js
 *   2. Add resource: /local/nina-sky-map-card.js  (JavaScript Module)
 *   3. Add card:  type: custom:nina-sky-map-card
 *      Optional config:
 *        latitude: 38.5    # your observing latitude (improves horizon shading)
 *        trail_length: 60  # number of historical positions to keep (default 60)
 *        show_constellations: true
 */

const VERSION = "1.0.0";

// Entity ids are prefixed with the instance name (device names drive entity
// ids since 2.0). Default "nina"; override with `prefix:` in the card config
// when you run more than one N.I.N.A. instance.
function withPrefix(entityId, prefix) {
  const dot = entityId.indexOf(".");
  return entityId.slice(0, dot + 1) + (prefix || "nina") + "_" + entityId.slice(dot + 1);
}


/* ── Notable stars with alt/az computed at runtime from RA/Dec + observer lat ──
   We store as { name, ra_h, dec_deg } and project at render time using
   the mount's current sidereal time so the star field rotates correctly.     */
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

/* ── Constellation lines as pairs of star indices into BRIGHT_STARS ── */
const ORION_BELT = [39, 40, 41]; // Alnitak, Alnilam, Mintaka
const BIG_DIPPER = [22, 23, 25, 33, 34, 35, 36]; // approximate subset

/* ── Math helpers ──────────────────────────────────────────────────── */
const DEG = Math.PI / 180;
const RAD = 180 / Math.PI;

function hmsToRad(h) { return h * 15 * DEG; }

/** Convert equatorial (ra_hours, dec_deg) → horizontal (alt_deg, az_deg)
    given observer latitude (lat_deg) and local sidereal time (lst_hours). */
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

/** Stereographic projection: alt/az → canvas (x,y) in unit circle [-1,1].
    Zenith = centre, horizon = edge.  Az 0° = North = top.               */
function project(alt_deg, az_deg) {
  const r = Math.cos(alt_deg * DEG) / (1 + Math.sin(alt_deg * DEG));
  const a = (az_deg - 180) * DEG;   // rotate so N is up (canvas y increases down)
  return {
    x:  r * Math.sin(a),
    y: -r * Math.cos(a),
  };
}

/* ── Styles ─────────────────────────────────────────────────────────── */
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

/* ── Card class ──────────────────────────────────────────────────────── */
class NinaSkyMapCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._trail = [];        // [{x,y,az,alt,ts}]  recent pointing history
    this._lastAlt = null;
    this._lastAz  = null;
    this._animFrame = null;
    this._dpr = window.devicePixelRatio || 1;
  }

  setConfig(config) {
        this._prefix = (config && config.prefix) || "nina";
this._config = {
      latitude: 40,
      trail_length: 60,
      show_constellations: true,
      map_size: 320,
      ...config,
    };
  }

  connectedCallback() {
    this._startAnimation();
  }

  disconnectedCallback() {
    if (this._animFrame) cancelAnimationFrame(this._animFrame);
  }

  set hass(hass) {
    this._hass = hass;
    this._updateTrail();
    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
    }
    this._updateInfoRow();
    this._updateStatusBar();
  }

  _s(id, fallback = null) {
    const e = this._hass?.states[withPrefix(id, this._prefix)];
    return e ? e.state : fallback;
  }
  _f(id, fallback = 0) {
    return parseFloat(this._s(id, fallback)) || fallback;
  }
  _on(id) { return this._s(id) === "on"; }

  _updateTrail() {
    const alt = this._f("sensor.mount_altitude");
    const az  = this._f("sensor.mount_azimuth");
    if (alt === this._lastAlt && az === this._lastAz) return;
    this._lastAlt = alt;
    this._lastAz  = az;
    if (alt > 0) {  // only record when above horizon
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
    const alt = this._f("sensor.mount_altitude");
    const az  = this._f("sensor.mount_azimuth");
    const ra  = this._f("sensor.mount_ra");
    const dec = this._f("sensor.mount_dec");
    const target = this._s("sensor.sequence_target", "");
    const ttf    = this._f("sensor.mount_time_to_meridian_flip", 999);

    const set = (id, v) => {
      const el = this.shadowRoot?.getElementById(id);
      if (el) el.textContent = v;
    };
    set("inf-alt",  alt.toFixed(1) + "°");
    set("inf-az",   az.toFixed(1)  + "°");
    set("inf-ra",   raToString(ra));
    set("inf-dec",  decToString(dec));

    const sub = this.shadowRoot?.getElementById("hdr-sub");
    if (sub) {
      sub.textContent = target
        ? `${target} · flip in ${ttf < 999 ? ttf.toFixed(0) + " min" : "—"}`
        : "Telescope pointing";
    }
  }

  _updateStatusBar() {
    const bar = this.shadowRoot?.getElementById("status-bar");
    if (!bar) return;
    const connected = this._on("binary_sensor.mount_connected");
    const tracking  = this._on("binary_sensor.mount_tracking");
    const parked    = this._on("binary_sensor.mount_parked");
    const slewing   = this._on("binary_sensor.mount_slewing");

    const chips = [];
    if (!connected) {
      chips.push(`<span class="dot off"></span> Mount disconnected`);
    } else if (parked) {
      chips.push(`<span class="dot warn"></span> Parked`);
    } else if (slewing) {
      chips.push(`<span class="dot warn"></span> Slewing…`);
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
    // Inverse stereographic: r = cos(alt)/(1+sin(alt)) → alt
    const sinAlt = (1 - r * r) / (1 + r * r);
    const alt = Math.asin(sinAlt) * RAD;
    // az: atan2(x, -y) with N=top correction
    const az  = ((Math.atan2(nx, -ny) * RAD) + 360 + 180) % 360;
    return { alt: alt.toFixed(1), az: az.toFixed(1) };
  }

  _onCanvasClick(e) {
    const rect  = this._canvas.getBoundingClientRect();
    const coord = this._canvasCoordToAltAz(e.clientX - rect.left, e.clientY - rect.top);
    if (!coord) return;
    // Could trigger a slew — for now just show in console
    console.info(`[NINA Sky Map] Clicked: Alt ${coord.alt}° Az ${coord.az}°`);
  }

  _onCanvasHover(e) {
    // Future: tooltip showing star name on hover
  }

  // ── Animation loop ────────────────────────────────────────────────────

  _startAnimation() {
    const loop = () => {
      if (this._canvas && this._ctx && this._hass) {
        this._drawFrame();
      }
      this._animFrame = requestAnimationFrame(loop);
    };
    loop();
  }

  // ── Main draw ─────────────────────────────────────────────────────────

  _drawFrame() {
    const ctx  = this._ctx;
    const size = this._config.map_size;
    const dpr  = this._dpr;
    const W    = size * dpr;
    const H    = size * dpr;
    const cx   = W / 2;
    const cy   = H / 2;
    const R    = (size / 2 - 4) * dpr;   // usable radius (leave 4px margin)

    ctx.clearRect(0, 0, W, H);

    // ── Sky background (deep radial) ───────────────────────────────────
    const skyGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, R);
    skyGrad.addColorStop(0,   "#0d1b2e");
    skyGrad.addColorStop(0.6, "#091525");
    skyGrad.addColorStop(1,   "#060e1a");
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.fillStyle = skyGrad;
    ctx.fill();

    // ── Clip everything to the sky circle ─────────────────────────────
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.clip();

    const proj = (alt, az) => {
      const p = project(alt, az);
      return { x: cx + p.x * R, y: cy + p.y * R };
    };

    // ── Altitude rings ─────────────────────────────────────────────────
    for (const alt of [0, 15, 30, 45, 60, 75]) {
      const r_ring = Math.cos(alt * DEG) / (1 + Math.sin(alt * DEG)) * R;
      ctx.beginPath();
      ctx.arc(cx, cy, r_ring, 0, Math.PI * 2);
      ctx.strokeStyle = alt === 0 ? "rgba(255,255,255,0.25)" : "rgba(255,255,255,0.08)";
      ctx.lineWidth   = alt === 0 ? 1.5 * dpr : 0.5 * dpr;
      ctx.stroke();
      // Label
      if (alt > 0 && alt < 75) {
        const lx = cx + 4 * dpr;
        const ly = cy - r_ring + 10 * dpr;
        ctx.fillStyle = "rgba(255,255,255,0.25)";
        ctx.font = `${9 * dpr}px sans-serif`;
        ctx.fillText(`${alt}°`, lx, ly);
      }
    }

    // ── Azimuth spokes (every 45°) ─────────────────────────────────────
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

    // ── Meridian line (azimuth 0° N–S through zenith) ─────────────────
    const ttf = this._f("sensor.mount_time_to_meridian_flip", 999);
    const meridianColor = ttf < 15 && ttf > 0
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

    // ── Milky Way (rough elliptical band for visual context) ───────────
    this._drawMilkyWay(ctx, cx, cy, R);

    // ── Stars ──────────────────────────────────────────────────────────
    const lat = this._config.latitude;
    const lst = this._f("sensor.mount_sidereal_time", 12);  // fallback to noon
    const connectedST = this._on("binary_sensor.mount_connected");

    if (connectedST) {
      for (const star of BRIGHT_STARS) {
        const h = equToHoriz(star.ra, star.dec, lat, lst);
        if (h.alt < -5) continue;  // below horizon
        const p = proj(h.alt, h.az);
        // Size by brightness (rough approximation — brighter stars listed first)
        const idx = BRIGHT_STARS.indexOf(star);
        const size_px = idx < 5 ? 2.5 : idx < 15 ? 1.8 : 1.2;
        const alpha = h.alt < 5
          ? 0.2 + (h.alt / 5) * 0.5
          : 0.3 + Math.random() * 0.05;  // subtle twinkle
        ctx.beginPath();
        ctx.arc(p.x, p.y, size_px * dpr, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(220, 230, 255, ${alpha})`;
        ctx.fill();
        // Label the 8 brightest
        if (idx < 8 && h.alt > 10) {
          ctx.font = `${8 * dpr}px sans-serif`;
          ctx.fillStyle = "rgba(180,190,255,0.45)";
          ctx.fillText(star.name, p.x + 4 * dpr, p.y - 3 * dpr);
        }
      }
    }

    // ── Horizon (thick outer ring with ground fill) ────────────────────
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.strokeStyle = "rgba(87, 204, 153, 0.6)";
    ctx.lineWidth   = 2 * dpr;
    ctx.stroke();

    // ── Pointing trail ─────────────────────────────────────────────────
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

    // ── Current pointing dot ───────────────────────────────────────────
    const alt = this._f("sensor.mount_altitude");
    const az  = this._f("sensor.mount_azimuth");
    const isParked   = this._on("binary_sensor.mount_parked");
    const isSlewing  = this._on("binary_sensor.mount_slewing");
    const isTracking = this._on("binary_sensor.mount_tracking");
    const isMounted  = this._on("binary_sensor.mount_connected");

    if (isMounted && alt >= 0) {
      const p = proj(alt, az);

      // Outer glow
      const glowR = (isSlewing ? 20 : 14) * dpr;
      const glow  = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowR);
      const glowColor = isParked  ? "244,162,97"
                      : isSlewing ? "231,111,81"
                      : isTracking ? "91,207,207"
                      : "123,141,232";
      glow.addColorStop(0,   `rgba(${glowColor},0.35)`);
      glow.addColorStop(1,   `rgba(${glowColor},0)`);
      ctx.beginPath();
      ctx.arc(p.x, p.y, glowR, 0, Math.PI * 2);
      ctx.fillStyle = glow;
      ctx.fill();

      // Reticle cross-hair
      const crossSize = 10 * dpr;
      ctx.strokeStyle = `rgba(${glowColor},0.7)`;
      ctx.lineWidth   = 1 * dpr;
      ctx.beginPath();
      ctx.moveTo(p.x - crossSize, p.y); ctx.lineTo(p.x + crossSize, p.y);
      ctx.moveTo(p.x, p.y - crossSize); ctx.lineTo(p.x, p.y + crossSize);
      ctx.stroke();

      // Circle reticle
      ctx.beginPath();
      ctx.arc(p.x, p.y, 6 * dpr, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(${glowColor},0.9)`;
      ctx.lineWidth   = 1.5 * dpr;
      ctx.stroke();

      // Inner dot
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.5 * dpr, 0, Math.PI * 2);
      ctx.fillStyle   = `rgba(${glowColor},1)`;
      ctx.fill();

      // Alt label next to dot
      ctx.font      = `bold ${9 * dpr}px sans-serif`;
      ctx.fillStyle = `rgba(${glowColor},0.9)`;
      ctx.fillText(`${alt.toFixed(1)}°`, p.x + 10 * dpr, p.y - 8 * dpr);
    }

    // ── Zenith dot ─────────────────────────────────────────────────────
    ctx.beginPath();
    ctx.arc(cx, cy, 2.5 * dpr, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(255,255,255,0.3)";
    ctx.fill();

    ctx.restore();  // end clip

    // ── Meridian flip warning label outside clip ───────────────────────
    if (ttf < 15 && ttf > 0) {
      ctx.font      = `bold ${10 * dpr}px sans-serif`;
      ctx.fillStyle = "rgba(244,162,97,0.9)";
      ctx.textAlign = "center";
      ctx.fillText(`⚠ Flip in ${ttf.toFixed(0)} min`, cx, cy + R + 18 * dpr);
      ctx.textAlign = "start";
    }
  }

  _drawMilkyWay(ctx, cx, cy, R) {
    // Simplified Milky Way band as a tilted elliptical arc
    // Galactic plane runs roughly NE–SW in the sky — drawn as translucent smear
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
}

/* ── Formatting helpers ──────────────────────────────────────────────── */
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

/* ── Register ─────────────────────────────────────────────────────────── */
customElements.define("nina-sky-map-card", NinaSkyMapCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-sky-map-card",
  name: "N.I.N.A. Sky Map Card",
  description: "Live all-sky stereographic map showing telescope pointing, star field, and meridian.",
  preview: true,
  documentationURL: "https://github.com/christian-photo/ninaAPI",
});

console.info(
  `%c NINA-SKY-MAP-CARD %c v${VERSION} `,
  "background:#0d1b2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #5bcfcf",
  "background:#5bcfcf;color:#0d1b2e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

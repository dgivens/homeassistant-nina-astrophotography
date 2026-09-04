/**
 * N.I.N.A. Image Panel Card  v1.0.0
 *
 * Displays the last captured image from N.I.N.A. using the Advanced API's
 * streaming image endpoint, with a live stats overlay, session image strip,
 * and histogram visualisation.
 *
 * API endpoints used:
 *   GET /v2/api/image?index=0&stream=true           → latest image (JPEG stream)
 *   GET /v2/api/image?index=N&stream=true           → Nth image from history
 *   GET /v2/api/image-history?all=true              → image history metadata
 *
 * Reads HA sensors for the overlay:
 *   sensor.last_frame_hfr, sensor.last_frame_stars, sensor.last_frame_mean_adu
 *   sensor.last_frame_filter, sensor.last_frame_exposure, sensor.last_frame_guide_rms
 *   sensor.last_frame_target, sensor.frame_session_count, sensor.session_integration_time
 *   binary_sensor.camera_connected, binary_sensor.camera_exposing
 *   sensor.frame_sparkline_data (for histogram data from extra attributes)
 *
 * Card config:
 *   type: custom:nina-image-panel-card
 *   host: 192.168.1.100     # N.I.N.A. PC IP (required)
 *   port: 1888              # API port (default 1888)
 *   refresh_on_save: true   # auto-refresh when IMAGE-SAVE fires via HA event (default true)
 *   show_strip: true        # show recent-frames strip at bottom (default true)
 *   show_histogram: true    # show ADU histogram bar (default true)
 *   quality: 85             # JPEG quality 1-100 (default 85)
 *   stretch: true           # use N.I.N.A.'s auto-stretch (default true)
 *   strip_count: 6          # number of thumbnails in the recent strip (default 6)
 */

const VERSION = "1.0.0";

const STYLE = `
  :host {
    --bg:      var(--ha-card-background, var(--card-background-color, #12121e));
    --border:  var(--divider-color, rgba(255,255,255,0.1));
    --accent:  #7b8de8;
    --accent2: #5bcfcf;
    --warn:    #f4a261;
    --success: #57cc99;
    --muted:   rgba(255,255,255,0.45);
    --text:    rgba(255,255,255,0.92);
    font-family: var(--primary-font-family, Roboto, sans-serif);
  }
  ha-card {
    background: var(--bg);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 16px;
    overflow: hidden;
    padding: 0;
  }

  /* ── Header ── */
  .header {
    display: flex; align-items: center; gap: 10px;
    padding: 12px 16px 10px;
    border-bottom: 1px solid var(--border);
    background: rgba(123,141,232,0.07);
  }
  .header .title { font-size: 1rem; font-weight: 600; flex: 1; }
  .header .sub { font-size: 0.68rem; color: var(--muted); margin-top: 1px; }
  .header .badge {
    font-size: 0.65rem; font-weight: 700; letter-spacing: .4px;
    padding: 3px 8px; border-radius: 20px;
    background: rgba(91,207,207,0.15); color: var(--accent2);
    border: 1px solid rgba(91,207,207,0.3);
  }
  .header .badge.warn { background: rgba(244,162,97,0.15); color: var(--warn); border-color: rgba(244,162,97,0.3); }

  /* ── Image container ── */
  .img-wrap {
    position: relative;
    background: #000;
    width: 100%;
    aspect-ratio: 4/3;
    overflow: hidden;
    cursor: zoom-in;
  }
  .img-wrap img {
    width: 100%; height: 100%;
    object-fit: contain;
    display: block;
    transition: opacity 0.3s ease;
  }
  .img-wrap img.loading { opacity: 0.4; }
  .img-wrap .spinner {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%,-50%);
    width: 32px; height: 32px;
    border: 2px solid rgba(255,255,255,0.15);
    border-top-color: var(--accent2);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    display: none;
  }
  .img-wrap .spinner.active { display: block; }
  @keyframes spin { to { transform: translate(-50%,-50%) rotate(360deg); } }

  /* ── Stats overlay ── */
  .overlay {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 10px 12px 8px;
    background: linear-gradient(transparent, rgba(0,0,0,0.75));
    display: flex; align-items: flex-end; justify-content: space-between;
    gap: 8px;
  }
  .overlay-left { display: flex; flex-wrap: wrap; gap: 5px; }
  .stat-pill {
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(0,0,0,0.55); backdrop-filter: blur(4px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 20px; padding: 3px 8px;
    font-size: 0.65rem; font-weight: 600;
  }
  .stat-pill .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent2); }
  .stat-pill.warn .dot { background: var(--warn); }

  /* ── Exposing indicator ── */
  .exposing-bar {
    position: absolute; top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    transform-origin: left;
    animation: expose-pulse 2s ease-in-out infinite;
    display: none;
  }
  .exposing-bar.active { display: block; }
  @keyframes expose-pulse { 0%,100%{opacity:0.5} 50%{opacity:1} }

  /* ── No image state ── */
  .no-image {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    min-height: 180px; gap: 10px;
    color: var(--muted); font-size: 0.82rem;
    padding: 24px;
  }
  .no-image svg { opacity: 0.3; }
  .no-image .hint { font-size: 0.68rem; opacity: 0.7; text-align: center; }

  /* ── Histogram ── */
  .histogram-wrap {
    padding: 6px 12px 4px;
    border-top: 1px solid var(--border);
  }
  .histogram-label {
    display: flex; justify-content: space-between;
    font-size: 0.6rem; color: var(--muted);
    margin-bottom: 3px;
  }
  .histogram-bar {
    position: relative; height: 28px;
    background: rgba(255,255,255,0.04);
    border-radius: 4px; overflow: hidden;
  }
  canvas.hist-canvas { position: absolute; inset: 0; width: 100%; height: 100%; }

  /* ── Stats row ── */
  .stats-row {
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 1px; background: var(--border);
    border-top: 1px solid var(--border);
  }
  .stat-cell {
    background: var(--bg);
    padding: 7px 10px;
  }
  .stat-cell .lbl { font-size: 0.58rem; font-weight: 600; letter-spacing: .6px; text-transform: uppercase; color: var(--muted); margin-bottom: 1px; }
  .stat-cell .val { font-size: 0.8rem; font-weight: 600; }
  .stat-cell .val.good { color: var(--success); }
  .stat-cell .val.warn { color: var(--warn); }

  /* ── Image strip ── */
  .strip-wrap {
    padding: 8px 10px 10px;
    border-top: 1px solid var(--border);
    display: flex; flex-direction: column; gap: 5px;
  }
  .strip-label { font-size: 0.6rem; font-weight: 700; letter-spacing: .7px; text-transform: uppercase; color: var(--muted); }
  .strip {
    display: flex; gap: 5px; overflow-x: auto;
    scrollbar-width: none;
  }
  .strip::-webkit-scrollbar { display: none; }
  .strip-thumb {
    flex-shrink: 0;
    width: 64px; height: 48px;
    border-radius: 5px;
    overflow: hidden;
    cursor: pointer;
    border: 1.5px solid transparent;
    transition: border-color 0.15s;
    background: rgba(255,255,255,0.06);
    position: relative;
  }
  .strip-thumb.active { border-color: var(--accent2); }
  .strip-thumb:hover { border-color: rgba(255,255,255,0.3); }
  .strip-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .strip-thumb .strip-filter {
    position: absolute; bottom: 2px; left: 2px; right: 2px;
    text-align: center; font-size: 0.55rem; font-weight: 700;
    background: rgba(0,0,0,0.65); border-radius: 2px; padding: 1px 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

  /* ── Fullscreen modal ── */
  .modal-bg {
    display: none;
    position: fixed; inset: 0; z-index: 9999;
    background: rgba(0,0,0,0.92);
    align-items: center; justify-content: center;
    cursor: zoom-out;
  }
  .modal-bg.open { display: flex; }
  .modal-bg img {
    max-width: 95vw; max-height: 90vh;
    object-fit: contain; border-radius: 8px;
    box-shadow: 0 0 60px rgba(0,0,0,0.8);
  }
  .modal-close {
    position: absolute; top: 16px; right: 16px;
    color: rgba(255,255,255,0.7); font-size: 1.5rem;
    cursor: pointer; background: rgba(0,0,0,0.5);
    border: none; border-radius: 50%; width: 36px; height: 36px;
    display: flex; align-items: center; justify-content: center;
  }
`;

class NinaImagePanelCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._currentIndex = 0;   // 0 = latest
    this._totalFrames  = 0;
    this._loading = false;
    this._imgUrl  = null;
    this._historyMeta = [];   // [{filter, hfr, stars, mean}]
    this._rendered = false;
    this._unsubHassEvent = null;
  }

  setConfig(config) {
    if (!config.host) throw new Error("nina-image-panel-card: 'host' is required");
    this._config = {
      host: config.host,
      port: config.port ?? 1888,
      refresh_on_save: config.refresh_on_save ?? true,
      show_strip: config.show_strip ?? true,
      show_histogram: config.show_histogram ?? true,
      quality: config.quality ?? 85,
      stretch: config.stretch ?? true,
      strip_count: config.strip_count ?? 6,
    };
    this._apiBase = `http://${this._config.host}:${this._config.port}/v2/api`;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;

    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
      this._loadImage(0);
      if (this._config.show_strip) this._loadStrip();
    }

    this._updateOverlay();
    this._updateStatsRow();
    this._updateHeaderBadge();

    // Subscribe to nina_image_save HA event for auto-refresh
    if (first && this._config.refresh_on_save && hass.connection) {
      this._unsubHassEvent = hass.connection.subscribeEvents(
        () => {
          // Jump back to latest on new frame
          this._currentIndex = 0;
          this._loadImage(0, true);
          if (this._config.show_strip) this._loadStrip();
        },
        "nina_image_save"
      ).then(unsub => { this._unsubHassEvent = unsub; });
    }
  }

  disconnectedCallback() {
    if (typeof this._unsubHassEvent === "function") this._unsubHassEvent();
  }

  _s(id, fallback = null) {
    const e = this._hass?.states?.[id];
    return e ? e.state : fallback;
  }
  _f(id, fallback = 0) { return parseFloat(this._s(id)) || fallback; }
  _attr(id, attr, fallback = null) {
    const e = this._hass?.states?.[id];
    return e?.attributes?.[attr] ?? fallback;
  }

  // ── DOM construction ──────────────────────────────────────────────────

  _buildDOM() {
    const cfg = this._config;
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>

        <div class="header">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#5bcfcf" stroke-width="1.5" stroke-linecap="round">
            <rect x="3" y="3" width="18" height="18" rx="3"/>
            <circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
          </svg>
          <div>
            <div class="title" id="hdr-title">Latest Image</div>
            <div class="sub" id="hdr-sub">Waiting for data…</div>
          </div>
          <span class="badge" id="hdr-badge">—</span>
        </div>

        <div class="img-wrap" id="img-wrap">
          <img id="main-img" alt="N.I.N.A. image" />
          <div class="spinner" id="spinner"></div>
          <div class="exposing-bar" id="exposing-bar"></div>
          <div class="overlay" id="overlay"></div>
          <div class="no-image" id="no-image" style="display:none">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
              <rect x="3" y="3" width="18" height="18" rx="3"/>
              <circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>
            </svg>
            <div>No image captured yet</div>
            <div class="hint">Images will appear here as N.I.N.A. saves frames.<br>Ensure "Create Thumbnails" is enabled in the plugin settings.</div>
          </div>
        </div>

        ${cfg.show_histogram ? `
          <div class="histogram-wrap">
            <div class="histogram-label">
              <span>ADU distribution</span>
              <span id="hist-range">—</span>
            </div>
            <div class="histogram-bar">
              <canvas class="hist-canvas" id="hist-canvas"></canvas>
            </div>
          </div>
        ` : ""}

        <div class="stats-row" id="stats-row">
          <div class="stat-cell"><div class="lbl">HFR</div><div class="val" id="st-hfr">—</div></div>
          <div class="stat-cell"><div class="lbl">Stars</div><div class="val" id="st-stars">—</div></div>
          <div class="stat-cell"><div class="lbl">Mean ADU</div><div class="val" id="st-adu">—</div></div>
          <div class="stat-cell"><div class="lbl">Exposure</div><div class="val" id="st-exp">—</div></div>
        </div>

        ${cfg.show_strip ? `
          <div class="strip-wrap">
            <div class="strip-label">Recent frames</div>
            <div class="strip" id="strip"></div>
          </div>
        ` : ""}

        <!-- Fullscreen modal -->
        <div class="modal-bg" id="modal">
          <button class="modal-close" id="modal-close">✕</button>
          <img id="modal-img" alt="Full image" />
        </div>
      </ha-card>
    `;

    // Image click → fullscreen
    this.shadowRoot.getElementById("img-wrap").addEventListener("click", () => {
      if (this._imgUrl) this._openModal(this._imgUrl);
    });
    this.shadowRoot.getElementById("modal").addEventListener("click", e => {
      if (e.target !== this.shadowRoot.getElementById("modal-img")) this._closeModal();
    });
    this.shadowRoot.getElementById("modal-close").addEventListener("click", () => this._closeModal());
  }

  // ── Image loading ─────────────────────────────────────────────────────

  _imageUrl(index, forStrip = false) {
    const cfg = this._config;
    const params = new URLSearchParams({
      index: String(index),
      stream: "true",
      quality: forStrip ? "40" : String(cfg.quality),
      ...(cfg.stretch ? { useAutoStretch: "true" } : {}),
    });
    return `${this._apiBase}/image?${params}`;
  }

  async _loadImage(index, silent = false) {
    if (this._loading && !silent) return;
    this._loading = true;
    this._currentIndex = index;

    const img    = this.shadowRoot?.getElementById("main-img");
    const spinner = this.shadowRoot?.getElementById("spinner");
    const noImg  = this.shadowRoot?.getElementById("no-image");
    if (!img) return;

    if (!silent) {
      img.classList.add("loading");
      spinner?.classList.add("active");
    }

    const url = this._imageUrl(index);
    // Cache-bust so browser doesn't serve stale image on refresh
    const cacheBusted = `${url}&_t=${Date.now()}`;

    try {
      const resp = await fetch(cacheBusted);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();
      if (!blob.type.startsWith("image/")) throw new Error("Not an image");

      const objUrl = URL.createObjectURL(blob);
      if (this._imgUrl) URL.revokeObjectURL(this._imgUrl);
      this._imgUrl = objUrl;

      img.src = objUrl;
      img.onload = () => {
        img.classList.remove("loading");
        spinner?.classList.remove("active");
        noImg && (noImg.style.display = "none");
        img.style.display = "block";
        if (this._config.show_histogram) this._drawHistogram();
        this._updateStripActive();
      };
    } catch (err) {
      img.classList.remove("loading");
      spinner?.classList.remove("active");
      // Show no-image state only if this is the latest frame (not a strip click)
      if (index === 0) {
        img.style.display = "none";
        noImg && (noImg.style.display = "flex");
      }
    } finally {
      this._loading = false;
    }
  }

  // ── Strip loading ─────────────────────────────────────────────────────

  async _loadStrip() {
    const strip = this.shadowRoot?.getElementById("strip");
    if (!strip) return;

    const count = this._config.strip_count;
    // Fetch image history metadata for filter names
    let meta = [];
    try {
      // /image-history, not /image/history, and `count` is a boolean asking
      // for the number of frames rather than a limit. Oldest first, so the
      // newest `count` frames are at the end.
      const resp = await fetch(`${this._apiBase}/image-history?all=true`);
      if (resp.ok) {
        const data = await resp.json();
        meta = (data?.Response ?? []).slice(-count);
      }
    } catch (_) {}

    // Also pull from our frame stats sensor for richer metadata
    const filterTimeline = this._attr("sensor.frame_sparkline_data", "filter_timeline", []) || [];
    const hfrSparkline   = this._attr("sensor.frame_sparkline_data", "hfr_sparkline", [])   || [];

    strip.innerHTML = "";
    for (let i = 0; i < count; i++) {
      const thumb = document.createElement("div");
      thumb.className = `strip-thumb${i === this._currentIndex ? " active" : ""}`;
      thumb.dataset.index = i;

      const img = document.createElement("img");
      img.src = `${this._imageUrl(i, true)}&_t=${Date.now()}`;
      img.alt = `Frame -${i}`;
      img.onerror = () => { thumb.style.opacity = "0.3"; };
      thumb.appendChild(img);

      // Filter label from history metadata or sparkline
      const filterName = meta[i]?.Filter
        ?? filterTimeline[filterTimeline.length - 1 - i]
        ?? "";
      if (filterName) {
        const lbl = document.createElement("div");
        lbl.className = "strip-filter";
        lbl.textContent = filterName;
        thumb.appendChild(lbl);
      }

      thumb.addEventListener("click", () => {
        this._loadImage(parseInt(thumb.dataset.index));
      });
      strip.appendChild(thumb);
    }
  }

  _updateStripActive() {
    const strip = this.shadowRoot?.getElementById("strip");
    if (!strip) return;
    strip.querySelectorAll(".strip-thumb").forEach(t => {
      t.classList.toggle("active", parseInt(t.dataset.index) === this._currentIndex);
    });
  }

  // ── Histogram ─────────────────────────────────────────────────────────

  _drawHistogram() {
    const canvas = this.shadowRoot?.getElementById("hist-canvas");
    if (!canvas) return;

    const min = this._f("sensor.last_frame_min_adu");
    const max = this._f("sensor.last_frame_max_adu");
    const mean = this._f("sensor.last_frame_mean_adu");
    const median = this._f("sensor.last_frame_median_adu") || mean;

    const rangeEl = this.shadowRoot?.getElementById("hist-range");
    if (rangeEl && max > 0) {
      rangeEl.textContent = `${Math.round(min)} – ${Math.round(max)} (mean ${Math.round(mean)})`;
    }

    if (!max || max <= min) return;

    const W = canvas.offsetWidth || 300;
    const H = canvas.offsetHeight || 28;
    const dpr = window.devicePixelRatio || 1;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    // Simplified gaussian histogram from min/max/mean/median
    const range = max - min;
    const bars = 60;
    const sigma = (max - min) * 0.18;
    const vals = Array.from({ length: bars }, (_, i) => {
      const x = min + (i / bars) * range;
      const g = Math.exp(-0.5 * ((x - mean) / sigma) ** 2);
      // Slight skew toward shadows (typical astrophoto histogram)
      const skew = 1 + 0.4 * Math.exp(-0.5 * ((x - min) / (range * 0.15)) ** 2);
      return g * skew;
    });
    const peakVal = Math.max(...vals);

    // Gradient fill
    const grad = ctx.createLinearGradient(0, 0, W, 0);
    grad.addColorStop(0,   "rgba(60,80,180,0.7)");
    grad.addColorStop(0.4, "rgba(100,120,220,0.8)");
    grad.addColorStop(0.7, "rgba(150,170,255,0.6)");
    grad.addColorStop(1,   "rgba(200,210,255,0.4)");

    ctx.beginPath();
    const bw = W / bars;
    ctx.moveTo(0, H);
    for (let i = 0; i < bars; i++) {
      const bh = (vals[i] / peakVal) * H * 0.9;
      ctx.lineTo(i * bw, H - bh);
      ctx.lineTo((i + 1) * bw, H - bh);
    }
    ctx.lineTo(W, H);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Mean line
    const meanX = ((mean - min) / range) * W;
    ctx.beginPath();
    ctx.moveTo(meanX, 0); ctx.lineTo(meanX, H);
    ctx.strokeStyle = "rgba(91,207,207,0.8)";
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Median line
    const medX = ((median - min) / range) * W;
    ctx.beginPath();
    ctx.moveTo(medX, 0); ctx.lineTo(medX, H);
    ctx.strokeStyle = "rgba(255,255,255,0.3)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Saturation zone
    const satX = ((max * 0.95 - min) / range) * W;
    ctx.fillStyle = "rgba(231,111,81,0.15)";
    ctx.fillRect(satX, 0, W - satX, H);
  }

  // ── Overlay pills ─────────────────────────────────────────────────────

  _updateOverlay() {
    const overlay = this.shadowRoot?.getElementById("overlay");
    if (!overlay) return;

    const hfr    = this._f("sensor.last_frame_hfr");
    const stars  = this._s("sensor.last_frame_stars");
    const filter = this._s("sensor.last_frame_filter");
    const rms    = this._s("sensor.last_frame_guide_rms");
    const target = this._s("sensor.last_frame_target");

    const pills = [];
    if (filter && filter !== "null") {
      pills.push(`<span class="stat-pill"><span class="dot"></span>${filter}</span>`);
    }
    if (hfr > 0) {
      const cls = hfr > 3 ? "warn" : "";
      pills.push(`<span class="stat-pill ${cls}"><span class="dot"></span>HFR ${hfr.toFixed(2)}"</span>`);
    }
    if (stars && stars !== "null" && parseInt(stars) > 0) {
      pills.push(`<span class="stat-pill"><span class="dot"></span>${stars} ★</span>`);
    }
    if (rms && rms !== "null" && rms !== "") {
      pills.push(`<span class="stat-pill"><span class="dot"></span>RMS ${rms}</span>`);
    }

    const targetHtml = target && target !== "null"
      ? `<span style="font-size:0.65rem;color:rgba(255,255,255,0.5);white-space:nowrap;overflow:hidden;max-width:120px;text-overflow:ellipsis">${target}</span>`
      : "";

    overlay.innerHTML = `<div class="overlay-left">${pills.join("")}</div>${targetHtml}`;
  }

  _updateStatsRow() {
    const set = (id, val) => {
      const el = this.shadowRoot?.getElementById(id);
      if (el) el.textContent = val;
    };
    const hfr  = this._f("sensor.last_frame_hfr");
    const stars = this._s("sensor.last_frame_stars", "—");
    const adu   = this._f("sensor.last_frame_mean_adu");
    const exp   = this._f("sensor.last_frame_exposure");

    set("st-hfr",   hfr  > 0 ? `${hfr.toFixed(2)} px`   : "—");
    set("st-stars", stars !== "null" ? stars : "—");
    set("st-adu",   adu  > 0 ? Math.round(adu).toString() : "—");
    set("st-exp",   exp  > 0 ? `${exp.toFixed(0)} s`      : "—");

    // Colour HFR
    const hfrEl = this.shadowRoot?.getElementById("st-hfr");
    if (hfrEl && hfr > 0) {
      hfrEl.className = `val ${hfr < 2 ? "good" : hfr > 3.5 ? "warn" : ""}`;
    }
  }

  _updateHeaderBadge() {
    const badge  = this.shadowRoot?.getElementById("hdr-badge");
    const sub    = this.shadowRoot?.getElementById("hdr-sub");
    const title  = this.shadowRoot?.getElementById("hdr-title");
    const expBar = this.shadowRoot?.getElementById("exposing-bar");
    if (!badge) return;

    const count   = this._s("sensor.frame_session_count", "0");
    const intTime = this._f("sensor.session_integration_time");
    const exposing = this._hass?.states?.["binary_sensor.camera_exposing"]?.state === "on";
    const connected = this._hass?.states?.["binary_sensor.camera_connected"]?.state === "on";
    const target = this._s("sensor.last_frame_target", "");
    const filter = this._s("sensor.last_frame_filter", "");
    const index  = this._currentIndex;

    if (!connected) {
      badge.textContent = "Disconnected";
      badge.className   = "badge warn";
    } else if (exposing) {
      badge.textContent = "Exposing…";
      badge.className   = "badge";
    } else {
      badge.textContent = `${count} frames`;
      badge.className   = "badge";
    }

    expBar?.classList.toggle("active", exposing);

    if (title) {
      title.textContent = index === 0 ? "Latest Image" : `Frame -${index}`;
    }
    if (sub) {
      const parts = [];
      if (target && target !== "null") parts.push(target);
      if (filter && filter !== "null") parts.push(filter);
      if (intTime > 0) parts.push(`${intTime.toFixed(1)} min`);
      sub.textContent = parts.join(" · ") || "Waiting for first frame…";
    }
  }

  // ── Modal ─────────────────────────────────────────────────────────────

  _openModal(url) {
    const modal    = this.shadowRoot?.getElementById("modal");
    const modalImg = this.shadowRoot?.getElementById("modal-img");
    if (!modal || !modalImg || !url) return;
    // Load full-quality version for modal
    const fullUrl = this._imageUrl(this._currentIndex);
    modalImg.src = `${fullUrl}&_t=${Date.now()}`;
    modal.classList.add("open");
  }

  _closeModal() {
    this.shadowRoot?.getElementById("modal")?.classList.remove("open");
  }

  getCardSize() { return 7; }

  static getStubConfig() {
    return { host: "192.168.1.100", port: 1888 };
  }
}

customElements.define("nina-image-panel-card", NinaImagePanelCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-image-panel-card",
  name: "N.I.N.A. Image Panel",
  description: "Live last-frame viewer with stats overlay, histogram, and frame strip.",
  preview: false,
  documentationURL: "https://github.com/christian-photo/ninaAPI",
});

console.info(
  `%c NINA-IMAGE-PANEL-CARD %c v${VERSION} `,
  "background:#12121e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #7b8de8",
  "background:#7b8de8;color:#12121e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

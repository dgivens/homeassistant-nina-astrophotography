/**
 * N.I.N.A. Image Panel Card
 *
 * Displays the last captured image from N.I.N.A., with a live stats overlay,
 * session image strip, and the frame's ADU range.
 *
 * Images never come from N.I.N.A. directly: its Advanced API is plain
 * HTTP-only, and a dashboard served over HTTPS would have every such fetch
 * blocked as mixed content. Instead the integration proxies them, same
 * origin as Home Assistant itself:
 *
 *   GET /api/nina_astrophotography/image/{entity_id}/{index}?date=…   → one
 *     frame, JPEG, by history index (0 = newest of any type) and save time
 *
 * Every image URL is signed just before use via the `auth/sign_path`
 * websocket command, so it can be set directly as `<img src>` — including
 * the thumbnail strip, which cannot carry an Authorization header.
 *
 * Everything describing a frame comes from the mean-ADU sensor's
 * `recent_frames` attribute — the newest frames of any type, already bounded
 * and ordered, each with its own readings — so the overlay, the stats row and
 * the ADU range describe the frame on screen, whichever it is. Only the
 * header's light count, integration time and exposing state are the session's.
 *
 * The ADU range is those statistics, not a histogram: a histogram needs the
 * frame's pixels. Every `/image` render is stretched, `autoPrepare=false`
 * included, so a preview's pixels describe the picture, not the frame. Only
 * `raw_fits` returns the frame's own values, at the whole frame's size again
 * (#178).
 *
 * Each N.I.N.A. render is a full FITS load and stretch on the imaging PC, so
 * the panel asks for as few as it can: one main load at a time, the newest
 * frame only when `recent_frames` gains one, a thumbnail only for a frame the
 * strip has not shown before, and the preview no wider than it is drawn.
 *
 * Card config — one rig needs none: the card finds its own sensors in the
 * registry.
 *   type: custom:nina-image-panel-card
 *   device_id: abc123       # which rig, for two or more; any one of its devices
 *   prefix: n_i_n_a         # fallback only, for the entities that cannot resolve
 *   refresh_on_save: true   # load each frame as N.I.N.A. saves it (default true)
 *   show_strip: true        # show recent-frames strip at bottom (default true)
 *   show_histogram: true    # show the frame's ADU range (default true)
 *   quality: 85             # JPEG quality 1-100 (default 85)
 *   stretch: true           # use N.I.N.A.'s auto-stretch (default true)
 *   strip_count: 6          # number of thumbnails in the recent strip (default 6)
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import { LinkView, RigEntities } from "./nina-entity-resolver.js";
import { quantityIn, shown } from "./nina-units.js";

const VERSION = "2.2.0";

const DEFAULT_QUALITY = 85;
const DEFAULT_STRIP_COUNT = 6;

// Signed just before use: a fresh signature per call busts the browser's cache
// across reloads of the same index.
const SIGNED_URL_TTL_SECONDS = 30;

// A strip tile's width in CSS pixels, as `.strip-thumb` draws it.
const THUMB_WIDTH = 64;

// Device pixels across for a preview the card could not measure.
const FALLBACK_PREVIEW_WIDTH = 1600;

// N.I.N.A. holds frames as 16-bit unsigned, so no statistic exceeds this; a
// camera whose driver does not scale to 16 bits saturates lower.
const ADU_FULL_SCALE = 65535;

// The ADU bar is logarithmic: a light's background sits in the hundreds to a
// few thousand, a flat's in the tens of thousands.
const ADU_GRIDLINES = [[100, "100"], [1000, "1k"], [10000, "10k"]];

// An absent field is undefined; the integration publishes no reading as null.
function finite(value) {
  return Number.isFinite(value) ? value : null;
}

// The type a thumbnail is tagged with: a light is the ordinary case, and a
// frame with no type is one the integration did not classify.
function tagFor(frame) {
  const type = frame?.image_type;
  return type && type !== "LIGHT" ? type : null;
}

// A browser draws an image with no src, or a failed one, as its alt text and a
// broken-image icon. Hidden, it is not announced either. Call before `src`.
function hideUntilLoaded(img) {
  img.style.visibility = "hidden";
  img.onload = () => { img.style.visibility = ""; };
  // A later `src` that fails would otherwise swap the frame for the broken-image icon.
  img.onerror = () => { img.style.visibility = "hidden"; };
}

const STYLE = `
  :host {
    /* A custom element is inline by default, and a ResizeObserver watching an
       inline box does not report the card getting wider — which is what
       redraws the ADU range. */
    display: block;
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
  /* Readings N.I.N.A. has not confirmed since it stopped answering */
  ha-card.stale .overlay, ha-card.stale .stats-row { opacity: 0.5; }
  .header .badge.warn { background: rgba(244,162,97,0.15); color: var(--warn); border-color: rgba(244,162,97,0.3); }

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

  .no-image {
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    min-height: 180px; gap: 10px;
    color: var(--muted); font-size: 0.82rem;
    padding: 24px;
  }
  .no-image svg { opacity: 0.3; }
  .no-image .hint { font-size: 0.68rem; opacity: 0.7; text-align: center; }

  .adu-wrap {
    padding: 6px 12px 4px;
    border-top: 1px solid var(--border);
  }
  .adu-label {
    display: flex; justify-content: space-between; gap: 8px;
    font-size: 0.6rem; color: var(--muted);
    margin-bottom: 3px;
  }
  .adu-label > span:first-child, .adu-label span span { white-space: nowrap; }
  #adu-range {
    display: flex; flex-wrap: wrap; justify-content: flex-end;
    column-gap: 8px;
  }
  .adu-label .median { color: var(--text); }
  .adu-label .mean { color: var(--accent2); }
  .adu-bar {
    position: relative; height: 28px;
    background: rgba(255,255,255,0.04);
    border-radius: 4px; overflow: hidden;
  }
  canvas.adu-canvas { position: absolute; inset: 0; width: 100%; height: 100%; }

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
  /* Not the accent, or a focused tile reads as a second selected frame; and
     inset, since the scrolling strip clips anything drawn outside a tile. */
  .strip-thumb:focus-visible { outline: 2px solid var(--text); outline-offset: -2px; }
  .strip-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .strip-thumb .strip-filter {
    position: absolute; bottom: 2px; left: 2px; right: 2px;
    text-align: center; font-size: 0.55rem; font-weight: 700;
    background: rgba(0,0,0,0.65); border-radius: 2px; padding: 1px 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .strip-thumb .strip-type {
    position: absolute; top: 2px; left: 2px;
    font-size: 0.5rem; font-weight: 700; letter-spacing: .3px;
    color: var(--warn);
    background: rgba(0,0,0,0.65); border-radius: 2px; padding: 0 2px;
  }

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
    this._shown = null;   // the `recent_frames` entry on screen, once one loads
    this._newest = undefined;
    this._loading = false;
    this._queued = null;
    this._hasImage = false;
    this._rendered = false;
    this._stripKey = null;
    this._tiles = new Map();  // strip tiles by frame date
    this._view = new LinkView();
  }

  connectedCallback() {
    // The ADU range is redrawn only with a frame, so a resize would otherwise
    // stretch its gridlines and labels until the next one.
    if (typeof ResizeObserver === "undefined" || this._observer) return;
    this._observer = new ResizeObserver(() => {
      if (this._config?.show_histogram) this._drawAduRange();
    });
    this._observer.observe(this);
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    this._observer = undefined;
  }

  setConfig(config) {
    this._config = {
      refresh_on_save: config.refresh_on_save ?? true,
      show_strip: config.show_strip ?? true,
      show_histogram: config.show_histogram ?? true,
      quality: config.quality ?? DEFAULT_QUALITY,
      stretch: config.stretch ?? true,
      strip_count: config.strip_count ?? DEFAULT_STRIP_COUNT,
      prefix: config.prefix || DEFAULT_PREFIX,
      device_id: config.device_id,
    };
    this._rig = new RigEntities(this._config.prefix, this._config.device_id);
    this._view.reset();
  }

  set hass(hass) {
    this._live = hass;

    this._rig.refresh(hass);

    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
    }

    const link = this._view.read(hass, this._rig);
    // While N.I.N.A. is not answering, the readings are its last ones.
    this._hass = link.hass;
    this._link = link;
    // Nothing to show at all: the link was lost before this card saw it up.
    this._unreachable = link.lost && !link.stale;
    this.shadowRoot.querySelector("ha-card")?.classList.toggle("stale", link.stale);
    this._update();
  }

  _update() {
    // The newest frame is loaded on the first render, whenever a config or
    // registry change points the card at another entity (which may be another
    // rig's), and with `refresh_on_save` whenever the rig saves another. Read
    // off the attribute rather than `nina_image_save`, so the frame arrives
    // with its readings, and from this rig alone.
    const newest = this._recentFrames()[0];
    const imageEntity = this._entityId();
    if (imageEntity !== this._imageEntity) {
      this._imageEntity = imageEntity;
      this._newest = newest?.date;
      this._load(newest);
    } else if (newest && newest.date !== this._newest) {
      // An emptied list is not a save, so the same newest coming back loads
      // nothing.
      this._newest = newest.date;
      if (this._config.refresh_on_save || !this._hasImage) this._load(newest);
    }

    // The ADU range too: before a frame loads, it describes the newest.
    const stripKey = JSON.stringify(this._recentFrames());
    if (stripKey !== this._stripKey) {
      this._stripKey = stripKey;
      if (this._config.show_strip) this._loadStrip();
      if (this._config.show_histogram) this._drawAduRange();
    }

    this._updateOverlay();
    this._updateStatsRow();
    this._updateHeaderBadge();
  }

  _s(id, fallback = null) {
    const e = this._hass?.states?.[id];
    return e ? e.state : fallback;
  }
  // A duration in `unit`, whichever unit the sensor is shown in; 0 for none.
  _duration(id, unit) { return quantityIn(this._hass, id, unit) || 0; }

  // Falls back to a prefixed `slug` when nothing resolves. The camera's
  // exposing sensor is keyed `camera_is_exposing`.
  _eid(domain, key, slug = key) {
    return this._rig.id(domain, key, slug);
  }

  // The entity the proxy resolves a rig by. It must be a hub entity, which
  // exists from setup: an equipment entity such as `camera_state` is absent
  // until its device is observed, and every request would 404. This one also
  // carries `recent_frames`.
  _entityId() { return this._eid("sensor", "last_image_mean_adu"); }

  // The frame the readings describe: the one on screen, or before any has
  // loaded the newest, which is what is loading.
  _frame() { return this._shown ?? this._recentFrames()[0] ?? {}; }

  // Where the frame on screen sits in `recent_frames`: 0 the newest, -1 once
  // newer frames have pushed it off the end.
  _index() {
    const date = this._frame().date;
    const frames = this._recentFrames();
    // An empty list says nothing of where the frame sits.
    if (!date || frames.length === 0) return 0;
    return frames.findIndex((frame) => frame.date === date);
  }

  _attr(id, attr, fallback = null) {
    const e = this._hass?.states?.[id];
    return e?.attributes?.[attr] ?? fallback;
  }

  // Newest first and bounded (session.py's `recent_frames`).
  _recentFrames() { return this._attr(this._entityId(), "recent_frames", []); }

  // The unsigned path: a stable, cache-key-free description of one frame. The
  // index is where the frame sits now; its `date` lets the proxy find it past
  // any frame the rig saved since, and refuse rather than serve another.
  _imagePath(frame, { thumbnail = false, width = null } = {}) {
    const cfg = this._config;
    const index = this._recentFrames().findIndex((f) => f.date === frame.date);
    const params = new URLSearchParams({
      quality: thumbnail ? "40" : String(cfg.quality),
      ...(cfg.stretch ? { autoPrepare: "true" } : {}),
      date: frame.date,
      ...(width ? { width: String(width) } : {}),
      ...(thumbnail ? { thumbnail: "true" } : {}),
    });
    return `/api/nina_astrophotography/image/${this._entityId()}/${Math.max(index, 0)}?${params}`;
  }

  // Device pixels across `css` CSS pixels, so the rig sends no more of a
  // frame than is drawn; `null` before layout.
  _devicePixels(css) {
    return css ? Math.ceil(css * (window.devicePixelRatio || 1)) : null;
  }

  // The preview's width in device pixels. Lovelace hands a card `hass` before
  // attaching it, in the same task, so an unmeasured card waits one task; one
  // still unmeasured — off-DOM, or in a hidden view — gets a cap, not the
  // full frame.
  async _previewWidth() {
    const wrap = () => this.shadowRoot.getElementById("img-wrap")?.clientWidth;
    if (!wrap()) await new Promise((resolve) => setTimeout(resolve));
    return this._devicePixels(wrap()) ?? FALLBACK_PREVIEW_WIDTH;
  }

  // A short-lived URL `<img src>` can load without an Authorization header.
  async _signedUrl(path) {
    const { path: signed } = await this._live.callWS({
      type: "auth/sign_path",
      path,
      expires: SIGNED_URL_TTL_SECONDS,
    });
    return signed;
  }

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
            <div class="hint">Images will appear here as N.I.N.A. saves frames.</div>
          </div>
        </div>

        ${cfg.show_histogram ? `
          <div class="adu-wrap">
            <div class="adu-label">
              <span>ADU range</span>
              <span id="adu-range">—</span>
            </div>
            <div class="adu-bar">
              <canvas class="adu-canvas" id="adu-canvas"></canvas>
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

        <div class="modal-bg" id="modal">
          <button class="modal-close" id="modal-close">✕</button>
          <img id="modal-img" alt="Full image" />
        </div>
      </ha-card>
    `;

    hideUntilLoaded(this.shadowRoot.getElementById("main-img"));

    this.shadowRoot.getElementById("img-wrap").addEventListener("click", () => {
      if (this._hasImage) this._openModal().catch(() => {});
    });
    this.shadowRoot.getElementById("modal").addEventListener("click", e => {
      if (e.target !== this.shadowRoot.getElementById("modal-img")) this._closeModal();
    });
    this.shadowRoot.getElementById("modal-close").addEventListener("click", () => this._closeModal());
  }

  // One main load at a time: a frame asked for meanwhile replaces any still
  // waiting, so a burst of saves costs N.I.N.A. two renders, not one each.
  // `picked` is a strip click, which shows the spinner at once, even while
  // it waits, and failing leaves the frame on screen.
  _load(frame, picked = false) {
    if (picked) {
      this.shadowRoot?.getElementById("main-img")?.classList.add("loading");
      this.shadowRoot?.getElementById("spinner")?.classList.add("active");
    }
    if (this._loading) {
      this._queued = { frame, picked };
      return;
    }
    this._loading = true;
    this._loadImage(frame, picked).catch(() => {}).finally(() => {
      this._loading = false;
      const next = this._queued;
      this._queued = null;
      if (next) this._load(next.frame, next.picked);
    });
  }

  async _loadImage(frame, picked) {
    const img    = this.shadowRoot?.getElementById("main-img");
    const spinner = this.shadowRoot?.getElementById("spinner");
    const noImg  = this.shadowRoot?.getElementById("no-image");
    if (!img) return;
    // A picked frame still waiting keeps its spinner.
    const settle = () => {
      if (this._queued?.picked) return;
      img.classList.remove("loading");
      spinner?.classList.remove("active");
    };

    try {
      if (!frame) throw new Error("no frame to load");
      const width = await this._previewWidth();
      const url = await this._signedUrl(this._imagePath(frame, { width }));
      await new Promise((resolve, reject) => {
        const probe = new Image();
        probe.onload = resolve;
        probe.onerror = () => reject(new Error("image failed to load"));
        probe.src = url;
      });
      img.src = url;
      // Only now: a failed or pending load leaves the previous frame on screen,
      // and everything describing it must stay on it too.
      this._shown = frame;
      this._hasImage = true;
      settle();
      noImg && (noImg.style.display = "none");
      img.style.display = "block";
    } catch (err) {
      settle();
      // A strip click leaves the frame shown; the newest failing clears it.
      if (!picked) {
        this._shown = null;
        this._hasImage = false;
        img.style.display = "none";
        noImg && (noImg.style.display = "flex");
      }
    }
    if (this._config.show_histogram) this._drawAduRange();
    this._updateStripActive();
    this._updateOverlay();
    this._updateStatsRow();
    this._updateHeaderBadge();
  }

  // Tiles are kept per frame: a new frame costs one thumbnail, and every
  // older tile only moves along.
  _loadStrip() {
    const strip = this.shadowRoot?.getElementById("strip");
    if (!strip) return;

    const frames = this._recentFrames().slice(0, this._config.strip_count);
    // An emptied list keeps its tiles, so the same frames returning cost no
    // thumbnails.
    if (frames.length === 0) {
      strip.innerHTML = "";
      return;
    }
    const kept = this._tiles;
    this._tiles = new Map();
    strip.innerHTML = "";
    frames.forEach((frame, i) => {
      const tile = kept.get(frame.date) ?? this._tile(frame);
      tile.setAttribute("aria-label", [
        i === 0 ? "Latest image" : `Frame -${i}`, tagFor(frame), frame.filter,
      ].filter(Boolean).join(", "));
      this._tiles.set(frame.date, tile);
      strip.appendChild(tile);
    });
    this._updateStripActive();
  }

  _tile(frame) {
    const thumb = document.createElement("div");
    thumb.className = "strip-thumb";
    thumb.dataset.date = frame.date;
    // A tile is a button in all but tag: a `div` keeps the thumbnail's
    // layout free of a button's default styling.
    thumb.setAttribute("role", "button");
    thumb.setAttribute("tabindex", "0");

    // Decorative: the tile's `aria-label` names it, and still does once a
    // failed thumbnail leaves nothing on it but the tags.
    const img = document.createElement("img");
    img.alt = "";
    const dim = () => { thumb.style.opacity = "0.3"; };
    hideUntilLoaded(img);
    img.onerror = dim;
    thumb.appendChild(img);
    const width = this._devicePixels(THUMB_WIDTH);
    this._signedUrl(this._imagePath(frame, { thumbnail: true, width }))
      .then((url) => { img.src = url; })
      .catch(dim);

    // Only a calibration frame is tagged: a light is the ordinary case.
    const type = tagFor(frame);
    if (type) {
      const tag = document.createElement("div");
      tag.className = "strip-type";
      tag.textContent = type;
      thumb.appendChild(tag);
    }

    if (frame.filter) {
      const lbl = document.createElement("div");
      lbl.className = "strip-filter";
      lbl.textContent = frame.filter;
      thumb.appendChild(lbl);
    }

    const pick = () => this._load(frame, true);
    thumb.addEventListener("click", pick);
    thumb.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();   // Space would scroll the page
      pick();
    });
    return thumb;
  }

  _updateStripActive() {
    const date = this._frame().date;
    for (const [tileDate, tile] of this._tiles) {
      const current = tileDate === date;
      tile.classList.toggle("active", current);
      if (current) tile.setAttribute("aria-current", "true");
      else tile.removeAttribute("aria-current");
    }
  }

  _drawAduRange() {
    const canvas = this.shadowRoot?.getElementById("adu-canvas");
    if (!canvas) return;

    // All of it from the frame on screen, out of `recent_frames`. The mean-ADU
    // sensor is no fallback: it holds the newest light's, and the frame on
    // screen may be a flat.
    const frame = this._frame();
    const min = finite(frame.min);
    const median = finite(frame.median);
    const mean = finite(frame.mean);
    const max = finite(frame.max);

    // Sizing the canvas wipes it, so a frame with no statistics leaves it empty.
    const W = canvas.offsetWidth || 300;
    const H = canvas.offsetHeight || 28;
    const dpr = window.devicePixelRatio || 1;
    canvas.width  = W * dpr;
    canvas.height = H * dpr;

    const label = [["min", min], ["median", median], ["mean", mean], ["max", max]]
      .filter(([, value]) => value !== null)
      .map(([name, value]) => `<span class="${name}">${name} ${Math.round(value)}</span>`)
      .join("");
    const rangeEl = this.shadowRoot?.getElementById("adu-range");
    if (rangeEl) rangeEl.innerHTML = label || "—";
    if (!label) return;

    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const x = (adu) => W * Math.log1p(Math.max(adu, 0)) / Math.log1p(ADU_FULL_SCALE);

    ctx.font = "8px sans-serif";
    ctx.textBaseline = "top";
    for (const [adu, text] of ADU_GRIDLINES) {
      ctx.fillStyle = "rgba(255,255,255,0.08)";
      ctx.fillRect(x(adu), 0, 1, H);
      ctx.fillStyle = "rgba(255,255,255,0.3)";
      ctx.fillText(text, x(adu) + 2, 1);
    }

    // A whisker, not a box: min and max are single pixels — a cold one and a
    // star core — while nearly every pixel sits near the median.
    const mid = (H + 9) / 2;
    if (min !== null && max !== null) {
      ctx.beginPath();
      ctx.moveTo(x(min), mid); ctx.lineTo(x(max), mid);
      ctx.moveTo(x(min), mid - 3); ctx.lineTo(x(min), mid + 3);
      ctx.moveTo(x(max), mid - 3); ctx.lineTo(x(max), mid + 3);
      ctx.strokeStyle = "rgba(123,141,232,0.8)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    const tick = (adu, style, width) => {
      if (adu === null) return;
      ctx.beginPath();
      ctx.moveTo(x(adu), 9); ctx.lineTo(x(adu), H - 2);
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      ctx.stroke();
    };
    tick(median, "rgba(255,255,255,0.9)", 3);
    tick(mean, "rgba(91,207,207,0.95)", 1.5);
  }

  _updateOverlay() {
    const overlay = this.shadowRoot?.getElementById("overlay");
    if (!overlay) return;

    const frame = this._frame();
    const hfr   = finite(frame.hfr);
    const stars = finite(frame.stars);
    const rms   = finite(frame.rms);

    const pills = [];
    if (frame.filter) {
      pills.push(`<span class="stat-pill"><span class="dot"></span>${frame.filter}</span>`);
    }
    if (hfr > 0) {
      const cls = hfr > 3 ? "warn" : "";
      pills.push(`<span class="stat-pill ${cls}"><span class="dot"></span>HFR ${hfr.toFixed(2)} px</span>`);
    }
    if (stars > 0) {
      pills.push(`<span class="stat-pill"><span class="dot"></span>${stars} ★</span>`);
    }
    if (rms !== null) {
      pills.push(`<span class="stat-pill"><span class="dot"></span>RMS ${rms.toFixed(2)}″</span>`);
    }

    const targetHtml = frame.target
      ? `<span class="target" style="font-size:0.65rem;color:rgba(255,255,255,0.5);white-space:nowrap;overflow:hidden;max-width:120px;text-overflow:ellipsis">${frame.target}</span>`
      : "";

    overlay.innerHTML = `<div class="overlay-left">${pills.join("")}</div>${targetHtml}`;
  }

  _updateStatsRow() {
    const set = (id, val) => {
      const el = this.shadowRoot?.getElementById(id);
      if (el) el.textContent = val;
    };
    const frame = this._frame();
    const hfr   = finite(frame.hfr);
    const stars = finite(frame.stars);
    const adu   = finite(frame.mean);
    // Seconds whatever the instance shows durations in: an attribute is not
    // converted. A flat can be a few hundredths of one.
    const exp   = finite(frame.exposure);

    set("st-hfr",   hfr > 0 ? `${hfr.toFixed(2)} px` : "—");
    set("st-stars", stars !== null ? String(stars) : "—");
    set("st-adu",   adu !== null ? Math.round(adu).toString() : "—");
    set("st-exp",   exp > 0 ? `${Number(exp.toPrecision(3))} s` : "—");

    const hfrEl = this.shadowRoot?.getElementById("st-hfr");
    if (hfrEl) {
      hfrEl.className = `val ${hfr === null || hfr <= 0 ? "" : hfr < 2 ? "good" : hfr > 3.5 ? "warn" : ""}`;
    }
  }

  _updateHeaderBadge() {
    const badge  = this.shadowRoot?.getElementById("hdr-badge");
    const sub    = this.shadowRoot?.getElementById("hdr-sub");
    const title  = this.shadowRoot?.getElementById("hdr-title");
    const expBar = this.shadowRoot?.getElementById("exposing-bar");
    if (!badge) return;

    // Lights, not frames: the count sensor's state includes the calibration
    // frames, and the integration time beside it is lights only.
    const count   = shown(this._attr(this._eid("sensor", "session_image_count"), "light_count"));
    const intTime = this._duration(this._eid("sensor", "session_integration_time"), "h");
    const exposing = this._s(
      this._eid("binary_sensor", "camera_is_exposing", "camera_exposing")) === "on";
    // A disconnected camera makes its entities unavailable rather than
    // publishing an off state.
    const cameraState = this._s(this._eid("sensor", "camera_state"));
    const connected = cameraState !== null && cameraState !== "unavailable";
    const { target, filter } = this._frame();
    const index = this._index();

    // Before the camera: a lost link makes it unavailable too.
    if (this._link.stale) {
      const since = this._link.since
        ? ` since ${new Date(this._link.since).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
        : "";
      badge.textContent = `No answer${since}`;
      badge.className   = "badge warn";
    } else if (this._unreachable) {
      badge.textContent = "N.I.N.A. unreachable";
      badge.className   = "badge warn";
    } else if (!connected) {
      badge.textContent = "Disconnected";
      badge.className   = "badge warn";
    } else if (exposing) {
      badge.textContent = "Exposing…";
      badge.className   = "badge";
    } else {
      badge.textContent = `${count} lights`;
      badge.className   = "badge";
    }

    // Held readings are not current: the exposure may have ended since.
    expBar?.classList.toggle("active", exposing && !this._link.stale);

    if (title) {
      title.textContent = index === 0 ? "Latest Image"
        : index > 0 ? `Frame -${index}` : "Earlier frame";
    }
    if (sub) {
      const parts = [];
      if (target) parts.push(target);
      if (filter) parts.push(filter);
      // Every light this session, not the target's or the filter's beside it.
      if (intTime > 0) parts.push(`session ${intTime.toFixed(1)} h`);
      sub.textContent = parts.join(" · ") || "No lights yet this session";
    }
  }

  async _openModal() {
    const modal    = this.shadowRoot?.getElementById("modal");
    const modalImg = this.shadowRoot?.getElementById("modal-img");
    if (!modal || !modalImg || !this._shown) return;
    // Full size and quality for the modal, signed fresh for this viewing.
    hideUntilLoaded(modalImg);
    modalImg.src = await this._signedUrl(this._imagePath(this._shown));
    modal.classList.add("open");
  }

  _closeModal() {
    this.shadowRoot?.getElementById("modal")?.classList.remove("open");
  }

  getCardSize() { return 7; }

  static getConfigForm() {
    const toggle = { default: true, selector: { boolean: {} } };
    return configForm([
      {
        name: "refresh_on_save",
        label: "Refresh on save",
        helper: "Load each frame as N.I.N.A. saves it. Off keeps the frame shown until "
          + "you pick one from the strip.",
        ...toggle,
      },
      {
        name: "stretch",
        label: "Auto-stretch",
        helper: "Let N.I.N.A. prepare the preview with its own image settings. Off shows "
          + "the linear frame, which looks almost black.",
        ...toggle,
      },
      {
        name: "show_histogram",
        label: "Show ADU range",
        helper: "Min, median, mean and max ADU of the frame on screen, on a log scale.",
        ...toggle,
      },
      { name: "show_strip", label: "Show recent frames", ...toggle },
      {
        name: "strip_count",
        label: "Number of recent frames",
        helper: "Up to 20, the frames the integration keeps.",
        default: DEFAULT_STRIP_COUNT,
        selector: { number: { min: 1, max: 20, mode: "box" } },
      },
      {
        name: "quality",
        label: "JPEG quality",
        helper: "The main frame only. Thumbnails are N.I.N.A.'s own where it keeps "
          + "them, and quality 40 where it does not.",
        default: DEFAULT_QUALITY,
        selector: { number: { min: 1, max: 100, mode: "box" } },
      },
    ]);
  }

  static getStubConfig() {
    return {};
  }
}

// Guarded: a stale 1.4.5 `/local/` resource defining the same tag would
// otherwise throw and abort the rest of this module.
if (!customElements.get("nina-image-panel-card")) {
  customElements.define("nina-image-panel-card", NinaImagePanelCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-image-panel-card",
  name: "N.I.N.A. Image Panel",
  description: "Live last-frame viewer with stats overlay, ADU range, and frame strip.",
  preview: false,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-IMAGE-PANEL-CARD %c v${VERSION} `,
  "background:#12121e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #7b8de8",
  "background:#7b8de8;color:#12121e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

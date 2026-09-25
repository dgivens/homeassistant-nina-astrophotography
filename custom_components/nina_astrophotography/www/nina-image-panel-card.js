/**
 * N.I.N.A. Image Panel Card
 *
 * Displays the last captured image from N.I.N.A., with a live stats overlay,
 * session image strip, and histogram visualisation.
 *
 * Images never come from N.I.N.A. directly: its Advanced API is plain
 * HTTP-only, and a dashboard served over HTTPS would have every such fetch
 * blocked as mixed content. Instead the integration proxies them, same
 * origin as Home Assistant itself:
 *
 *   GET /api/nina_astrophotography/image/{entity_id}/{index}   → one frame,
 *     JPEG, by history index (0 = newest of any type)
 *
 * Every image URL is signed just before use via the `auth/sign_path`
 * websocket command, so it can be set directly as `<img src>` — including
 * the thumbnail strip, which cannot carry an Authorization header.
 *
 * Reads HA sensors for the overlay and the strip/histogram:
 *   The newest LIGHT frame's HFR, star count, mean ADU, filter, exposure,
 *   guide RMS and target; the session frame count and integration time;
 *   whether the camera is exposing; and the mean-ADU sensor's `recent_frames`
 *   attribute — the newest frames of any type, already bounded and ordered —
 *   for the strip's labels and the histogram's range.
 *
 * Card config — one rig needs none: the card finds its own sensors in the
 * registry.
 *   type: custom:nina-image-panel-card
 *   device_id: abc123       # which rig, for two or more; any one of its devices
 *   prefix: n_i_n_a         # fallback only, for the entities that cannot resolve
 *   refresh_on_save: true   # auto-refresh when IMAGE-SAVE fires via HA event (default true)
 *   show_strip: true        # show recent-frames strip at bottom (default true)
 *   show_histogram: true    # show ADU histogram bar (default true)
 *   quality: 85             # JPEG quality 1-100 (default 85)
 *   stretch: true           # use N.I.N.A.'s auto-stretch (default true)
 *   strip_count: 6          # number of thumbnails in the recent strip (default 6)
 */

import { resolveEntities } from "./nina-entity-resolver.js";

const VERSION = "3.0.0";

// Signed just before use, not cached: a fresh signature each call is what
// naturally busts the browser's cache across reloads of the same index.
const SIGNED_URL_TTL_SECONDS = 30;

// Home Assistant slugifies an instance name the same way for the entity ids
// and the event payload: `N.I.N.A.` becomes `n_i_n_a`.
function slug(name) {
  return String(name).toLowerCase().replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

// Home Assistant publishes "unknown" for no reading and "unavailable" for a
// device that is not connected. Neither is a number to print.
function missing(value) {
  return value === null || value === undefined || value === ""
    || value === "unknown" || value === "unavailable";
}

// A reading to print, dashed when there is none.
function shown(value) {
  return missing(value) ? "—" : value;
}

// A reading that is left out rather than dashed: a pill or a header part that
// has nothing to say is not drawn at all.
function known(value) {
  return missing(value) ? null : value;
}

// .NET writes NaN as the string "NaN", and an absent field is undefined.
function finite(value) {
  const number = typeof value === "number" ? value : parseFloat(value);
  return Number.isFinite(number) ? number : null;
}

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

// The fallback path, not the primary one: entity ids normally come from the
// registry (`_eid`), and the prefix is what an id is built from when a
// particular entity cannot be resolved. It is the instance name from the config
// flow, slugified — `N.I.N.A.` by default. Set `prefix:` for a renamed
// instance, or for the second rig.
//
// Repeated in each card rather than imported: it is one literal, and `www/` is
// served whole from the integration (`frontend.py`), so a card that needs real
// shared code imports it instead — see `nina-entity-resolver.js`.
const DEFAULT_PREFIX = "n_i_n_a";

class NinaImagePanelCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._currentIndex = 0;   // 0 = latest
    this._totalFrames  = 0;
    this._loading = false;
    this._historyMeta = [];   // [{date, filename, filter, mean, median, min, max}]
    this._hasImage = false;
    this._loadToken = 0;
    this._rendered = false;
    this._stripKey = null;
    this._unsubHassEvent = null;
  }

  setConfig(config) {
    this._config = {
      refresh_on_save: config.refresh_on_save ?? true,
      show_strip: config.show_strip ?? true,
      show_histogram: config.show_histogram ?? true,
      quality: config.quality ?? 85,
      stretch: config.stretch ?? true,
      strip_count: config.strip_count ?? 6,
      prefix: config.prefix ?? DEFAULT_PREFIX,
      device_id: config.device_id,
    };
    // A new config may name a different rig: make the next `set hass` re-resolve.
    this._resolved = {};
    this._resolvedFrom = null;
    this._entryId = null;
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
      this._entryId = this._rigEntryId(hass);
    }

    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
    }

    // On the first render, and whenever a new config or a registry change
    // points the card at another entity — which may be another rig's. Past a
    // load still in flight: that one is for the old entity.
    const imageEntity = this._entityId();
    if (imageEntity !== this._imageEntity) {
      this._imageEntity = imageEntity;
      this._loadImage(0, this._loading);
    }

    // Keyed on the attribute's contents, not on `nina_image_save`: the bus
    // event reaches the card before the state update carrying the new frame,
    // so a strip rebuilt from the event would render the previous list.
    // Also when only the histogram is on: it reads what this loads.
    const stripKey = JSON.stringify(this._recentFrames());
    if (stripKey !== this._stripKey
        && (this._config.show_strip || this._config.show_histogram)) {
      this._stripKey = stripKey;
      this._loadStrip();
    }

    this._updateOverlay();
    this._updateStatsRow();
    this._updateHeaderBadge();

    this._subscribe();
  }

  // Lovelace can detach and reattach a card without recreating it, as when
  // masonry re-lays its columns out, and a detached card has unsubscribed.
  connectedCallback() {
    this._detached = false;
    if (this._hass) this._subscribe();
  }

  // Refresh on `nina_image_save`, once per attachment. Not while detached,
  // which a card can be and still be handed `hass`.
  _subscribe() {
    if (this._detached || this._unsubHassEvent || !this._config.refresh_on_save
        || !this._hass.connection) return;
    this._unsubHassEvent = this._hass.connection.subscribeEvents(
      (event) => {
        if (!this._fromThisRig(event?.data ?? {})) return;
        this._currentIndex = 0;
        this._loadImage(0, true);
      },
      "nina_image_save"
    );
  }

  // Every configured rig fires `nina_image_save`, so a two-rig dashboard would
  // otherwise refresh both panels off whichever rig saved a frame. The entry id
  // is exact; the instance name is what is left when the rig did not resolve,
  // and it matches only while `prefix:` is its slug.
  _fromThisRig({ entry_id: entryId, instance }) {
    if (this._entryId) return entryId === this._entryId;
    return !instance || slug(instance) === this._config.prefix;
  }

  disconnectedCallback() {
    this._detached = true;
    // `subscribeEvents` resolves to the unsubscribe function, so a card
    // removed before it resolves must await the promise to unsubscribe at all.
    Promise.resolve(this._unsubHassEvent)
      .then((unsub) => { if (typeof unsub === "function") unsub(); })
      .catch(() => {});
    this._unsubHassEvent = null;
  }

  _s(id, fallback = null) {
    const e = this._hass?.states?.[id];
    return e ? e.state : fallback;
  }
  _f(id, fallback = 0) { return parseFloat(this._s(id)) || fallback; }

  // The resolved entity id for a `translation_key`, falling back to a prefixed
  // `slug` when there is nothing to resolve: an entity with no translation key,
  // a disabled one, or a rig the resolver cannot identify.
  //
  // `slug` is the entity-id suffix — the device name plus the entity name — so
  // it is not always the key: the camera's exposing sensor is keyed
  // `camera_is_exposing`.
  _eid(domain, key, slug = key) {
    return this._resolved[`${domain}.${key}`] ?? `${domain}.${this._config.prefix}_${slug}`;
  }

  // The entity the proxy resolves to a rig by — any of this integration's
  // own hub entities works, but NOT a piece of equipment's: `camera_state`
  // is gated behind the camera being observed (kind="camera") and is absent
  // from the registry on a fresh install, which would 404 every request.
  // `last_image_mean_adu` (kind=None) is a hub entity, always created at
  // setup, and the card already reads it for `recent_frames`.
  _entityId() { return this._eid("sensor", "last_image_mean_adu"); }

  // The config entry of the rig whose images this card shows, which is how a
  // `nina_image_save` event names its rig: the hub's own identifier is the
  // entry id (device.py `device_identifiers`). `null` without a registry.
  _rigEntryId(hass) {
    const hub = hass.devices?.[hass.entities?.[this._entityId()]?.device_id];
    return hub?.identifiers?.find(([domain]) => domain === "nina_astrophotography")?.[1]
      ?? null;
  }

  // The frame on screen, from the `recent_frames` attribute. Index 0 is the
  // newest of any type, matching what the proxy serves at history index 0.
  _frame() { return this._historyMeta[this._currentIndex] || {}; }
  _attr(id, attr, fallback = null) {
    const e = this._hass?.states?.[id];
    return e?.attributes?.[attr] ?? fallback;
  }

  // Already newest-first and bounded (session.py's `recent_frames`) — no
  // fetch of our own, and no reversal needed.
  _recentFrames() { return this._attr(this._entityId(), "recent_frames", []); }

  // ── Signed, same-origin image URLs ──────────────────────────────────────

  // The unsigned path: a stable, cache-key-free description of one frame.
  _imagePath(index, forStrip = false) {
    const cfg = this._config;
    const params = new URLSearchParams({
      quality: forStrip ? "40" : String(cfg.quality),
      ...(cfg.stretch ? { autoPrepare: "true" } : {}),
    });
    return `/api/nina_astrophotography/image/${this._entityId()}/${index}?${params}`;
  }

  // Signed right before use: `auth/sign_path` is Home Assistant's mechanism
  // for handing an authenticated resource a short-lived URL usable directly
  // as `<img src>`, which cannot carry an Authorization header itself.
  async _signedUrl(path) {
    const { path: signed } = await this._hass.callWS({
      type: "auth/sign_path",
      path,
      expires: SIGNED_URL_TTL_SECONDS,
    });
    return signed;
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
      if (this._hasImage) this._openModal().catch(() => {});
    });
    this.shadowRoot.getElementById("modal").addEventListener("click", e => {
      if (e.target !== this.shadowRoot.getElementById("modal-img")) this._closeModal();
    });
    this.shadowRoot.getElementById("modal-close").addEventListener("click", () => this._closeModal());
  }

  // ── Image loading ─────────────────────────────────────────────────────

  async _loadImage(index, silent = false) {
    if (this._loading && !silent) return;

    const img    = this.shadowRoot?.getElementById("main-img");
    const spinner = this.shadowRoot?.getElementById("spinner");
    const noImg  = this.shadowRoot?.getElementById("no-image");
    // Before the flag, not after: returning past it would wedge `_loading`
    // true and block every later load.
    if (!img) return;

    // `silent` bypasses the guard above, so an IMAGE-SAVE refresh can race a
    // strip click. Each load gets its own token and its own off-DOM probe
    // image — the shared `<img>` and `_hasImage`/`_loading` are only ever
    // touched by whichever load is still current when it settles, so a
    // superseded load's promise still resolves instead of hanging forever,
    // it just does nothing.
    const token = ++this._loadToken;
    this._loading = true;
    this._currentIndex = index;

    if (!silent) {
      img.classList.add("loading");
      spinner?.classList.add("active");
    }

    try {
      const url = await this._signedUrl(this._imagePath(index));
      await new Promise((resolve, reject) => {
        const probe = new Image();
        probe.onload = resolve;
        probe.onerror = () => reject(new Error("image failed to load"));
        probe.src = url;
      });
      if (token !== this._loadToken) return;
      img.src = url;
      this._hasImage = true;
      img.classList.remove("loading");
      spinner?.classList.remove("active");
      noImg && (noImg.style.display = "none");
      img.style.display = "block";
      if (this._config.show_histogram) this._drawHistogram();
      this._updateStripActive();
    } catch (err) {
      if (token !== this._loadToken) return;
      this._hasImage = false;
      img.classList.remove("loading");
      spinner?.classList.remove("active");
      // Show no-image state only if this is the latest frame (not a strip click)
      if (index === 0) {
        img.style.display = "none";
        noImg && (noImg.style.display = "flex");
      }
    } finally {
      if (token === this._loadToken) this._loading = false;
    }
  }

  // ── Strip loading ─────────────────────────────────────────────────────

  async _loadStrip() {
    const strip = this.shadowRoot?.getElementById("strip");
    if (!strip) return;

    const count = this._config.strip_count;
    const recentFrames = this._recentFrames();
    this._historyMeta = recentFrames.slice(0, count);
    if (this._config.show_histogram) this._drawHistogram();

    // Bounded to what actually exists: `strip_count` thumbnails would each
    // cost a sign + proxy round trip for an index N.I.N.A. cannot serve. A
    // rig whose attribute has not populated yet (old data, first render)
    // falls back to the configured count rather than showing nothing.
    const thumbCount = recentFrames.length > 0
      ? Math.min(count, recentFrames.length) : count;

    strip.innerHTML = "";
    for (let i = 0; i < thumbCount; i++) {
      const thumb = document.createElement("div");
      thumb.className = `strip-thumb${i === this._currentIndex ? " active" : ""}`;
      thumb.dataset.index = i;

      const img = document.createElement("img");
      img.alt = `Frame -${i}`;
      img.onerror = () => { thumb.style.opacity = "0.3"; };
      thumb.appendChild(img);
      this._signedUrl(this._imagePath(i, true))
        .then((url) => { img.src = url; })
        .catch(() => { thumb.style.opacity = "0.3"; });

      // Filter label from the recent-frames metadata
      const filterName = this._historyMeta[i]?.filter ?? "";
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

    // All of it from the frame on screen, out of `recent_frames`. The mean-ADU
    // sensor is no fallback: it holds the newest light's, and the frame on
    // screen may be a flat.
    const frame = this._frame();
    const mean = finite(frame.mean);
    const min = finite(frame.min);
    const max = finite(frame.max);
    const median = finite(frame.median) ?? mean;

    const rangeEl = this.shadowRoot?.getElementById("hist-range");
    if (mean === null || min === null || max === null) {
      if (rangeEl) rangeEl.textContent = "—";
      return;
    }
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

    const hfr    = this._f(this._eid("sensor", "last_image_hfr"));
    // `_s`'s fallback covers a missing entity only; `known` covers one that
    // exists and reads `unknown` or `unavailable`, which would otherwise be
    // drawn as a pill spelling the word.
    const stars  = known(this._s(this._eid("sensor", "last_image_star_count")));
    const filter = known(this._s(this._eid("sensor", "last_image_filter")));
    const rms    = known(this._s(this._eid("sensor", "last_image_rms")));
    const target = known(this._s(this._eid("sensor", "last_image_target")));

    const pills = [];
    if (filter && filter !== "null") {
      pills.push(`<span class="stat-pill"><span class="dot"></span>${filter}</span>`);
    }
    if (hfr > 0) {
      const cls = hfr > 3 ? "warn" : "";
      pills.push(`<span class="stat-pill ${cls}"><span class="dot"></span>HFR ${hfr.toFixed(2)} px</span>`);
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
    const hfr  = this._f(this._eid("sensor", "last_image_hfr"));
    const stars = this._s(this._eid("sensor", "last_image_star_count"), "—");
    const adu   = this._f(this._entityId());
    const exp   = this._f(this._eid("sensor", "last_image_exposure"));

    set("st-hfr",   hfr  > 0 ? `${hfr.toFixed(2)} px`   : "—");
    set("st-stars", shown(stars));
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

    // Lights, not frames: the count sensor's state includes the calibration
    // frames, and the integration time beside it is lights only.
    const count   = shown(this._attr(this._eid("sensor", "session_image_count"), "light_count"));
    const intTime = this._f(this._eid("sensor", "session_integration_time"));
    const exposing = this._s(
      this._eid("binary_sensor", "camera_is_exposing", "camera_exposing")) === "on";
    // A disconnected camera makes its entities unavailable rather than
    // publishing an off state.
    const cameraState = this._s(this._eid("sensor", "camera_state"));
    const connected = cameraState !== null && cameraState !== "unavailable";
    const target = known(this._s(this._eid("sensor", "last_image_target")));
    const filter = known(this._s(this._eid("sensor", "last_image_filter")));
    const index  = this._currentIndex;

    if (!connected) {
      badge.textContent = "Disconnected";
      badge.className   = "badge warn";
    } else if (exposing) {
      badge.textContent = "Exposing…";
      badge.className   = "badge";
    } else {
      badge.textContent = `${count} lights`;
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
      if (intTime > 0) parts.push(`${intTime.toFixed(1)} h`);
      sub.textContent = parts.join(" · ") || "No lights yet this session";
    }
  }

  // ── Modal ─────────────────────────────────────────────────────────────

  async _openModal() {
    const modal    = this.shadowRoot?.getElementById("modal");
    const modalImg = this.shadowRoot?.getElementById("modal-img");
    if (!modal || !modalImg) return;
    // Full-quality version for the modal, signed fresh for this viewing.
    modalImg.src = await this._signedUrl(this._imagePath(this._currentIndex));
    modal.classList.add("open");
  }

  _closeModal() {
    this.shadowRoot?.getElementById("modal")?.classList.remove("open");
  }

  getCardSize() { return 7; }

  static getStubConfig() {
    return {};
  }
}

// Guarded: see nina-frame-stats-card.js — a leftover 1.4.5 `/local/` resource
// defining the same tag would otherwise throw and abort this whole module.
if (!customElements.get("nina-image-panel-card")) {
  customElements.define("nina-image-panel-card", NinaImagePanelCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-image-panel-card",
  name: "N.I.N.A. Image Panel",
  description: "Live last-frame viewer with stats overlay, histogram, and frame strip.",
  preview: false,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-IMAGE-PANEL-CARD %c v${VERSION} `,
  "background:#12121e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #7b8de8",
  "background:#7b8de8;color:#12121e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

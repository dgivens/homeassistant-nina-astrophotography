/**
 * N.I.N.A. Livestack Card
 *
 * The Livestack plugin's stacks: one per target and filter, each as the plugin
 * last stretched it, picked from chips that carry each stack's frame count.
 *
 * Everything describing a stack comes from the livestack image entity's
 * `stacks` attribute — every stack updated this session, newest first, each with its
 * own frame count and update time — so the card needs nothing polled. The
 * bytes come through the integration's proxy, same origin as Home Assistant,
 * since N.I.N.A. serves plain HTTP:
 *
 *   GET /api/nina_astrophotography/livestack/{entity_id}?target=…&filter=…
 *
 * signed just before use via `auth/sign_path`, so `<img src>` can load it.
 *
 * Each request makes the imaging PC scale and encode the stack again, so the
 * card asks for as few as it can: one load at a time, the stack on screen only
 * when its own update time moves, none while the page is hidden, and no wider
 * than it is drawn. Full size is fetched only for the zoomable view.
 *
 * Colour and mono are told apart by the counts the plugin reports, never by
 * the filter's name, which is whatever the operator called it.
 *
 * Card config — one rig needs none: the card finds its own entities in the
 * registry.
 *   type: custom:nina-livestack-card
 *   device_id: abc123       # which rig, for two or more; any one of its devices
 *   prefix: n_i_n_a         # fallback only, for the entities that cannot resolve
 *   follow_latest: true     # show whichever stack updated last (default true)
 *   show_controls: true     # the start/stop button (default true)
 *   quality: 85             # JPEG quality 1-100 (default 85)
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import { CHEVRON, COLLAPSE_STYLE, Collapse } from "./nina-collapse.js";
import { LinkView, RigEntities } from "./nina-entity-resolver.js";
import { safe } from "./nina-units.js";
import { ON_IMAGE, THEME, applyTheme } from "./nina-theme.js";

const VERSION = "2.6.0";

const DEFAULT_QUALITY = 85;

// Signed just before use: a fresh signature per call busts the browser's cache
// across reloads of the same stack.
const SIGNED_URL_TTL_SECONDS = 30;

// Device pixels across for a preview the card could not measure.
const FALLBACK_PREVIEW_WIDTH = 1600;

// How often the age of the stack on screen is rewritten.
const AGE_TICK_MS = 30_000;

const MAX_ZOOM = 8;

// A browser draws an image with no src, or a failed one, as its alt text and a
// broken-image icon. Hidden, it is not announced either. Call before `src`.
function hideUntilLoaded(img) {
  img.style.visibility = "hidden";
  img.onload = () => { img.style.visibility = ""; };
  img.onerror = () => { img.style.visibility = "hidden"; };
}

const sameStack = (a, b) => a?.target === b?.target && a?.filter === b?.filter;

// A colour stack counts each channel and leaves `count` null; a channel with
// no frame yet is null too.
function channels(stack) {
  const rgb = [stack.red_count, stack.green_count, stack.blue_count];
  return rgb.some(Number.isFinite) ? rgb : null;
}

// "24 frames", "R 12 · G 11 · B —", or null for a stack that reported none.
function countText(stack) {
  if (Number.isFinite(stack.count)) {
    return `${stack.count} frame${stack.count === 1 ? "" : "s"}`;
  }
  const rgb = channels(stack);
  if (!rgb) return null;
  return ["R", "G", "B"]
    .map((name, i) => `${name} ${Number.isFinite(rgb[i]) ? rgb[i] : "—"}`)
    .join(" · ");
}

// The count on a chip: "24", or "12|11|9" for a colour stack.
function chipCount(stack) {
  if (Number.isFinite(stack.count)) return String(stack.count);
  const rgb = channels(stack);
  return rgb ? rgb.map((n) => (Number.isFinite(n) ? n : "–")).join("|") : "";
}

function ageText(iso) {
  const ms = Date.now() - Date.parse(iso);
  if (!Number.isFinite(ms)) return null;
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours >= 24) return `${Math.floor(hours / 24)} d ago`;
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min ago` : `${hours} h ago`;
}

const STYLE = `
  ${THEME}
  ${COLLAPSE_STYLE}
  :host {
    display: block;
    --bg:      var(--ha-card-background, var(--card-background-color, #12121e));
    --border:  var(--divider-color, rgba(255,255,255,0.1));
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
    background: color-mix(in srgb, var(--accent) 7%, transparent);
  }
  .header .titles { flex: 1; min-width: 0; }
  .header .title { font-size: 1rem; font-weight: 600; }
  .header .sub {
    font-size: 0.68rem; color: var(--muted); margin-top: 1px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .badge {
    font-size: 0.65rem; font-weight: 700; letter-spacing: .4px;
    padding: 3px 8px; border-radius: 20px; white-space: nowrap;
    background: color-mix(in srgb, var(--accent2) 15%, transparent); color: var(--accent2);
    border: 1px solid color-mix(in srgb, var(--accent2) 30%, transparent);
  }
  .badge.idle {
    background: color-mix(in srgb, var(--ink) 6%, transparent); color: var(--muted);
    border-color: color-mix(in srgb, var(--ink) 15%, transparent);
  }
  .badge.warn {
    background: color-mix(in srgb, var(--warn) 15%, transparent); color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 30%, transparent);
  }
  .badge[hidden], .toggle[hidden], .row[hidden] { display: none; }
  .toggle {
    font: inherit; font-size: 0.7rem; font-weight: 600;
    padding: 4px 12px; border-radius: 20px; cursor: pointer;
    color: var(--text); background: color-mix(in srgb, var(--ink) 8%, transparent);
    border: 1px solid color-mix(in srgb, var(--ink) 18%, transparent);
  }
  .toggle:hover { background: color-mix(in srgb, var(--ink) 14%, transparent); }
  .toggle:focus-visible { outline: 2px solid var(--accent2); outline-offset: 1px; }
  ha-card.stale .overlay, ha-card.stale .picker { opacity: 0.5; }

  /* Over the stack, which is dark whatever the theme. */
  .img-wrap, .modal-bg { ${ON_IMAGE} }

  .img-wrap {
    position: relative;
    background: #000;
    width: 100%;
    aspect-ratio: 4/3;
    max-height: 70vh;
    overflow: hidden;
  }
  .img-wrap.has-image { cursor: zoom-in; }
  .img-wrap img {
    width: 100%; height: 100%;
    object-fit: contain;
    display: block;
    transition: opacity 0.3s ease;
  }
  .img-wrap img.loading { opacity: 0.4; }
  .spinner {
    position: absolute; top: 50%; left: 50%;
    transform: translate(-50%,-50%);
    width: 32px; height: 32px;
    border: 2px solid rgba(255,255,255,0.15);
    border-top-color: var(--accent2);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    display: none;
  }
  .spinner.active { display: block; }
  @keyframes spin { to { transform: translate(-50%,-50%) rotate(360deg); } }

  .overlay {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 10px 12px 8px;
    background: linear-gradient(transparent, rgba(0,0,0,0.75));
    display: flex; align-items: flex-end; justify-content: space-between;
    gap: 8px;
  }
  .overlay:empty { display: none; }
  .overlay-left { display: flex; flex-wrap: wrap; gap: 5px; }
  .pill {
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(0,0,0,0.55); backdrop-filter: blur(4px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 20px; padding: 3px 8px;
    font-size: 0.65rem; font-weight: 600; white-space: nowrap;
  }
  .pill .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent2); }
  .overlay .target {
    font-size: 0.65rem; color: var(--muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 45%;
  }

  .empty {
    position: absolute; inset: 0;
    display: none; flex-direction: column; align-items: center; justify-content: center;
    gap: 10px; padding: 24px;
    color: var(--muted); font-size: 0.82rem; text-align: center;
  }
  .empty.active { display: flex; }
  .empty svg { opacity: 0.3; }
  .empty .hint { font-size: 0.68rem; opacity: 0.7; }

  .picker {
    display: flex; flex-direction: column; gap: 6px;
    padding: 8px 10px 10px;
    border-top: 1px solid var(--border);
  }
  .picker:empty { display: none; }
  .row {
    display: flex; gap: 5px; overflow-x: auto;
    scrollbar-width: none;
  }
  .row::-webkit-scrollbar { display: none; }
  .chip {
    flex-shrink: 0;
    display: inline-flex; align-items: center; gap: 5px;
    font: inherit; font-size: 0.7rem; font-weight: 600;
    padding: 4px 10px; border-radius: 20px; cursor: pointer;
    color: var(--text);
    background: color-mix(in srgb, var(--ink) 5%, transparent);
    border: 1.5px solid color-mix(in srgb, var(--ink) 12%, transparent);
    max-width: 220px;
  }
  .chip .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .chip .n { color: var(--muted); font-weight: 500; font-variant-numeric: tabular-nums; }
  .chip:hover { border-color: color-mix(in srgb, var(--ink) 30%, transparent); }
  .chip.active {
    border-color: var(--accent2);
    background: color-mix(in srgb, var(--accent2) 12%, transparent);
  }
  .chip.target.active {
    border-color: var(--accent);
    background: color-mix(in srgb, var(--accent) 12%, transparent);
  }
  .chip:focus-visible { outline: 2px solid var(--text); outline-offset: -2px; }

  .modal-bg {
    display: none;
    position: fixed; inset: 0; z-index: 9999;
    background: rgba(0,0,0,0.92);
    overflow: hidden;
    touch-action: none;
  }
  .modal-bg.open { display: block; }
  .modal-bg img {
    position: absolute; inset: 0; margin: auto;
    max-width: 100vw; max-height: 100vh;
    transform-origin: center;
    user-select: none; -webkit-user-drag: none;
    cursor: grab;
  }
  .modal-bg .modal-spinner { z-index: 1; }
  .modal-close {
    position: absolute; top: 16px; right: 16px; z-index: 2;
    color: rgba(255,255,255,0.8); font-size: 1.3rem;
    cursor: pointer; background: rgba(0,0,0,0.6);
    border: none; border-radius: 50%; width: 36px; height: 36px;
    display: flex; align-items: center; justify-content: center;
  }
  .modal-caption {
    position: absolute; left: 16px; bottom: 14px; z-index: 2;
    font-size: 0.75rem; color: var(--muted);
    pointer-events: none;
  }
`;

class NinaLivestackCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._following = true; // showing whichever stack updated last
    this._pinned = null;    // the stack shown while not following
    this._shown = null;     // the `stacks` entry on screen, once one loads
    this._wanted = null;    // the load key last asked for
    this._loading = false;
    this._queued = null;
    this._rendered = false;
    this._view = new LinkView();
    this._zoom = { scale: 1, x: 0, y: 0 };
    this._pointers = new Map();
    this._onVisible = () => { if (!document.hidden && this._config) this._update(); };
    this._onKey = (e) => { if (e.key === "Escape") this._closeModal(); };
    this._collapse = new Collapse(this, "nina-livestack-card", (section, open) => {
      this._applyFolds();
      if (open) this._update();
    });
  }

  connectedCallback() {
    document.addEventListener("visibilitychange", this._onVisible);
    this._ticker ??= setInterval(() => this._updateOverlay(), AGE_TICK_MS);
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisible);
    window.removeEventListener("keydown", this._onKey);
    clearInterval(this._ticker);
    this._ticker = undefined;
  }

  setConfig(config) {
    const quality = Number(config.quality ?? DEFAULT_QUALITY);
    this._config = {
      follow_latest: config.follow_latest ?? true,
      show_controls: config.show_controls ?? true,
      quality: quality >= 1 && quality <= 100 ? Math.round(quality) : DEFAULT_QUALITY,
      prefix: config.prefix || DEFAULT_PREFIX,
      device_id: config.device_id,
    };
    this._rig = new RigEntities(this._config.prefix, this._config.device_id);
    this._view.reset();
    this._following = this._config.follow_latest;
    this._pinned = null;
    this._wanted = null;
    this._collapse.scope(this._config);
    if (this._rendered) this._applyFolds();
  }

  set hass(hass) {
    this._live = hass;
    this._rig.refresh(hass);
    applyTheme(this);

    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
    }

    const link = this._view.read(hass, this._rig);
    // While N.I.N.A. is not answering, the readings are its last ones.
    this._hass = link.hass;
    this._link = link;
    this.shadowRoot.querySelector("ha-card")?.classList.toggle("stale", link.stale);
    this._update();
  }

  _eid(domain, key, slug = key) {
    return this._rig.id(domain, key, slug);
  }

  // The entity the proxy resolves a rig by, and the one carrying `stacks`.
  _imageEntity() { return this._eid("image", "livestack"); }
  _switchEntity() { return this._eid("switch", "livestack"); }

  // Newest first (session.py's `stacks`).
  _stacks() {
    const stacks = this._hass?.states?.[this._imageEntity()]?.attributes?.stacks;
    return Array.isArray(stacks) ? stacks : [];
  }

  // The pinned stack while this session still holds it, else the newest.
  _current() {
    const stacks = this._stacks();
    const pinned = !this._following && this._pinned && stacks.find((s) => sameStack(s, this._pinned));
    return pinned || stacks[0] || null;
  }

  _update() {
    const stacks = this._stacks();
    // A pin on a stack the session no longer lists is let go: held, it would
    // leave the card following the newest while still claiming a pin. Not
    // following, the newest is pinned in its place below.
    if (this._pinned && !stacks.some((s) => sameStack(s, this._pinned))) this._pinned = null;
    // Not following: the stack first shown stays until another is picked.
    if (!this._following && !this._pinned && stacks[0]) {
      this._pinned = { target: stacks[0].target, filter: stacks[0].filter };
    }

    const current = this._current();
    // A new image entity is another rig, or the same one re-resolved.
    const key = current
      ? [this._imageEntity(), current.target, current.filter, current.updated].join("\u0000")
      : null;
    // Folded or out of sight, nothing is fetched: each stack is a render on the
    // imaging PC. Unfolding or showing the page catches up.
    if (key !== this._wanted && !document.hidden && this._collapse.open("card")) {
      this._wanted = key;
      this._load(current);
    }

    this._renderPicker();
    this._updateOverlay();
    this._updateHeader();
  }

  // The markup is built once, so a fold is applied to it rather than rendered.
  _applyFolds() {
    this._collapse.sync();
    this._collapse.hide(["img-wrap", "picker"], !this._collapse.open("card"));
  }

  // The unsigned path. `width` null asks for the stack at full size.
  _stackPath(stack, width = null) {
    const params = new URLSearchParams({
      target: stack.target,
      filter: stack.filter,
      quality: String(this._config.quality),
      ...(width ? { width: String(width) } : {}),
    });
    return `/api/nina_astrophotography/livestack/${this._imageEntity()}?${params}`;
  }

  _devicePixels(css) {
    return css ? Math.ceil(css * (window.devicePixelRatio || 1)) : null;
  }

  // Lovelace hands a card `hass` before attaching it, in the same task, so an
  // unmeasured card waits one task; one still unmeasured gets a cap.
  async _previewWidth() {
    const wrap = () => this.shadowRoot.getElementById("img-wrap")?.clientWidth;
    if (!wrap()) await new Promise((resolve) => setTimeout(resolve));
    return this._devicePixels(wrap()) ?? FALLBACK_PREVIEW_WIDTH;
  }

  async _signedUrl(path) {
    const { path: signed } = await this._live.callWS({
      type: "auth/sign_path",
      path,
      expires: SIGNED_URL_TTL_SECONDS,
    });
    return signed;
  }

  _buildDOM() {
    const controls = this._config.show_controls
      ? `<button class="toggle" id="toggle" hidden></button>`
      : "";
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header"${this._collapse.attrs("card")}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" style="stroke:var(--accent2)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <polygon points="12 3 21 8 12 13 3 8 12 3"/>
            <polyline points="3 12 12 17 21 12"/><polyline points="3 16 12 21 21 16"/>
          </svg>
          <div class="titles">
            <div class="title">Live Stack</div>
            <div class="sub" id="sub">Waiting for data…</div>
          </div>
          <span class="badge" id="badge" hidden></span>
          ${controls}
          ${CHEVRON}
        </div>
        ${this._collapse.banner()}

        <div class="img-wrap" id="img-wrap">
          <img id="main-img" alt="" />
          <div class="spinner" id="spinner"></div>
          <div class="overlay" id="overlay"></div>
          <div class="empty" id="empty">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" stroke-linejoin="round">
              <polygon points="12 3 21 8 12 13 3 8 12 3"/>
              <polyline points="3 12 12 17 21 12"/><polyline points="3 16 12 21 21 16"/>
            </svg>
            <div id="empty-text"></div>
            <div class="hint" id="empty-hint"></div>
          </div>
        </div>

        <div class="picker" id="picker">
          <div class="row" id="targets" role="group" aria-label="Target" hidden></div>
          <div class="row" id="filters" role="group" aria-label="Stack" hidden></div>
        </div>

        <div class="modal-bg" id="modal" role="dialog" aria-label="Live stack, zoomable">
          <button class="modal-close" id="modal-close" aria-label="Close">✕</button>
          <div class="spinner modal-spinner" id="modal-spinner"></div>
          <img id="modal-img" alt="" draggable="false" />
          <div class="modal-caption" id="modal-caption"></div>
        </div>
      </ha-card>
    `;

    this._applyFolds();
    hideUntilLoaded(this.shadowRoot.getElementById("main-img"));
    this.shadowRoot.getElementById("img-wrap").addEventListener("click", () => {
      if (this._shown) this._openModal().catch(() => {});
    });
    this.shadowRoot.getElementById("toggle")?.addEventListener("click", () => this._toggle());
    this._bindModal();
  }

  // ── loading ────────────────────────────────────────────────────────────

  // One load at a time: a stack asked for meanwhile replaces any still
  // waiting, so a burst of updates costs N.I.N.A. two renders, not one each.
  _load(stack) {
    const spinner = this.shadowRoot?.getElementById("spinner");
    const img = this.shadowRoot?.getElementById("main-img");
    // Another stack, not a newer copy of this one: dim the old one at once.
    if (stack && !sameStack(stack, this._shown)) {
      img?.classList.add("loading");
      spinner?.classList.add("active");
    }
    if (this._loading) {
      this._queued = { stack };
      return;
    }
    this._loading = true;
    this._loadImage(stack).catch(() => {}).finally(() => {
      this._loading = false;
      const next = this._queued;
      this._queued = null;
      if (next) this._load(next.stack);
      else this._updateEmpty();
    });
  }

  async _loadImage(stack) {
    const img = this.shadowRoot?.getElementById("main-img");
    const wrap = this.shadowRoot?.getElementById("img-wrap");
    const spinner = this.shadowRoot?.getElementById("spinner");
    if (!img) return;
    const settle = () => {
      if (this._queued) return;
      img.classList.remove("loading");
      spinner?.classList.remove("active");
    };

    try {
      if (!stack) throw new Error("no stack to load");
      const width = await this._previewWidth();
      // Folded while measuring: the width is the fallback, not the card's, and
      // unfolding asks again.
      if (!this._collapse.open("card")) {
        this._wanted = null;
        settle();
        return;
      }
      const url = await this._signedUrl(this._stackPath(stack, width));
      const size = await new Promise((resolve, reject) => {
        const probe = new Image();
        probe.onload = () => resolve([probe.naturalWidth, probe.naturalHeight]);
        probe.onerror = () => reject(new Error("stack failed to load"));
        probe.src = url;
      });
      img.src = url;
      img.alt = `Live stack of ${stack.target}, ${stack.filter}`;
      // The frame's own shape, so the card fits the stack rather than a fixed 4:3.
      if (size[0] > 0 && size[1] > 0) wrap.style.aspectRatio = `${size[0]} / ${size[1]}`;
      this._shown = stack;
      img.style.display = "block";
    } catch (err) {
      this._shown = null;
      img.style.display = "none";
      img.alt = "";
    }
    settle();
    wrap?.classList.toggle("has-image", this._shown !== null);
    this._updateOverlay();
  }

  // ── picking ────────────────────────────────────────────────────────────

  // `null` is the Latest chip: follow whichever stack updates.
  _pick(pinned) {
    this._following = pinned === null;
    this._pinned = pinned;
    this._update();
  }

  _chip(className, label, count, active, onPick, ariaLabel) {
    const chip = document.createElement("button");
    chip.className = `chip ${className}${active ? " active" : ""}`;
    chip.setAttribute("aria-pressed", String(active));
    if (ariaLabel) chip.setAttribute("aria-label", ariaLabel);
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = label;
    chip.appendChild(name);
    if (count) {
      const n = document.createElement("span");
      n.className = "n";
      n.textContent = count;
      chip.appendChild(n);
    }
    chip.addEventListener("click", onPick);
    return chip;
  }

  // Rebuilt only when what the chips say changes: `set hass` arrives for every
  // state change in Home Assistant, and a rebuild drops a focused chip's focus.
  _renderPicker() {
    const targetsRow = this.shadowRoot?.getElementById("targets");
    const filtersRow = this.shadowRoot?.getElementById("filters");
    if (!targetsRow || !filtersRow) return;

    const stacks = this._stacks();
    const current = this._current();
    // In order of each target's newest update.
    const targets = [...new Set(stacks.map((s) => s.target))];
    // Alphabetical, so a chip stays put while the filters update in turn.
    const filters = stacks
      .filter((s) => s.target === current?.target)
      .sort((a, b) => a.filter.localeCompare(b.filter));
    const following = this._following;

    const key = JSON.stringify([targets, filters.map((s) => [s.filter, chipCount(s)]),
      current?.target, current?.filter, following]);
    if (key === this._pickerKey) return;
    this._pickerKey = key;

    targetsRow.innerHTML = "";
    for (const target of targets) {
      const newest = stacks.find((s) => s.target === target);
      targetsRow.appendChild(this._chip("target", target, "", target === current?.target,
        () => this._pick({ target, filter: newest.filter })));
    }
    targetsRow.hidden = targets.length < 2;

    const chips = filters.map((s) => this._chip("filter", s.filter, chipCount(s),
      !following && sameStack(s, current),
      () => this._pick({ target: s.target, filter: s.filter }),
      [s.filter, countText(s)].filter(Boolean).join(", ")));
    if (stacks.length > 1) {
      chips.unshift(this._chip("latest", "Latest", "", following, () => this._pick(null),
        "Latest: follow the stack updated last"));
    }
    filtersRow.innerHTML = "";
    for (const chip of chips) filtersRow.appendChild(chip);
    filtersRow.hidden = chips.length === 0;
  }

  // ── readings ───────────────────────────────────────────────────────────

  _updateOverlay() {
    const overlay = this.shadowRoot?.getElementById("overlay");
    if (!overlay) return;
    // The stack on screen; one still loading is described once it arrives.
    const stack = this._shown;
    if (!stack) {
      overlay.innerHTML = "";
      return;
    }
    const pills = [stack.filter, countText(stack), ageText(stack.updated)]
      .filter((text) => text)
      .map((text) => `<span class="pill"><span class="dot"></span>${safe(text)}</span>`);
    overlay.innerHTML = `<div class="overlay-left">${pills.join("")}</div>`
      + `<span class="target">${safe(stack.target)}</span>`;
  }

  _running() {
    const state = this._hass?.states?.[this._switchEntity()]?.state;
    return state === "on" ? true : state === "off" ? false : null;
  }

  _updateHeader() {
    const badge = this.shadowRoot?.getElementById("badge");
    const sub = this.shadowRoot?.getElementById("sub");
    const toggle = this.shadowRoot?.getElementById("toggle");
    if (!badge) return;
    const running = this._running();
    const unreachable = this._link.lost && !this._link.stale;

    let text = null;
    let tone = "";
    if (this._link.stale) {
      const since = this._link.since
        ? ` since ${new Date(this._link.since).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
        : "";
      text = `No answer${since}`;
      tone = "warn";
    } else if (unreachable) {
      text = "N.I.N.A. unreachable";
      tone = "warn";
    } else if (running !== null) {
      text = running ? "Stacking" : "Stopped";
      tone = running ? "" : "idle";
    }
    badge.hidden = text === null;
    badge.textContent = text ?? "";
    badge.className = `badge ${tone}`;

    if (toggle) {
      // A command needs the link up, and the switch to know which way to go.
      toggle.hidden = running === null || this._link.lost || this._link.stale;
      toggle.textContent = running ? "Stop" : "Start";
      toggle.setAttribute("aria-label", running ? "Stop the live stack" : "Start the live stack");
    }

    const current = this._current();
    if (sub) {
      const count = this._stacks().length;
      sub.textContent = current
        ? `${current.target} · ${count} stack${count === 1 ? "" : "s"} this session`
        : "No stacks this session";
    }
    this._updateEmpty();
  }

  _updateEmpty() {
    const empty = this.shadowRoot?.getElementById("empty");
    const text = this.shadowRoot?.getElementById("empty-text");
    const hint = this.shadowRoot?.getElementById("empty-hint");
    if (!empty || !this._link) return;
    const current = this._current();
    const loading = this._loading || this._queued !== null;
    const show = !this._shown && !(current && loading);
    empty.classList.toggle("active", show);
    if (!show) return;
    if (this._link.lost && !this._link.stale) {
      text.textContent = "N.I.N.A. is not answering";
      hint.textContent = "The stack will return when it does.";
    } else if (current) {
      text.textContent = "Could not load this stack";
      hint.textContent = "N.I.N.A. may no longer hold it, or did not answer in time.";
    } else {
      text.textContent = "No live stack this session";
      hint.textContent = this._running() === false
        ? "Start the live stack, and each stack appears here as it updates."
        : "Each stack appears here as N.I.N.A.'s Livestack plugin updates it.";
    }
  }

  _toggle() {
    const running = this._running();
    if (running === null) return;
    this._live.callService("switch", running ? "turn_off" : "turn_on",
      { entity_id: this._switchEntity() });
  }

  // ── the zoomable view ──────────────────────────────────────────────────

  async _openModal() {
    const modal = this.shadowRoot?.getElementById("modal");
    const img = this.shadowRoot?.getElementById("modal-img");
    const spinner = this.shadowRoot?.getElementById("modal-spinner");
    const stack = this._shown;
    if (!modal || !img || !stack) return;
    this._resetZoom();
    hideUntilLoaded(img);
    const loaded = img.onload;
    img.onload = () => { loaded(); spinner.classList.remove("active"); };
    img.onerror = () => spinner.classList.remove("active");
    spinner.classList.add("active");
    this.shadowRoot.getElementById("modal-caption").textContent =
      [stack.target, stack.filter, countText(stack)].filter(Boolean).join(" · ");
    modal.classList.add("open");
    window.addEventListener("keydown", this._onKey);
    // Full size, signed fresh for this viewing.
    try {
      img.src = await this._signedUrl(this._stackPath(stack));
    } catch {
      this._closeModal();
    }
  }

  _closeModal() {
    this.shadowRoot?.getElementById("modal")?.classList.remove("open");
    window.removeEventListener("keydown", this._onKey);
    this._pointers.clear();
  }

  _resetZoom() {
    this._zoom = { scale: 1, x: 0, y: 0 };
    this._applyZoom();
  }

  _applyZoom() {
    const img = this.shadowRoot?.getElementById("modal-img");
    if (!img) return;
    // Pans only as far as keeps the zoomed image covering its unzoomed
    // footprint, so a drag cannot lose it off screen. `offset*` is the fitted
    // image, untransformed.
    const { scale } = this._zoom;
    const clamp = (v, size) => {
      const reach = ((scale - 1) * size) / 2;
      return size ? Math.max(-reach, Math.min(reach, v)) : v;
    };
    const x = clamp(this._zoom.x, img.offsetWidth);
    const y = clamp(this._zoom.y, img.offsetHeight);
    this._zoom = { scale, x, y };
    img.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  }

  // Scale to `scale` keeping the image point under `point` (relative to the
  // view's centre) where it is.
  _zoomAt(scale, point, from = this._zoom) {
    const s = Math.min(Math.max(scale, 1), MAX_ZOOM);
    if (s === 1) {
      this._zoom = { scale: 1, x: 0, y: 0 };
    } else {
      const k = s / from.scale;
      this._zoom = { scale: s, x: point.x - (point.x - from.x) * k, y: point.y - (point.y - from.y) * k };
    }
    this._applyZoom();
  }

  _bindModal() {
    const modal = this.shadowRoot.getElementById("modal");
    const img = this.shadowRoot.getElementById("modal-img");
    const centred = (e) => {
      const r = modal.getBoundingClientRect();
      return { x: e.clientX - r.left - r.width / 2, y: e.clientY - r.top - r.height / 2 };
    };
    let gesture = null;   // what the pointers down began: a pan or a pinch
    let moved = false;
    // Captured, a pointer's click and dblclick arrive at the backdrop whatever
    // was pressed, so what the press began on decides what they do.
    let pressed = null;

    this.shadowRoot.getElementById("modal-close").addEventListener("click", (e) => {
      e.stopPropagation();
      this._closeModal();
    });
    // A tap on the backdrop closes; the end of a drag does not.
    modal.addEventListener("click", () => {
      if (!moved && pressed === modal) this._closeModal();
    });
    modal.addEventListener("wheel", (e) => {
      e.preventDefault();
      this._zoomAt(this._zoom.scale * Math.exp(-e.deltaY * 0.002), centred(e));
    }, { passive: false });
    modal.addEventListener("dblclick", (e) => {
      if (pressed === img) this._zoomAt(this._zoom.scale > 1 ? 1 : 2.5, centred(e));
    });

    const begin = () => {
      const points = [...this._pointers.values()];
      if (points.length === 1) {
        gesture = { kind: "pan", from: points[0], zoom: { ...this._zoom } };
      } else if (points.length === 2) {
        const [a, b] = points;
        gesture = {
          kind: "pinch",
          distance: Math.hypot(a.x - b.x, a.y - b.y) || 1,
          mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
          zoom: { ...this._zoom },
        };
      } else {
        gesture = null;
      }
    };
    modal.addEventListener("pointerdown", (e) => {
      if (e.target.closest?.(".modal-close")) return;
      moved = false;
      pressed = e.target;
      modal.setPointerCapture?.(e.pointerId);
      this._pointers.set(e.pointerId, centred(e));
      begin();
    });
    modal.addEventListener("pointermove", (e) => {
      if (!this._pointers.has(e.pointerId) || !gesture) return;
      this._pointers.set(e.pointerId, centred(e));
      const points = [...this._pointers.values()];
      if (gesture.kind === "pan" && points.length === 1) {
        const dx = points[0].x - gesture.from.x;
        const dy = points[0].y - gesture.from.y;
        if (Math.hypot(dx, dy) > 4) moved = true;
        if (this._zoom.scale > 1) {
          this._zoom = { ...gesture.zoom, x: gesture.zoom.x + dx, y: gesture.zoom.y + dy };
          this._applyZoom();
        }
      } else if (gesture.kind === "pinch" && points.length === 2) {
        moved = true;
        const [a, b] = points;
        const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
        const scale = gesture.zoom.scale * Math.hypot(a.x - b.x, a.y - b.y) / gesture.distance;
        // The midpoint's image point follows the fingers as they move.
        const s = Math.min(Math.max(scale, 1), MAX_ZOOM);
        const k = s / gesture.zoom.scale;
        this._zoom = s === 1 ? { scale: 1, x: 0, y: 0 } : {
          scale: s,
          x: mid.x - (gesture.mid.x - gesture.zoom.x) * k,
          y: mid.y - (gesture.mid.y - gesture.zoom.y) * k,
        };
        this._applyZoom();
      }
    });
    const end = (e) => {
      this._pointers.delete(e.pointerId);
      begin();
    };
    modal.addEventListener("pointerup", end);
    modal.addEventListener("pointercancel", end);
  }

  getCardSize() { return 7; }

  static getConfigForm() {
    const toggle = { default: true, selector: { boolean: {} } };
    return configForm([
      {
        name: "follow_latest",
        label: "Follow the latest stack",
        helper: "Show whichever stack updated last. Off keeps the stack shown until "
          + "you pick another.",
        ...toggle,
      },
      {
        name: "show_controls",
        label: "Show start/stop",
        helper: "Start and stop N.I.N.A.'s live stack from the card.",
        ...toggle,
      },
      {
        name: "quality",
        label: "JPEG quality",
        default: DEFAULT_QUALITY,
        selector: { number: { min: 1, max: 100, mode: "box" } },
      },
    ]);
  }

  static getStubConfig() {
    return {};
  }
}

// Guarded, as every card is: a second copy of the module must not throw.
if (!customElements.get("nina-livestack-card")) {
  customElements.define("nina-livestack-card", NinaLivestackCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-livestack-card",
  name: "N.I.N.A. Live Stack",
  description: "The Livestack plugin's stacks, by target and filter, with a zoomable view.",
  preview: false,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-LIVESTACK-CARD %c v${VERSION} `,
  "background:#12121e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #7b8de8",
  "background:#7b8de8;color:#12121e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

/**
 * N.I.N.A. Site Camera Card
 *
 * A pier camera, an all-sky camera or the observatory's own, in the frame the
 * other cards use. The cameras are any camera or image entities, from whatever
 * integration provides them: nothing here reads the rig.
 *
 * Each picture is the entity's own `entity_picture`, which carries its access
 * token. A camera is asked again every `refresh_interval`; an image entity only
 * when its state, the time of its picture, moves. Nothing is fetched while the
 * card is folded or the page hidden. A tap opens the entity's more-info
 * dialog, which is where Home Assistant plays a camera's live stream.
 *
 * Card config:
 *   type: custom:nina-site-camera-card
 *   title: Site Cameras       # the header (default "Site Cameras")
 *   refresh_interval: 10      # seconds between a camera's pictures (default 10)
 *   cameras:
 *     - entity: camera.pier   # a camera or an image entity
 *       name: Pier            # the chip and caption (default: the entity's name)
 *       url: https://…        # a link shown over the picture
 */

import { standaloneForm } from "./nina-card-config.js";
import { CHEVRON, COLLAPSE_STYLE, Collapse } from "./nina-collapse.js";
import { safe } from "./nina-units.js";
import { ON_IMAGE, THEME, applyTheme } from "./nina-theme.js";

const VERSION = "2.6.0";

const DEFAULT_TITLE = "Site Cameras";
const DEFAULT_REFRESH_SECONDS = 10;
const MIN_REFRESH_SECONDS = 2;

const GONE = new Set(["unavailable", "unknown"]);

function ageText(date) {
  const ms = Date.now() - date;
  if (!Number.isFinite(ms)) return null;
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours >= 24) return `${Math.floor(hours / 24)} d ago`;
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min ago` : `${hours} h ago`;
}

// Only a web link is rendered: the address is typed into the card's config.
const webLink = (url) => (/^https?:\/\//i.test(url ?? "") ? url : null);

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
    background: color-mix(in srgb, var(--warn) 15%, transparent); color: var(--warn);
    border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
  }

  /* Over the picture, which is dark whatever the theme. */
  .img-wrap { ${ON_IMAGE} }

  .img-wrap {
    position: relative;
    background: #000;
    width: 100%;
    aspect-ratio: 16/9;
    max-height: 70vh;
    overflow: hidden;
  }
  .img-wrap.has-image { cursor: pointer; }
  .img-wrap:focus-visible { outline: 2px solid var(--accent2); outline-offset: -2px; }
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
  .overlay-left { display: flex; flex-wrap: wrap; gap: 5px; min-width: 0; }
  .pill {
    display: inline-flex; align-items: center; gap: 4px;
    background: rgba(0,0,0,0.55); backdrop-filter: blur(4px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 20px; padding: 3px 8px;
    font-size: 0.65rem; font-weight: 600; white-space: nowrap;
    color: var(--text); text-decoration: none;
  }
  .pill .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent2); }
  .pill.late .dot { background: var(--warn); }
  a.pill:hover { border-color: rgba(255,255,255,0.4); }
  a.pill:focus-visible { outline: 2px solid var(--accent2); outline-offset: 1px; }

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
    display: flex; gap: 5px; overflow-x: auto;
    padding: 8px 10px 10px;
    border-top: 1px solid var(--border);
    scrollbar-width: none;
  }
  .picker::-webkit-scrollbar, .picker:empty { display: none; }
  .chip {
    flex-shrink: 0;
    font: inherit; font-size: 0.7rem; font-weight: 600;
    padding: 4px 10px; border-radius: 20px; cursor: pointer;
    color: var(--text);
    background: color-mix(in srgb, var(--ink) 5%, transparent);
    border: 1.5px solid color-mix(in srgb, var(--ink) 12%, transparent);
    max-width: 220px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .chip:hover { border-color: color-mix(in srgb, var(--ink) 30%, transparent); }
  .chip.active {
    border-color: var(--accent2);
    background: color-mix(in srgb, var(--accent2) 12%, transparent);
  }
  .chip:focus-visible { outline: 2px solid var(--text); outline-offset: -2px; }
`;

const CAMERA_ICON = (size, stroke, width) => `
  <svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ${stroke} stroke-width="${width}" stroke-linecap="round" stroke-linejoin="round">
    <rect x="2" y="6" width="14" height="12" rx="2"/>
    <polygon points="16 10 22 7 22 17 16 14 16 10"/>
  </svg>`;

class NinaSiteCameraCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._picked = 0;      // which of the configured cameras is on screen
    this._shown = null;    // { entity, at } of the picture on screen
    this._asked = null;    // the load key last asked for
    this._loading = false;
    this._failed = false;
    this._ticks = 0;
    this._rendered = false;
    this._onVisible = () => { if (!document.hidden) this._tick(); };
    this._collapse = new Collapse(this, "nina-site-camera-card", (section, open) => {
      this._applyFolds();
      if (open) this._tick();
    });
  }

  connectedCallback() {
    document.addEventListener("visibilitychange", this._onVisible);
    this._startTimer();
  }

  disconnectedCallback() {
    document.removeEventListener("visibilitychange", this._onVisible);
    clearInterval(this._timer);
    this._timer = undefined;
  }

  setConfig(config) {
    const seconds = Number(config.refresh_interval ?? DEFAULT_REFRESH_SECONDS);
    const listed = Array.isArray(config.cameras) ? config.cameras : [];
    this._config = {
      title: config.title || DEFAULT_TITLE,
      refresh_interval: seconds >= MIN_REFRESH_SECONDS ? seconds : DEFAULT_REFRESH_SECONDS,
      cameras: listed
        .filter((camera) => camera?.entity)
        .map(({ entity, name, url }) => ({ entity: String(entity), name: name || null, url: webLink(url) })),
    };
    this._picked = 0;
    this._asked = null;
    this._chipsKey = null;
    // Folds are remembered per rig, and this card's rig is its cameras.
    this._collapse.scope({ device_id: this._cameras().map((camera) => camera.entity).join(",") });
    if (this.isConnected) this._startTimer();
    if (this._rendered) {
      this._applyFolds();
      this._update();
    }
  }

  set hass(hass) {
    this._hass = hass;
    applyTheme(this);
    if (!this._rendered) {
      this._buildDOM();
      this._rendered = true;
    }
    this._update();
  }

  _startTimer() {
    clearInterval(this._timer);
    this._timer = this._config
      ? setInterval(() => this._tick(), this._config.refresh_interval * 1000)
      : undefined;
  }

  // A camera's next picture is due, and a picture that failed is tried again.
  _tick() {
    this._ticks += 1;
    if (this._failed) this._asked = null;
    if (this._rendered && this._hass) this._update();
  }

  _cameras() { return this._config.cameras; }

  _current() {
    const cameras = this._cameras();
    return cameras[this._picked] ?? cameras[0] ?? null;
  }

  _state(camera) {
    return camera ? this._hass?.states?.[camera.entity] ?? null : null;
  }

  _name(camera) {
    return camera.name || this._state(camera)?.attributes?.friendly_name || camera.entity;
  }

  // Whether the entity has a picture to ask for.
  _picture(camera) {
    const row = this._state(camera);
    return row && !GONE.has(row.state) ? row.attributes?.entity_picture ?? null : null;
  }

  _update() {
    const camera = this._current();
    const picture = camera ? this._picture(camera) : null;
    // A picture of a camera no longer shown, or no longer there, comes down.
    if (this._shown && (this._shown.entity !== camera?.entity || !picture)) this._clear();

    // An image entity's state is when its picture was taken; a camera's says
    // nothing of its picture, so the clock decides.
    const version = camera?.entity.startsWith("image.") ? this._state(camera)?.state : this._ticks;
    const key = picture ? `${camera.entity}\u0000${version}` : null;
    if (key === null) this._asked = null;
    else if (key !== this._asked && !this._loading && !document.hidden && this._collapse.open("card")) {
      this._asked = key;
      this._load(camera, picture);
    }

    this._renderChips();
    this._updateHeader();
    this._updateOverlay();
    this._updateEmpty();
  }

  // The markup is built once, so a fold is applied to it rather than rendered.
  _applyFolds() {
    this._collapse.sync();
    this._collapse.hide(["img-wrap", "picker"], !this._collapse.open("card"));
  }

  _buildDOM() {
    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header"${this._collapse.attrs("card")}>
          ${CAMERA_ICON(18, `style="stroke:var(--accent2)"`, 1.5)}
          <div class="titles">
            <div class="title" id="title"></div>
            <div class="sub" id="sub"></div>
          </div>
          <span class="badge" id="badge" hidden></span>
          ${CHEVRON}
        </div>
        ${this._collapse.banner()}

        <div class="img-wrap" id="img-wrap">
          <img id="main-img" alt="" />
          <div class="spinner" id="spinner"></div>
          <div class="overlay" id="overlay"></div>
          <div class="empty" id="empty">
            ${CAMERA_ICON(48, `stroke="currentColor"`, 1)}
            <div id="empty-text"></div>
            <div class="hint" id="empty-hint"></div>
          </div>
        </div>

        <div class="picker" id="picker" role="group" aria-label="Camera"></div>
      </ha-card>
    `;

    this._applyFolds();
    const img = this.shadowRoot.getElementById("main-img");
    // A browser draws an image with no src as its alt text and a broken icon.
    img.style.visibility = "hidden";
    const wrap = this.shadowRoot.getElementById("img-wrap");
    wrap.addEventListener("click", (event) => {
      // The link over the picture is its own control.
      if (!event.target.closest?.("a")) this._moreInfo();
    });
    wrap.addEventListener("keydown", (event) => {
      if (event.target !== wrap || (event.key !== "Enter" && event.key !== " ")) return;
      event.preventDefault();
      this._moreInfo();
    });
  }

  // ── loading ────────────────────────────────────────────────────────────

  _clear() {
    this._shown = null;
    const img = this.shadowRoot.getElementById("main-img");
    if (img) img.style.visibility = "hidden";
  }

  // One load at a time; whatever came due meanwhile is asked for when it ends.
  _load(camera, picture) {
    const img = this.shadowRoot.getElementById("main-img");
    const spinner = this.shadowRoot.getElementById("spinner");
    // Only over an empty frame: a newer picture of the one shown swaps in
    // quietly, and a retry leaves the failure it follows on screen.
    if (!this._shown && !this._failed) spinner?.classList.add("active");
    this._loading = true;
    this._loadImage(camera, picture, img).finally(() => {
      this._loading = false;
      spinner?.classList.remove("active");
      this._update();
    });
  }

  async _loadImage(camera, picture, img) {
    // The same address would be answered from the browser's cache.
    const stamp = `${picture.includes("?") ? "&" : "?"}t=${Date.now()}`;
    const url = this._hass.hassUrl?.(picture + stamp) ?? picture + stamp;
    let size = null;
    try {
      size = await new Promise((resolve, reject) => {
        const probe = new Image();
        probe.onload = () => resolve([probe.naturalWidth, probe.naturalHeight]);
        probe.onerror = () => reject(new Error("picture failed to load"));
        probe.src = url;
      });
    } catch {
      // The picture on screen stays, and its age says it is no longer fresh.
      this._failed = true;
      return;
    }
    this._failed = false;
    // Another camera was picked while this one loaded.
    if (this._current()?.entity !== camera.entity || !img) return;
    img.src = url;
    img.alt = this._name(camera);
    img.style.visibility = "";
    // The picture's own shape, so the card fits the camera rather than 16:9.
    const wrap = this.shadowRoot.getElementById("img-wrap");
    if (wrap && size[0] > 0 && size[1] > 0) wrap.style.aspectRatio = `${size[0]} / ${size[1]}`;
    const taken = Date.parse(this._state(camera)?.state);
    this._shown = {
      entity: camera.entity,
      at: camera.entity.startsWith("image.") && Number.isFinite(taken) ? taken : Date.now(),
    };
  }

  // ── picking ────────────────────────────────────────────────────────────

  // Rebuilt only when the chips change: `set hass` arrives for every state
  // change in Home Assistant, and a rebuild drops a focused chip's focus.
  _renderChips() {
    const picker = this.shadowRoot.getElementById("picker");
    if (!picker) return;
    const cameras = this._cameras();
    const current = this._current();
    const names = cameras.map((camera) => this._name(camera));
    const key = JSON.stringify([names, cameras.indexOf(current)]);
    if (key === this._chipsKey) return;
    this._chipsKey = key;

    picker.innerHTML = "";
    if (cameras.length < 2) return;
    cameras.forEach((camera, index) => {
      const chip = document.createElement("button");
      chip.className = `chip${camera === current ? " active" : ""}`;
      chip.setAttribute("aria-pressed", String(camera === current));
      chip.textContent = names[index];
      chip.addEventListener("click", () => {
        this._picked = index;
        this._failed = false;
        this._update();
      });
      picker.appendChild(chip);
    });
  }

  // ── readings ───────────────────────────────────────────────────────────

  _updateHeader() {
    const camera = this._current();
    const count = this._cameras().length;
    this.shadowRoot.getElementById("title").textContent = this._config.title;
    this.shadowRoot.getElementById("sub").textContent = !camera
      ? "No camera configured"
      : count > 1 ? `${this._name(camera)} · ${count} cameras` : this._name(camera);

    const badge = this.shadowRoot.getElementById("badge");
    const down = camera !== null && !this._picture(camera);
    badge.toggleAttribute("hidden", !down);
    badge.textContent = down ? "Unavailable" : "";
  }

  _updateOverlay() {
    const overlay = this.shadowRoot.getElementById("overlay");
    const wrap = this.shadowRoot.getElementById("img-wrap");
    const camera = this._current();
    const shown = this._shown;
    wrap.classList.toggle("has-image", shown !== null);
    if (shown) {
      wrap.setAttribute("role", "button");
      wrap.setAttribute("tabindex", "0");
      wrap.setAttribute("aria-label", `${this._name(camera)}: more information`);
    } else {
      for (const name of ["role", "tabindex", "aria-label"]) wrap.removeAttribute(name);
    }

    const pills = [];
    if (shown) {
      // Late once two refreshes have gone by with no picture: a failing camera.
      const late = !camera.entity.startsWith("image.")
        && Date.now() - shown.at > 2 * this._config.refresh_interval * 1000;
      pills.push(`<span class="pill${late ? " late" : ""}"><span class="dot"></span>${safe(ageText(shown.at))}</span>`);
    }
    const link = camera?.url
      ? `<a class="pill" href="${safe(camera.url)}" target="_blank" rel="noopener noreferrer">Open ↗</a>`
      : "";
    const markup = pills.length || link
      ? `<div class="overlay-left">${pills.join("")}</div>${link}`
      : "";
    // Rewritten only when it changes, so a focused link keeps its focus.
    if (markup !== this._overlayMarkup) {
      this._overlayMarkup = markup;
      overlay.innerHTML = markup;
    }
  }

  _updateEmpty() {
    const empty = this.shadowRoot.getElementById("empty");
    const text = this.shadowRoot.getElementById("empty-text");
    const hint = this.shadowRoot.getElementById("empty-hint");
    const camera = this._current();
    const show = !this._shown && !(this._loading && !this._failed);
    empty.classList.toggle("active", show);
    if (!show) return;
    if (!camera) {
      text.textContent = "No camera configured";
      hint.textContent = "Edit the card and add a camera or image entity.";
    } else if (!this._state(camera)) {
      text.textContent = "Entity not found";
      hint.textContent = camera.entity;
    } else if (!this._picture(camera)) {
      text.textContent = "Camera unavailable";
      hint.textContent = "Its picture returns when the entity does.";
    } else if (this._failed) {
      text.textContent = "Could not load the picture";
      hint.textContent = "Trying again shortly.";
    } else {
      text.textContent = "";
      hint.textContent = "";
    }
  }

  _moreInfo() {
    if (!this._shown) return;
    const event = new Event("hass-action", { bubbles: true, composed: true });
    event.detail = {
      config: { entity: this._shown.entity, tap_action: { action: "more-info" } },
      action: "tap",
    };
    this.dispatchEvent(event);
  }

  getCardSize() { return 5; }

  static getConfigForm() {
    return standaloneForm([
      { name: "title", label: "Title", default: DEFAULT_TITLE, selector: { text: {} } },
      {
        name: "cameras",
        label: "Cameras",
        helper: "With two or more, chips under the picture choose between them.",
        selector: {
          object: {
            multiple: true,
            label_field: "entity",
            fields: {
              entity: {
                label: "Camera or image entity",
                required: true,
                selector: { entity: { domain: ["camera", "image"] } },
              },
              name: { label: "Name (default: the entity's)", selector: { text: {} } },
              url: { label: "Link shown over the picture", selector: { text: { type: "url" } } },
            },
          },
        },
      },
      {
        name: "refresh_interval",
        label: "Refresh interval",
        helper: "How often a camera is asked for a new picture. An image entity "
          + "updates when its picture does.",
        default: DEFAULT_REFRESH_SECONDS,
        selector: {
          number: { min: MIN_REFRESH_SECONDS, max: 3600, mode: "box", unit_of_measurement: "s" },
        },
      },
    ]);
  }

  // The first camera the instance has, so the card picker previews a picture.
  static getStubConfig(hass) {
    const entity = Object.keys(hass?.states ?? {}).find((id) => id.startsWith("camera."));
    return { cameras: entity ? [{ entity }] : [] };
  }
}

// Guarded, as every card is: a second copy of the module must not throw.
if (!customElements.get("nina-site-camera-card")) {
  customElements.define("nina-site-camera-card", NinaSiteCameraCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-site-camera-card",
  name: "N.I.N.A. Site Camera",
  description: "A pier, all-sky or observatory camera, from any camera or image entity.",
  preview: false,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-SITE-CAMERA-CARD %c v${VERSION} `,
  "background:#12121e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px;border:1px solid #7b8de8",
  "background:#7b8de8;color:#12121e;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

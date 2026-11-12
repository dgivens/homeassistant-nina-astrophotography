/**
 * Collapsible sections, shared by every card: a click, Enter or Space on a
 * heading folds what it heads, and the browser remembers it, so hiding a
 * section needs no dashboard edit.
 *
 * A card builds each heading with `heading()`, or `attrs()` and `CHEVRON` where
 * its markup places the chevron. Its header, `attrs("card")` and ending in
 * `CHEVRON`, folds the whole body, and `banner()` follows it to say so. A
 * heading is a button, whose content a screen reader flattens, so a control
 * goes beside it as a sibling, between the header and the banner. A card
 * that re-renders its markup leaves a folded section's body out, so nothing in
 * it is drawn; one that builds its markup once hides the body itself from
 * `onToggle`, which runs after every toggle.
 *
 * Remembered per browser, in `localStorage`, under the card, the rig and the
 * section. Each copy of a card reads it once, when its rig is set, and then
 * keeps its own: a copy on another view never changes under its own markup.
 * Where storage is refused, as in a private window, a fold lasts until the
 * page reloads.
 *
 * Not a card, so not in `frontend.py`'s `CARD_FILENAMES`.
 */

import { DEFAULT_PREFIX } from "./nina-card-config.js";

// `[hidden]` loses to any `display` rule a card sets, so it is restated. A
// section heading's layout is under `:where`, so a card's own rule for one wins.
// A heading's cue and the card's banner show only while folded.
export const COLLAPSE_STYLE = `
  [hidden] { display: none !important; }
  [data-fold] { cursor: pointer; user-select: none; -webkit-user-select: none; }
  [data-fold]:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; border-radius: 4px; }
  :where([data-fold]:not(.header)) { display: flex; align-items: center; gap: 6px; }
  [data-fold]:not(.header):hover { color: var(--text); }
  .fold-chevron {
    display: inline-block; flex-shrink: 0; margin-left: auto;
    width: 5px; height: 5px;
    border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor;
    color: var(--muted); opacity: 0.8;
    transform: translateY(-2px) rotate(45deg);
    transition: transform 0.15s;
  }
  .header > .fold-chevron { width: 7px; height: 7px; margin-right: 2px; }
  [aria-expanded="false"] .fold-chevron { transform: rotate(-45deg); }
  .fold-cue { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; margin-left: auto; }
  .fold-cue.warn { background: var(--warn); box-shadow: 0 0 5px var(--warn); }
  .fold-cue.danger { background: var(--danger); box-shadow: 0 0 5px var(--danger); }
  [aria-expanded="true"] > .fold-cue { display: none; }
  [aria-expanded="false"] > .fold-cue + .fold-chevron { margin-left: 0; }
  .fold-banner {
    display: none; padding: 4px 16px;
    font-size: 0.6rem; font-weight: 700; letter-spacing: .6px; text-transform: uppercase;
    color: var(--muted); background: color-mix(in srgb, var(--ink) 4%, transparent);
    border-bottom: 1px solid color-mix(in srgb, var(--ink) 10%, transparent);
  }
  .fold-banner.warn { color: var(--warn); }
  .fold-banner.danger { color: var(--danger); }
  .header[aria-expanded="false"] ~ .fold-banner { display: block; }
`;

export const CHEVRON = `<span class="fold-chevron" aria-hidden="true"></span>`;
const LEVEL = { warn: "A warning", danger: "A danger" };

const memory = new Map();

function stored(key) {
  try {
    const value = globalThis.localStorage?.getItem(key);
    if (value !== null && value !== undefined) return value === "1";
  } catch {
    // Storage refused: fall through to memory.
  }
  return memory.get(key) ?? false;
}

function store(key, folded) {
  memory.set(key, folded);
  try {
    if (folded) globalThis.localStorage?.setItem(key, "1");
    else globalThis.localStorage?.removeItem(key);
  } catch {
    // Storage refused: memory holds it for this page.
  }
}

// A click on a control inside a heading is the control's, not the heading's.
const CONTROL = "button, a, input, select, textarea";

export class Collapse {
  /**
   * @param {HTMLElement} card  the card, whose shadow root is already attached
   * @param {string} name       the card's element name
   * @param {(section: string, open: boolean) => void} onToggle
   */
  constructor(card, name, onToggle) {
    this._root = card.shadowRoot;
    this._name = name;
    this._onToggle = onToggle;
    this._rig = null;
    this._folded = new Map();
    this._root.addEventListener("click", (event) => this._handle(event, false));
    this._root.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && !event.repeat) this._handle(event, true);
    });
  }

  /** Remembers folds under the configured rig, and rereads them for a new one. */
  scope(config) {
    const rig = config.device_id || config.prefix || DEFAULT_PREFIX;
    if (rig === this._rig) return;
    this._rig = rig;
    this._folded.clear();
  }

  open(section) {
    if (!this._folded.has(section)) this._folded.set(section, stored(this._key(section)));
    return !this._folded.get(section);
  }

  set(section, open) {
    this._folded.set(section, !open);
    store(this._key(section), !open);
  }

  /** Fold `sections` on this copy only, remembering nothing. */
  preset(...sections) {
    for (const section of sections) this._folded.set(section, true);
  }

  /**
   * A section's heading. `level` — `"warn"`, `"danger"` or null — is what the
   * section would show, cued on the heading while it is folded.
   */
  heading(section, cls, label, level = null) {
    return `<div class="${cls}"${this.attrs(section)}>${label}${cue(level)}${CHEVRON}</div>`;
  }

  /** The attributes that make an element the heading of `section`; `"card"` for the header. */
  attrs(section) {
    return ` data-fold="${section}" role="button" tabindex="0" aria-expanded="${this.open(section)}"`;
  }

  /**
   * The strip under the header saying the card is folded, and what a section
   * it hides warns of. It shows only while the card is folded, and a tap on it
   * unfolds the card; the header is what a keyboard or screen reader uses.
   */
  banner(level = null) {
    const inside = level ? ` · ${LEVEL[level].toLowerCase()} inside` : "";
    return `<div class="fold-banner${level ? ` ${level}` : ""}" data-fold="card" aria-hidden="true">Collapsed${inside} · tap to expand</div>`;
  }

  /** Hide or show the elements with `ids`, for a card that builds its markup once. */
  hide(ids, hidden) {
    for (const id of ids) this._root.getElementById(id)?.toggleAttribute("hidden", hidden);
  }

  /** Sets every heading's state from the folds, for markup built under another rig. */
  sync() {
    for (const head of this._root.querySelectorAll("[data-fold]")) {
      head.setAttribute("aria-expanded", String(this.open(head.dataset.fold)));
    }
  }

  /** Runs `render`, and gives focus back to the heading that had it. */
  keepFocus(render) {
    const focused = this._root.activeElement?.dataset?.fold;
    render();
    if (focused && !this._root.activeElement) {
      // A heading keeps focus after a tap, so scrolling here would pull the
      // page back to the card on every update.
      this._root.querySelector(`[data-fold="${focused}"]`)?.focus({ preventScroll: true });
    }
  }

  _key(section) {
    return `nina-collapse:${this._name}:${this._rig}:${section}`;
  }

  _handle(event, keyboard) {
    const head = event.target?.closest?.("[data-fold]");
    if (!head) return;
    if (keyboard && event.target !== head) return;
    const control = event.target.closest(CONTROL);
    if (control && head.contains(control)) return;
    // Space would scroll the page, and Enter submit a surrounding form.
    if (keyboard) event.preventDefault();

    const section = head.dataset.fold;
    const open = !this.open(section);
    this.set(section, open);
    head.setAttribute("aria-expanded", String(open));
    this.keepFocus(() => this._onToggle(section, open));
  }
}

/** The more severe of `"warn"`, `"danger"` and null, for a heading's cue. */
export function worst(levels) {
  return levels.includes("danger") ? "danger" : levels.includes("warn") ? "warn" : null;
}

function cue(level) {
  return level ? `<span class="fold-cue ${level}" role="img" aria-label="${LEVEL[level]} in this section"></span>` : "";
}

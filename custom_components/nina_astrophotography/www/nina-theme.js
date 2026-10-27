/**
 * The colours every card draws in, on a dark theme or a light one.
 *
 * Text comes from the theme, falling back to white for a page with none. The
 * accents were picked for a dark card, where they are pale; on white three of
 * them fall to 2:1, so a light theme takes darker ones that hold 4.5:1. A
 * card's CSS reads all of them as variables, and its canvas, which cannot,
 * asks `palette()` for the same values.
 *
 * Not a card, so not in `frontend.py`'s `CARD_FILENAMES`.
 */

const DARK = {
  accent: "#7b8de8", accent2: "#5bcfcf", warn: "#f4a261", danger: "#e76f51", success: "#57cc99",
};
const LIGHT = {
  accent: "#4b64e0", accent2: "#247c7c", warn: "#b2560c", danger: "#ca3f1c", success: "#277f59",
};

const declare = (colours) =>
  Object.entries(colours).map(([name, value]) => `--${name}: ${value};`).join(" ");

/**
 * The `:host` palette. `--ink` is the text colour at full strength, for the
 * washes and tracks a card mixes from it with `color-mix()` so they read on
 * either background.
 */
export const THEME = `
  :host {
    --text: var(--primary-text-color, rgba(255,255,255,0.92));
    --muted: var(--secondary-text-color, rgba(255,255,255,0.45));
    --ink: var(--primary-text-color, #fff);
    ${declare(DARK)}
  }
  :host([light]) { ${declare(LIGHT)} }
`;

/**
 * Declarations for something drawn over an image, which is dark whatever the
 * theme: the dark palette, whatever the card around it uses.
 */
export const ON_IMAGE = `
  --text: rgba(255,255,255,0.92);
  --muted: rgba(255,255,255,0.45);
  --ink: #fff;
  ${declare(DARK)}
  color: var(--text);
`;

function rgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

let probe;

// The theme's text colour as `[r, g, b]`, or white with no theme. Read off the
// variable, which the element inherits before its own styles are in place. A
// canvas context normalises whatever form the theme wrote it in to `#rrggbb`,
// or to `rgba()` when it is translucent.
function ink(element) {
  const value = getComputedStyle(element).getPropertyValue("--primary-text-color").trim();
  if (!value) return [255, 255, 255];
  probe ??= document.createElement("canvas").getContext("2d");
  probe.fillStyle = "#fff";
  probe.fillStyle = value;
  const colour = probe.fillStyle;
  if (colour.startsWith("#")) return rgb(colour);
  return colour.match(/[\d.]+/g).slice(0, 3).map(Number);
}

// Dark text means a light card.
const isLight = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b < 128;

/**
 * The colours for `element`'s canvas: each accent as hex, `text` as hex, and
 * `ink(alpha)` and `tint(name, alpha)` as `rgba()`. Read when drawing, since
 * the theme can change under a card.
 */
export function palette(element) {
  const text = ink(element);
  const light = isLight(text);
  const colours = light ? LIGHT : DARK;
  const rgba = ([r, g, b], alpha) => `rgba(${r},${g},${b},${alpha})`;
  return {
    ...colours,
    light,
    text: `#${text.map((c) => Math.round(c).toString(16).padStart(2, "0")).join("")}`,
    ink: (alpha) => rgba(text, alpha),
    tint: (name, alpha) => rgba(rgb(colours[name]), alpha),
  };
}

/**
 * Mark `element` `light` when its theme is, which swaps the CSS accents.
 * True when that changed, so a card that draws only on new data knows to
 * draw again.
 */
export function applyTheme(element) {
  const light = palette(element).light;
  if (light === element.hasAttribute("light")) return false;
  element.toggleAttribute("light", light);
  return true;
}

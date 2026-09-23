/**
 * Enough of a DOM to run a card under node, with a canvas that records rather
 * than draws.
 *
 * Every card is a custom element over a shadow root and, for three of them, a
 * 2D canvas — none of which node has. Installing stubs lets the card's own
 * render path execute, so a refactor can be diffed call for call against the
 * file it replaced.
 *
 * What comes back is a log, not a picture: it proves two versions agree, not
 * that either looks right. `render.html` is what shows the pixels.
 */

/** Numbers to six places, so a float that moves shows up and noise does not. */
const fmt = (args) =>
  args.map((v) => (typeof v === "number" ? v.toFixed(6) : String(v))).join(",");

function recorder(log) {
  const state = {};
  const gradient = { addColorStop() {} };
  const target = {
    beginPath: () => log.push("beginPath"),
    closePath: () => log.push("closePath"),
    moveTo: (...a) => log.push(`moveTo ${fmt(a)}`),
    lineTo: (...a) => log.push(`lineTo ${fmt(a)}`),
    arc: (...a) => log.push(`arc ${fmt(a)}`),
    ellipse: (...a) => log.push(`ellipse ${fmt(a)}`),
    rect: (...a) => log.push(`rect ${fmt(a)}`),
    quadraticCurveTo: (...a) => log.push(`quadraticCurveTo ${fmt(a)}`),
    bezierCurveTo: (...a) => log.push(`bezierCurveTo ${fmt(a)}`),
    fill: () => log.push("fill"),
    stroke: () => log.push("stroke"),
    save: () => log.push("save"),
    restore: () => log.push("restore"),
    clip: () => log.push("clip"),
    clearRect: (...a) => log.push(`clearRect ${fmt(a)}`),
    fillRect: (...a) => log.push(`fillRect ${fmt(a)}`),
    strokeRect: (...a) => log.push(`strokeRect ${fmt(a)}`),
    translate: (...a) => log.push(`translate ${fmt(a)}`),
    rotate: (...a) => log.push(`rotate ${fmt(a)}`),
    scale: (...a) => log.push(`scale ${fmt(a)}`),
    fillText: (...a) => log.push(`fillText ${a[0]} ${fmt(a.slice(1))}`),
    strokeText: (...a) => log.push(`strokeText ${a[0]} ${fmt(a.slice(1))}`),
    setLineDash: (a) => log.push(`setLineDash ${JSON.stringify(a)}`),
    measureText: (t) => ({ width: String(t).length * 6 }),
    createRadialGradient: () => gradient,
    createLinearGradient: () => gradient,
  };
  // Assignments are drawing too — `fillStyle`, `lineWidth`, `font` — so they
  // are logged, and read back so the card can compare against what it set.
  return new Proxy(target, {
    get: (t, k) => (k in t ? t[k] : state[k]),
    set(t, k, v) {
      state[k] = v;
      log.push(`set ${String(k)} = ${v}`);
      return true;
    },
  });
}

/**
 * Install the stubs and return what the runner needs back.
 *
 * `Math.random` and `Date.now` are pinned: the sky map twinkles its stars and
 * pulses the meridian off both, so two runs of the same card disagree on a few
 * dozen lines unless they are held still.
 *
 * @param {object} [options]
 * @param {number} [options.width]   the canvas size a card reads off the layout
 * @param {number} [options.dpr]     `window.devicePixelRatio`
 * @returns {{log: string[], element: () => Function, html: () => string,
 *            frame: () => void}}
 */
export function install({ width = 320, height = 320, dpr = 2 } = {}) {
  const log = [];
  let defined = null;
  let html = "";
  const queued = new Map();
  let handle = 0;

  const canvas = {
    width: 0,
    height: 0,
    offsetWidth: width,
    offsetHeight: height,
    style: {},
    getContext: () => recorder(log),
    addEventListener() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width, height }),
  };
  const nodes = new Map();
  const shadow = {
    set innerHTML(value) {
      html = value;
    },
    get innerHTML() {
      return html;
    },
    // A canvas is whatever the card's own markup declares as one, rather than
    // a list of ids to keep in step with six cards.
    getElementById(id) {
      if (new RegExp(`<canvas[^>]*\\bid="${id}"`).test(html)) return canvas;
      if (!nodes.has(id)) {
        nodes.set(id, { textContent: "", innerHTML: "", style: {}, addEventListener() {} });
      }
      return nodes.get(id);
    },
    querySelector: () => null,
    querySelectorAll: () => [],
  };

  globalThis.HTMLElement = class {
    attachShadow() {
      this.shadowRoot = shadow;
      return shadow;
    }
  };
  globalThis.customElements = {
    get: () => undefined,
    define: (name, cls) => {
      defined = cls;
    },
  };
  globalThis.window = { devicePixelRatio: dpr, customCards: [] };
  globalThis.document = { createElement: () => ({ style: {}, addEventListener() {} }) };
  // Held rather than run: node fires no frames, so the runner decides when the
  // ones a render queued go off. Kept as a list against its handles, and not as
  // one slot: a render that queues two frames would otherwise record only the
  // second, and a card cancelling a stale handle would wipe a live callback —
  // both of which read as "the card stopped drawing" in a diff.
  globalThis.requestAnimationFrame = (callback) => {
    queued.set(++handle, callback);
    return handle;
  };
  globalThis.cancelAnimationFrame = (id) => {
    queued.delete(id);
  };
  globalThis.ResizeObserver = undefined;

  let seed = 1;
  Math.random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  Date.now = () => 1789000000000;

  // Drained before the callbacks run, so a frame one of them queues for its own
  // next tick is left pending rather than fired in the same pass — which is
  // what an animating card expects, and what stops it looping here.
  const frame = () => {
    const pending = [...queued.values()];
    queued.clear();
    for (const callback of pending) callback();
  };

  return { log, element: () => defined, html: () => html, frame };
}

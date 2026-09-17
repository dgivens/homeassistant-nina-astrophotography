/**
 * N.I.N.A. Autofocus Card
 * Draws the last autofocus run as N.I.N.A.'s own chart draws it: the measured
 * V with its error bars, the fitted curves over it, the minima each fit found,
 * and where the focuser was actually left.
 *
 * Installation:
 *   1. Copy to /config/www/nina-autofocus-card.js
 *   2. Add resource: /local/nina-autofocus-card.js (JavaScript Module)
 *   3. Add card:
 *        type: custom:nina-autofocus-card
 *        prefix: n_i_n_a        # the slugified instance name your entities carry
 *        temperature_delta: 1   # °C of drift since the run worth flagging
 */

const VERSION = "2.0.0";

// 2.0 entity ids carry the instance name, so the card is told the prefix
// rather than guessing it: it is the instance name from the config flow,
// slugified — `N.I.N.A.` by default. Set `prefix:` in the card config for a
// renamed instance, or for the second rig.
//
// Repeated in each card on purpose: the cards are copied into `www/` one file
// at a time, and a shared module would break a card whose neighbour was missed.
const DEFAULT_PREFIX = "n_i_n_a";

// How far the focuser temperature may drift from the run's before the card
// says so. There is no right answer to publish here — it belongs to the
// sequence's own refocus trigger — so this is only a default to override.
const DEFAULT_TEMPERATURE_DELTA = 1.0;

const CURVE = "#5bcfcf";      // the measured sweep
const FIT = "#7b8de8";        // the fitted curve, and the minimum it found
const TREND = "#f4a261";      // the trend lines, and where they cross
const FINAL = "#57cc99";      // where the focuser was left
const DANGER = "#e76f51";

// A reading Home Assistant has no value for is not a number to print.
function shown(value) {
  return value === null || value === undefined || value === "—"
    || value === "unknown" || value === "unavailable" ? "—" : value;
}

function fixed(value, places) {
  return Number.isFinite(value) ? value.toFixed(places) : "—";
}

// The wire names a fit and its minimum in .NET's own casing: `LeftTrend`,
// `TrendLineIntersection`, `QuadraticMinimum`. Split it for a human.
function pretty(name) {
  const words = String(name).replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// A trend line is fitted to one side of the V and a curve to the whole of it;
// they are drawn differently, and each minimum takes the colour of the fit
// that found it — the wire names the intersection after that fit.
function isTrend(name) {
  return /trend/i.test(String(name));
}

// `coefficients` are highest power first, as the mapper parses them out of
// N.I.N.A.'s equation string: [a, b, c] is a·x² + b·x + c. A fit whose
// equation was not a polynomial — a hyperbola, a Gaussian — arrives with
// `coefficients: null` and simply is not drawn.
function evaluate(coefficients, x) {
  return coefficients.reduce((total, coefficient) => total * x + coefficient, 0);
}

function ago(iso) {
  const at = Date.parse(iso);
  if (!Number.isFinite(at)) return null;
  const seconds = Math.max(0, (Date.now() - at) / 1000);
  if (seconds < 90) return `${Math.round(seconds)} s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 129600) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return "—";
  if (seconds < 90) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes} m ${String(Math.round(seconds % 60)).padStart(2, "0")} s`;
}

const STYLE = `
  :host {
    /* A custom element is inline by default, and a ResizeObserver watching an
       inline box does not report the card getting wider — which is what
       redraws the canvas. */
    display: block;
    --card-bg: var(--ha-card-background, var(--card-background-color, #1c1c2e));
    --card-border: var(--divider-color, rgba(255,255,255,0.1));
    --muted: rgba(255,255,255,0.45);
    --text: rgba(255,255,255,0.92);
    font-family: var(--primary-font-family, Roboto, sans-serif);
  }
  ha-card {
    background: var(--card-bg);
    color: var(--text);
    border: 1px solid var(--card-border);
    border-radius: 16px;
    overflow: hidden;
    padding: 0;
  }
  .header {
    display: flex; align-items: center; gap: 10px;
    padding: 14px 18px 10px;
    border-bottom: 1px solid var(--card-border);
    background: rgba(91,207,207,0.08);
  }
  .header .title { font-size: 1.05rem; font-weight: 600; }
  .header .subtitle { font-size: 0.72rem; color: var(--muted); margin-top: 1px; }
  .body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 14px; }

  .banner {
    display: flex; align-items: center; gap: 10px;
    border-radius: 10px; padding: 10px 12px;
    background: rgba(231,111,81,0.12);
    border: 1px solid rgba(231,111,81,0.45);
    font-size: 0.78rem;
  }
  .banner .what { font-weight: 700; }
  .banner .why { color: var(--muted); font-size: 0.72rem; }

  .stat-row { display: flex; flex-wrap: wrap; gap: 8px; }
  .stat-box {
    flex: 1; min-width: 92px; box-sizing: border-box;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 10px;
    padding: 10px 12px;
    display: flex; flex-direction: column; gap: 2px;
  }
  .stat-box .label { font-size: 0.6rem; font-weight: 600; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }
  .stat-box .value { font-size: 1.05rem; font-weight: 700; }
  .stat-box .value .unit { font-size: 0.7rem; font-weight: 400; color: var(--muted); }
  .stat-box .sub { font-size: 0.65rem; color: var(--muted); }
  .stat-box.drifted { border-color: rgba(244,162,97,0.45); }

  .chart-section { display: flex; flex-direction: column; gap: 4px; }
  .chart-label { font-size: 0.62rem; font-weight: 700; letter-spacing: .8px; text-transform: uppercase; color: var(--muted); }
  /* The height is set here and not on the element: a canvas with only a
     height attribute takes its displayed height from the intrinsic ratio, so
     each redraw at a wider card would measure taller and grow again. */
  canvas { width: 100%; height: 200px; border-radius: 6px; display: block; }

  .legend { display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 0.68rem; }
  .legend .item { display: flex; align-items: center; gap: 6px; }
  .legend .swatch { width: 14px; height: 0; border-top-width: 2px; border-top-style: solid; flex-shrink: 0; }
  .legend .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .legend .diamond { width: 8px; height: 8px; transform: rotate(45deg); flex-shrink: 0; }
  .legend .reading { color: var(--muted); }

  .meta { display: flex; flex-wrap: wrap; gap: 4px 6px; }
  .chip {
    display: flex; align-items: center; gap: 5px;
    border-radius: 20px; padding: 4px 10px;
    font-size: 0.68rem;
    background: rgba(255,255,255,0.05);
    border: 1px solid var(--card-border);
  }
  .chip .k { color: var(--muted); }

  .no-data {
    text-align: center; padding: 28px 16px;
    color: var(--muted); font-size: 0.85rem;
  }
  .no-data .icon { font-size: 2rem; margin-bottom: 8px; }
`;

class NinaAutofocusCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._signature = null;
  }

  setConfig(config) {
    this._config = config || {};
    this._prefix = this._config.prefix || DEFAULT_PREFIX;
    this._temperatureDelta = Number.isFinite(this._config.temperature_delta)
      ? Math.abs(this._config.temperature_delta)
      : DEFAULT_TEMPERATURE_DELTA;
    this._signature = null;
  }

  connectedCallback() {
    // The card only re-renders when the run changes, so a resize would
    // otherwise leave the canvas at its old width until the next autofocus.
    if (typeof ResizeObserver === "undefined" || this._observer) return;
    this._observer = new ResizeObserver(() => this._draw());
    this._observer.observe(this);
  }

  disconnectedCallback() {
    this._observer?.disconnect();
    this._observer = undefined;
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _state(id, fallback = null) {
    const entity = this._hass?.states?.[id];
    return entity ? entity.state : fallback;
  }

  _attr(id, attribute, fallback = null) {
    const entity = this._hass?.states?.[id];
    return entity ? (entity.attributes[attribute] ?? fallback) : fallback;
  }

  _number(id) {
    const value = parseFloat(this._state(id));
    return Number.isFinite(value) ? value : null;
  }

  _read() {
    const prefix = this._prefix;
    const run = `sensor.${prefix}_focuser_last_autofocus`;
    const curve = this._attr(run, "curve", []) || [];
    const fits = this._attr(run, "fits", []) || [];
    const minima = this._attr(run, "minima", []) || [];

    // `autofocus_fitted_hfr` and `autofocus_r2` are diagnostic and ship
    // disabled, so both are taken from the attributes instead: the fitted HFR
    // is the mean of the minima, which is how N.I.N.A. computes the point it
    // moves to, and the sensor's R² is the worst of the run's fits.
    const fitted = minima.map((minimum) => minimum.value).filter(Number.isFinite);
    const scored = fits.filter((fit) => Number.isFinite(fit.r_squared));
    const worst = scored.reduce(
      (lowest, fit) => (lowest === null || fit.r_squared < lowest.r_squared ? fit : lowest),
      null,
    );

    const temperature = this._number(`sensor.${prefix}_focuser_temperature`);
    const at = this._number(`sensor.${prefix}_focuser_autofocus_temperature`);

    return {
      timestamp: this._state(run),
      curve, fits, minima,
      method: this._attr(run, "method"),
      fitting: this._attr(run, "fitting"),
      autofocuser: this._attr(run, "autofocuser"),
      detector: this._attr(run, "star_detector"),
      measured: this._attr(run, "measured_points"),
      failed: this._state(`binary_sensor.${prefix}_focuser_autofocus_failed`) === "on",
      position: this._number(`sensor.${prefix}_focuser_autofocus_position`),
      hfr: this._number(`sensor.${prefix}_focuser_autofocus_hfr`),
      fittedHfr: fitted.length
        ? fitted.reduce((total, value) => total + value, 0) / fitted.length
        : null,
      // Named, because the sensor's R² is the worst of several fits and the
      // number means nothing without knowing which one it came from. The
      // sensor itself is the fallback for a run whose equations did not parse.
      worstSquare: worst ? worst.r_squared : this._number(`sensor.${prefix}_focuser_autofocus_r2`),
      worstFit: worst ? pretty(worst.name) : null,
      startPosition: this._number(`sensor.${prefix}_focuser_autofocus_starting_position`),
      startHfr: this._number(`sensor.${prefix}_focuser_autofocus_starting_hfr`),
      filter: this._state(`sensor.${prefix}_focuser_autofocus_filter`),
      duration: this._number(`sensor.${prefix}_focuser_autofocus_duration`),
      temperature: at,
      nowTemperature: temperature,
      nowPosition: this._number(`sensor.${prefix}_focuser_position`),
      drift: Number.isFinite(at) && Number.isFinite(temperature)
        ? temperature - at : null,
    };
  }

  _render() {
    if (!this._hass) return;
    const run = this._read();

    // Every entity here changes once per run, but `set hass` fires on every
    // state change in the whole of Home Assistant. Redrawing the canvas each
    // time buys nothing.
    const signature = JSON.stringify([
      run.timestamp, run.failed, run.position, run.nowPosition,
      run.nowTemperature, run.curve.length, run.fits.length,
    ]);
    if (signature === this._signature) return;
    this._signature = signature;
    this._run = run;

    this.shadowRoot.innerHTML = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <span style="font-size:1.3rem">🎯</span>
          <div>
            <div class="title">Autofocus</div>
            <div class="subtitle">${this._subtitle(run)}</div>
          </div>
        </div>
        <div class="body">${this._body(run)}</div>
      </ha-card>
    `;

    if (this._plottable(run)) requestAnimationFrame(() => this._draw());
  }

  _plottable(run) {
    return run.curve.some((point) => Number.isFinite(point.value));
  }

  _subtitle(run) {
    const when = run.timestamp ? ago(run.timestamp) : null;
    return [
      when,
      shown(run.filter) === "—" ? null : `${run.filter} filter`,
      Number.isFinite(run.temperature) ? `${fixed(run.temperature, 1)} °C` : null,
    ].filter(Boolean).join(" · ") || "No run reported";
  }

  _body(run) {
    if (!run.timestamp || shown(run.timestamp) === "—") {
      return `
        <div class="no-data">
          <div class="icon">🔭</div>
          <div>No autofocus run reported yet</div>
          <div style="font-size:0.72rem;margin-top:4px">The curve appears once N.I.N.A. finishes a run</div>
        </div>`;
    }

    const moved = Number.isFinite(run.position) && Number.isFinite(run.startPosition)
      ? run.position - run.startPosition : null;
    const away = Number.isFinite(run.nowPosition) && Number.isFinite(run.position)
      ? run.nowPosition - run.position : null;
    const drifted = Number.isFinite(run.drift)
      && Math.abs(run.drift) >= this._temperatureDelta;
    const blind = run.curve.filter((point) => !Number.isFinite(point.value)).length;

    return `
      ${run.failed ? `
        <div class="banner">
          <span style="font-size:1.1rem">⚠️</span>
          <div>
            <div class="what">This run did not take</div>
            <div class="why">The focuser stayed where it was, and frames since are as soft as they were before it.</div>
          </div>
        </div>` : ""}

      <div class="stat-row">
        <div class="stat-box">
          <div class="label">Focus position</div>
          <div class="value">${shown(run.position)} <span class="unit">steps</span></div>
          <div class="sub">${moved === null ? "&nbsp;"
            : `${moved >= 0 ? "+" : "−"}${Math.abs(moved)} from ${run.startPosition}`}</div>
        </div>
        <div class="stat-box">
          <div class="label">Best measured</div>
          <div class="value">${fixed(run.hfr, 2)} <span class="unit">px</span></div>
          <div class="sub">${Number.isFinite(run.fittedHfr)
            ? `Fitted ${fixed(run.fittedHfr, 2)} px` : "&nbsp;"}</div>
        </div>
        <div class="stat-box">
          <div class="label">Worst fit</div>
          <div class="value">${fixed(run.worstSquare, 3)} <span class="unit">R²</span></div>
          <div class="sub">${run.worstFit || "&nbsp;"}</div>
        </div>
      </div>

      ${Number.isFinite(run.nowTemperature) || away !== null ? `
        <div class="stat-row">
          ${Number.isFinite(run.nowTemperature) ? `
            <div class="stat-box ${drifted ? "drifted" : ""}">
              <div class="label">Temperature since</div>
              <div class="value">${run.drift === null ? "—"
                : `${run.drift >= 0 ? "+" : "−"}${fixed(Math.abs(run.drift), 1)}`} <span class="unit">°C</span></div>
              <div class="sub">${fixed(run.temperature, 1)} → ${fixed(run.nowTemperature, 1)} °C${drifted ? " · past your trigger" : ""}</div>
            </div>` : ""}
          ${away !== null ? `
            <div class="stat-box">
              <div class="label">Focuser now</div>
              <div class="value">${run.nowPosition} <span class="unit">steps</span></div>
              <div class="sub">${away === 0 ? "Where the run left it"
                : `${away > 0 ? "+" : "−"}${Math.abs(away)} steps since the run`}</div>
            </div>` : ""}
        </div>` : ""}

      ${this._plottable(run) ? `
        <div class="chart-section">
          <div class="chart-label">HFR against focuser position</div>
          <canvas id="curve"></canvas>
          ${this._legend(run)}
        </div>` : `
        <div class="no-data" style="padding:18px 16px">
          ${run.curve.length
            ? "Every position in this sweep measured nothing"
            : "This run reported no sweep to plot"}
        </div>`}

      <div class="meta">
        ${blind ? `<span class="chip" style="border-color:rgba(231,111,81,0.45)">
          <span class="k">Measured nothing</span> ${blind} ${blind === 1 ? "position" : "positions"}</span>` : ""}
        <span class="chip"><span class="k">Points</span> ${shown(run.measured)} of ${run.curve.length}</span>
        <span class="chip"><span class="k">Took</span> ${duration(run.duration)}</span>
        ${shown(run.method) === "—" ? "" : `<span class="chip"><span class="k">Method</span> ${run.method}</span>`}
        ${shown(run.fitting) === "—" ? "" : `<span class="chip"><span class="k">Fitting</span> ${run.fitting}</span>`}
        ${shown(run.autofocuser) === "—" ? "" : `<span class="chip"><span class="k">By</span> ${run.autofocuser}</span>`}
        ${shown(run.detector) === "—" ? "" : `<span class="chip"><span class="k">Stars</span> ${run.detector}</span>`}
      </div>
    `;
  }

  _legend(run) {
    const items = [
      `<div class="item"><span class="dot" style="background:${CURVE}"></span>
        <span>Measured</span><span class="reading">± spread across stars</span></div>`,
    ];
    for (const fit of run.fits) {
      // A fit whose equation is not a polynomial has no coefficients to
      // evaluate, so it is listed with its R² and said to be absent from the
      // chart rather than quietly missing from it.
      const drawn = Array.isArray(fit.coefficients) && fit.coefficients.length > 0;
      const colour = isTrend(fit.name) ? TREND : FIT;
      const dash = isTrend(fit.name) ? "dashed" : "solid";
      items.push(`<div class="item">
        <span class="swatch" style="border-top-color:${drawn ? colour : "var(--muted)"};border-top-style:${drawn ? dash : "dotted"}"></span>
        <span${drawn ? "" : ` style="color:var(--muted)"`}>${pretty(fit.name)}</span>
        <span class="reading">R² ${fixed(fit.r_squared, 3)}${drawn ? "" : " · not plotted"}</span></div>`);
    }
    // The axis stops at the lowest measured point, so a minimum below that is
    // drawn on the edge and has to say so here.
    const floor = Math.min(...run.curve
      .filter((point) => Number.isFinite(point.value))
      .map((point) => point.value - (point.error || 0)));
    for (const minimum of run.minima) {
      const colour = isTrend(minimum.name) ? TREND : FIT;
      const under = Number.isFinite(minimum.value) && minimum.value < floor;
      items.push(`<div class="item">
        <span class="diamond" style="background:${colour}"></span>
        <span>${pretty(minimum.name)}</span>
        <span class="reading">${shown(minimum.position)} · ${fixed(minimum.value, 2)} px${
          under ? " · below the axis" : ""}</span></div>`);
    }
    if (Number.isFinite(run.position)) {
      items.push(`<div class="item">
        <span class="swatch" style="border-top-color:${FINAL};border-top-style:dotted"></span>
        <span>Focus position</span><span class="reading">${run.position}</span></div>`);
    }
    return `<div class="legend">${items.join("")}</div>`;
  }

  _draw() {
    const run = this._run;
    const canvas = this.shadowRoot?.getElementById("curve");
    if (!canvas || !run || !this._plottable(run)) return;

    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth || 320;
    const H = canvas.offsetHeight || 200;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);

    const pad = { l: 34, r: 12, t: 12, b: 20 };
    const plotW = W - pad.l - pad.r;
    const plotH = H - pad.t - pad.b;

    // The x domain is the sweep's own range, nulls included: a position that
    // measured nothing was still visited, and dropping it would narrow the
    // range the run actually covered.
    const positions = run.curve.map((point) => point.position);
    if (Number.isFinite(run.position)) positions.push(run.position);
    const step = run.curve.length > 1
      ? (Math.max(...positions) - Math.min(...positions)) / (run.curve.length - 1)
      : 1;
    const xMin = Math.min(...positions) - step * 0.5;
    const xMax = Math.max(...positions) + step * 0.5;

    // The axis is the MEASURED points and nothing else. Two trend lines
    // extrapolate the V's wings until they cross, and that crossing sits well
    // below any star the optics can produce — letting it set the floor spends
    // most of the chart on empty sky and squashes the vertex, which is the
    // part worth reading. A minimum outside the axis is pinned to its edge.
    const measured = run.curve.filter((point) => Number.isFinite(point.value));
    const tops = measured.map((point) => point.value + (point.error || 0));
    const bottoms = measured.map((point) => point.value - (point.error || 0));
    const high = Math.max(...tops);
    const low = Math.min(...bottoms);
    const span = (high - low) || 1;
    const yMax = high + span * 0.08;
    const yMin = Math.max(0, low - span * 0.08);

    const xOf = (x) => pad.l + ((x - xMin) / (xMax - xMin)) * plotW;
    const yOf = (y) => pad.t + plotH - ((y - yMin) / (yMax - yMin)) * plotH;
    const inside = (y) => y >= yMin && y <= yMax;

    ctx.font = "9px sans-serif";
    ctx.textBaseline = "middle";

    // Grid and the HFR axis
    ctx.strokeStyle = "rgba(255,255,255,0.06)";
    ctx.fillStyle = "rgba(255,255,255,0.4)";
    ctx.lineWidth = 0.5;
    for (let line = 0; line <= 4; line++) {
      const value = yMin + ((yMax - yMin) * line) / 4;
      const y = yOf(value);
      ctx.beginPath();
      ctx.moveTo(pad.l, y);
      ctx.lineTo(W - pad.r, y);
      ctx.stroke();
      ctx.textAlign = "right";
      ctx.fillText(value.toFixed(1), pad.l - 5, y);
    }

    // The focuser-position axis
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let tick = 0; tick <= 3; tick++) {
      const value = xMin + ((xMax - xMin) * tick) / 3;
      ctx.fillText(Math.round(value).toString(), xOf(value), H - pad.b + 5);
    }
    ctx.textBaseline = "middle";

    // Positions the sweep visited and measured nothing at. Drawn first, so
    // the break they leave in the line lands on top of the marker.
    for (const point of run.curve) {
      if (Number.isFinite(point.value)) continue;
      const x = xOf(point.position);
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = `${DANGER}55`;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, H - pad.b);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = DANGER;
      ctx.textAlign = "center";
      ctx.fillText("✕", x, pad.t + plotH / 2);
    }

    // The fits, sampled across the sweep and broken wherever they leave the
    // chart — which is how a trend line stays a line over its own half of the
    // V rather than a spike out of the top of the frame.
    for (const fit of run.fits) {
      if (!Array.isArray(fit.coefficients) || !fit.coefficients.length) continue;
      ctx.strokeStyle = isTrend(fit.name) ? TREND : FIT;
      ctx.lineWidth = 1.4;
      ctx.setLineDash(isTrend(fit.name) ? [5, 4] : []);
      ctx.beginPath();
      let pen = false;
      for (let sample = 0; sample <= 160; sample++) {
        const x = xMin + ((xMax - xMin) * sample) / 160;
        const y = evaluate(fit.coefficients, x);
        if (!Number.isFinite(y) || !inside(y)) { pen = false; continue; }
        if (pen) ctx.lineTo(xOf(x), yOf(y));
        else { ctx.moveTo(xOf(x), yOf(y)); pen = true; }
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Error bars: the spread of HFR across the stars in that frame, not the
    // uncertainty on the V.
    ctx.strokeStyle = `${CURVE}77`;
    ctx.lineWidth = 1;
    for (const point of measured) {
      if (!Number.isFinite(point.error) || point.error === 0) continue;
      const x = xOf(point.position);
      const top = yOf(Math.min(point.value + point.error, yMax));
      const bottom = yOf(Math.max(point.value - point.error, yMin));
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bottom);
      ctx.moveTo(x - 3, top);
      ctx.lineTo(x + 3, top);
      ctx.moveTo(x - 3, bottom);
      ctx.lineTo(x + 3, bottom);
      ctx.stroke();
    }

    // The measured sweep. The pen lifts at a position that measured nothing
    // rather than drawing a chord across it — which on a V is a chord through
    // the very region focus lives in.
    ctx.strokeStyle = CURVE;
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    let pen = false;
    for (const point of run.curve) {
      if (!Number.isFinite(point.value)) { pen = false; continue; }
      const x = xOf(point.position);
      const y = yOf(point.value);
      if (pen) ctx.lineTo(x, y);
      else { ctx.moveTo(x, y); pen = true; }
    }
    ctx.stroke();

    const best = measured.reduce(
      (lowest, point) => (lowest === null || point.value < lowest.value ? point : lowest),
      null,
    );
    for (const point of measured) {
      ctx.beginPath();
      ctx.arc(xOf(point.position), yOf(point.value), point === best ? 3.5 : 2.4, 0, Math.PI * 2);
      ctx.fillStyle = point === best ? CURVE : `${CURVE}bb`;
      ctx.fill();
      if (point === best) {
        ctx.strokeStyle = "rgba(255,255,255,0.65)";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    }

    // Where the focuser was actually left, which is neither minimum: it is
    // their mean, rounded to a step.
    if (Number.isFinite(run.position)) {
      const x = xOf(run.position);
      ctx.strokeStyle = FINAL;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(x, pad.t);
      ctx.lineTo(x, H - pad.b);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    for (const minimum of run.minima) {
      if (!Number.isFinite(minimum.value) || !Number.isFinite(minimum.position)) continue;
      const x = xOf(minimum.position);
      const below = minimum.value < yMin;
      const y = yOf(Math.min(Math.max(minimum.value, yMin), yMax));
      ctx.fillStyle = isTrend(minimum.name) ? TREND : FIT;
      ctx.strokeStyle = "rgba(255,255,255,0.5)";
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      if (below || minimum.value > yMax) {
        // Off the chart: a chevron pointing the way it went, pinned to the
        // edge. The legend carries the value it actually has.
        const tip = below ? y : y - 1;
        const back = below ? -6 : 6;
        ctx.moveTo(x, tip);
        ctx.lineTo(x + 5, tip + back);
        ctx.lineTo(x - 5, tip + back);
      } else {
        ctx.moveTo(x, y - 4.5);
        ctx.lineTo(x + 4.5, y);
        ctx.lineTo(x, y + 4.5);
        ctx.lineTo(x - 4.5, y);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }

  getCardSize() { return 7; }

  static getStubConfig() { return {}; }
}

customElements.define("nina-autofocus-card", NinaAutofocusCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-autofocus-card",
  name: "N.I.N.A. Autofocus Card",
  description: "The last autofocus V-curve with its fits, minima and resulting focus position.",
  preview: true,
});

console.info(
  `%c NINA-AUTOFOCUS-CARD %c v${VERSION} `,
  "background:#5bcfcf;color:#1c1c2e;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px",
  "background:#1c1c2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

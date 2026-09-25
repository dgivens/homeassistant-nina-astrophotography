/**
 * N.I.N.A. Autofocus Card
 * Draws the last autofocus run as N.I.N.A.'s own chart draws it: the measured
 * V with its error bars, the fitted curves over it, the minima each fit found,
 * and where the focuser was actually left.
 *
 * Ships with the integration and registers itself as a dashboard resource —
 * nothing to copy or add under Resources. One rig needs no configuration at
 * all: the card finds its own focuser in the registry.
 *   type: custom:nina-autofocus-card
 *   device_id: abc123      # which rig, for two or more; any one of its devices
 *   temperature_delta: 2   # °C of drift since the run worth flagging
 *   prefix: n_i_n_a        # fallback only, for the entities that cannot resolve
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import { resolveEntities } from "./nina-entity-resolver.js";

const VERSION = "2.0.0";

// How far the focuser temperature may drift from the run's before the card
// says so. There is no right answer to publish here — it belongs to the
// sequence's own refocus trigger — so this is only a default to override, and
// the card names the number it used rather than claiming it is yours. Set
// above 1 °C deliberately: a site that swings ten degrees overnight would
// spend most of the night flagged, which teaches the operator to ignore it.
const DEFAULT_TEMPERATURE_DELTA = 2.0;

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

// Two decimals suit HFR in pixels; a contrast score spans thousandths and
// would read as "0.00" throughout.
function reading(value) {
  if (!Number.isFinite(value)) return "—";
  return value !== 0 && Math.abs(value) < 0.1 ? value.toFixed(4) : value.toFixed(2);
}

// Filter, fitting, autofocuser, star detector and fit names all come off the
// rig, and all of them land in `innerHTML`. A filter named with a tag would
// otherwise run as markup in the dashboard.
const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
function safe(value) {
  return String(value).replace(/[&<>"]/g, (character) => ESCAPES[character]);
}

// The wire names a fit and its minimum in .NET's own casing: `LeftTrend`,
// `TrendLineIntersection`, `QuadraticMinimum`. Split it for a human.
function pretty(name) {
  const words = safe(name).replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// The chart's y axis: the MEASURED points and nothing else, error bars
// included, with a little padding. Two trend lines extrapolate the V's wings
// until they cross, and that crossing sits well below any star the optics can
// produce — letting it set the floor spends most of the chart on empty sky and
// squashes the vertex, which is the part worth reading.
//
// One function because the legend and the chart have to agree on it: the
// legend is what says a minimum is below the axis, and the chart is what puts
// it there.
function axisRange(curve) {
  const measured = curve.filter((point) => Number.isFinite(point.value));
  const low = Math.min(...measured.map((point) => point.value - (point.error || 0)));
  const high = Math.max(...measured.map((point) => point.value + (point.error || 0)));
  const span = (high - low) || 1;
  return { measured, min: Math.max(0, low - span * 0.08), max: high + span * 0.08 };
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
  .stat-box.rejected { border-color: rgba(231,111,81,0.5); }

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
    // Coerced, because YAML hands back a string as readily as a number, and a
    // silent fallback to the default would look like the setting was ignored.
    const delta = Math.abs(Number(this._config.temperature_delta));
    this._temperatureDelta = Number.isFinite(delta) && delta > 0
      ? delta : DEFAULT_TEMPERATURE_DELTA;
    this._signature = null;
    // A new config may name a different rig: make the next `set hass` re-resolve.
    this._resolved = {};
    this._resolvedFrom = null;
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
    // The frontend replaces `hass.entities` only when the registry itself
    // changes, so this walks it on a rename, not on every state tick.
    // `hass.devices` needs no second memo key: every device change that alters
    // the map arrives with an entity-registry change too.
    if (hass.entities !== this._resolvedFrom) {
      this._resolvedFrom = hass.entities;
      this._resolved = resolveEntities(hass, this._config.device_id);
    }
    this._render();
  }

  // The resolved entity id for a `translation_key`, falling back to a prefixed
  // `slug` when there is nothing to resolve: an entity with no translation key,
  // a disabled one, or a rig the resolver cannot identify.
  //
  // `slug` is the entity-id suffix — the device name plus the entity name — so
  // it is not always the key, and on this card it usually is not: the focuser
  // device supplies the leading "focuser", which the autofocus keys do not
  // carry. Most reads below therefore pass one.
  _eid(domain, key, slug = key) {
    return this._resolved[`${domain}.${key}`] ?? `${domain}.${this._prefix}_${slug}`;
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

  _list(id, attribute) {
    const value = this._attr(id, attribute, []);
    return Array.isArray(value) ? value : [];
  }

  _read() {
    const run = this._eid("sensor", "autofocus_last_run", "focuser_last_autofocus");
    const curve = this._list(run, "curve");
    const fits = this._list(run, "fits");
    const minima = this._list(run, "minima");

    // A CONTRASTDETECTION run measures a contrast score and not star sizes, so
    // nothing it produces is in pixels. The integration already refuses to
    // publish an HFR for one; the card has to stop labelling the axis.
    const method = this._attr(run, "method");
    const isHfr = method === null || method === undefined
      || String(method).toUpperCase() !== "CONTRASTDETECTION";

    // `autofocus_fitted_hfr` and `autofocus_r2` are diagnostic and ship
    // disabled, so both are taken from the attributes instead: the fitted HFR
    // is the mean of the minima, which is how N.I.N.A. arrives at the point it
    // moves to, and the sensor's R² is the worst of the run's fits.
    //
    // The mean holds only while EVERY minimum survived. A trend-line
    // intersection can extrapolate below zero, and the mapper drops a negative
    // one — averaging what is left would then quietly report the quadratic
    // minimum alone, a different and much higher number than the integration's
    // own `autofocus_fitted_hfr`, which is the mean including the negative.
    const fitted = minima.map((minimum) => minimum.value).filter(Number.isFinite);
    const whole = minima.length > 0 && fitted.length === minima.length;
    const scored = fits.filter((fit) => Number.isFinite(fit.r_squared));
    const worst = scored.reduce(
      (lowest, fit) => (lowest === null || fit.r_squared < lowest.r_squared ? fit : lowest),
      null,
    );

    const temperature = this._number(this._eid("sensor", "focuser_temperature"));
    const at = this._number(
      this._eid("sensor", "autofocus_temperature", "focuser_autofocus_temperature"));

    // The verdict, from the entity that makes it. `reason` separates a run
    // that hung — which wrote no report, so the curve below belongs to an
    // earlier run — from one that finished and was rejected on its fit. The
    // R² is the one the judgement used, so the card cannot contradict the
    // sensor it is quoting.
    const verdict = this._eid("binary_sensor", "autofocus_failed", "focuser_autofocus_failed");
    const judged = this._attr(verdict, "r_squared");
    const threshold = this._attr(verdict, "r_squared_threshold");

    return {
      timestamp: this._state(run),
      curve, fits, minima, method, isHfr,
      unit: isHfr ? "px" : "",
      fitting: this._attr(run, "fitting"),
      autofocuser: this._attr(run, "autofocuser"),
      detector: this._attr(run, "star_detector"),
      measured: this._attr(run, "measured_points"),
      failed: this._state(verdict) === "on",
      reason: this._attr(verdict, "reason"),
      judged: Number.isFinite(judged) ? judged : null,
      threshold: Number.isFinite(threshold) ? threshold : null,
      position: this._number(
        this._eid("sensor", "autofocus_position", "focuser_autofocus_position")),
      hfr: this._number(this._eid("sensor", "autofocus_hfr", "focuser_autofocus_hfr")),
      fittedHfr: whole && isHfr
        ? fitted.reduce((total, value) => total + value, 0) / fitted.length
        : null,
      // Named, because the sensor's R² is the worst of several fits and the
      // number means nothing without knowing which one it came from. The
      // sensor is only a fallback for a report that carried no fits at all —
      // R² comes off `RSquares` whether or not the equation string parsed —
      // and it ships disabled, so on a stock install `fits` is the only source.
      // Disabled also means Home Assistant leaves it out of the registry a
      // dashboard sees, so this read has nothing to resolve on and takes the
      // prefix path.
      worstSquare: worst ? worst.r_squared : this._number(
        this._eid("sensor", "autofocus_r_squared", "focuser_autofocus_r2")),
      worstFit: worst ? pretty(worst.name) : null,
      startPosition: this._number(
        this._eid("sensor", "autofocus_starting_position", "focuser_autofocus_starting_position")),
      startHfr: this._number(
        this._eid("sensor", "autofocus_starting_hfr", "focuser_autofocus_starting_hfr")),
      filter: this._state(this._eid("sensor", "autofocus_filter", "focuser_autofocus_filter")),
      duration: this._number(
        this._eid("sensor", "autofocus_duration", "focuser_autofocus_duration")),
      temperature: at,
      nowTemperature: temperature,
      // The number domain and not the sensor one: the focuser position exists
      // as both, and the sensor is the diagnostic one, disabled by default.
      // The observatory card reads the same number for the same reason.
      nowPosition: this._number(this._eid("number", "focuser_position")),
      drift: Number.isFinite(at) && Number.isFinite(temperature)
        ? temperature - at : null,
    };
  }

  _render() {
    if (!this._hass) return;
    const run = this._read();

    // `set hass` fires on every state change in the whole of Home Assistant,
    // and redrawing the canvas each time buys nothing. The signature is
    // everything the card renders rather than a few fields that stand in for
    // it: state arrives per batch, not per run, so a `hass` can carry the new
    // run's timestamp beside the previous run's HFR and duration. Rendering
    // that mixture is survivable; skipping every later correction because a
    // narrow signature already matched is not — on a focuser with no
    // temperature probe nothing would ever dislodge it.
    const signature = JSON.stringify(run);
    if (signature === this._signature) return;
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
    // Only once the markup is up. Recording it first would mean that a throw
    // anywhere in `_body` left a blank card that never tried again, because
    // the next identical `hass` would match the signature and return.
    this._signature = signature;

    if (this._plottable(run)) requestAnimationFrame(() => this._draw());
  }

  _plottable(run) {
    return run.curve.some((point) => Number.isFinite(point.value));
  }

  _subtitle(run) {
    const when = run.timestamp ? ago(run.timestamp) : null;
    return [
      when,
      shown(run.filter) === "—" ? null : `${safe(run.filter)} filter`,
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
    // Positive means the sweep improved focus. Both readings are measured
    // exposures, so they are comparable; the fitted value is not.
    const gained = Number.isFinite(run.startHfr) && Number.isFinite(run.hfr)
      ? run.startHfr - run.hfr : null;
    // An error of exactly 0 is a frame with no spread to report — near enough
    // one detected star, and a point the fit should not have leaned on.
    const lonely = run.curve.filter(
      (point) => Number.isFinite(point.value) && point.error === 0).length;
    // A fit landing in the outermost step means the true focus is probably
    // outside the range that was swept, so the sweep needs widening and this
    // result does not deserve much confidence.
    const swept = run.curve.map((point) => point.position);
    const reach = run.curve.length > 1
      ? (Math.max(...swept) - Math.min(...swept)) / (run.curve.length - 1) : 0;
    const atEdge = Number.isFinite(run.position) && run.curve.length > 1
      && (run.position <= Math.min(...swept) + reach
        || run.position >= Math.max(...swept) - reach);
    // A hung run wrote no report, so nothing below it describes the failure —
    // it describes whichever run last finished.
    const hung = run.reason === "hung";
    // Only a rejected run leaves a computed position the focuser never took.
    // A hung run's report is an EARLIER run's, and that one was applied.
    const rejected = run.reason === "rejected";
    const quality = run.judged ?? run.worstSquare;

    return `
      ${run.failed ? `
        <div class="banner">
          <span style="font-size:1.1rem">⚠️</span>
          <div>
            <div class="what">${hung ? "An autofocus run hung" : "The last autofocus was rejected"}</div>
            <div class="why">${hung
              ? `It never finished, so it wrote no report — the run charted below is the last one
                 that did, from ${ago(run.timestamp) || "earlier"}, and not the one that failed.`
              : `${run.threshold === null ? "Its fit was not good enough"
                  : `Its fit scored ${fixed(run.judged, 3)} against the ${fixed(run.threshold, 2)}
                     your profile requires`}. The focuser stayed where it was, so frames since are
                 as soft as they were before it.`}</div>
          </div>
        </div>` : ""}

      <div class="stat-row">
        <div class="stat-box">
          <div class="label">${rejected ? "Computed position" : "Focus position"}</div>
          <div class="value">${shown(run.position)} <span class="unit">steps</span></div>
          <div class="sub">${rejected ? "Not applied — rejected"
            : moved === null ? "&nbsp;"
            : `${moved >= 0 ? "+" : "−"}${Math.abs(moved)} from ${run.startPosition}`}</div>
        </div>
        <div class="stat-box">
          <div class="label">Best measured</div>
          <div class="value">${fixed(run.hfr, 2)} <span class="unit">${run.unit}</span></div>
          <div class="sub">${gained === null
            // What the sweep was for. Both numbers are measured — the starting
            // one before it, the best during it — so unlike the fitted value
            // they are on the same scale and the difference means something.
            ? (Number.isFinite(run.fittedHfr) ? `Fitted ${fixed(run.fittedHfr, 2)} ${run.unit}` : "&nbsp;")
            : `${fixed(run.startHfr, 2)} → ${fixed(run.hfr, 2)} · ${
                gained > 0 ? `${fixed(gained, 2)} better` : `${fixed(-gained, 2)} worse`}`}</div>
        </div>
        <div class="stat-box ${run.threshold !== null && quality !== null
            && quality < run.threshold ? "rejected" : ""}">
          <div class="label">Fit quality</div>
          <div class="value">${fixed(quality, 3)} <span class="unit">R²</span></div>
          <div class="sub">${
            // The threshold turns a number nobody knows the scale of into a
            // verdict. Without it the card falls back to naming which of the
            // run's fits the number came from.
            run.threshold === null || quality === null
              ? (run.worstFit || "&nbsp;")
              : `${quality < run.threshold ? "Rejected" : "Passed"} · needs ${fixed(run.threshold, 2)}`}</div>
        </div>
      </div>

      ${Number.isFinite(run.nowTemperature) || away !== null ? `
        <div class="stat-row">
          ${Number.isFinite(run.nowTemperature) ? `
            <div class="stat-box ${drifted ? "drifted" : ""}">
              <div class="label">Temperature since</div>
              <div class="value">${run.drift === null ? "—"
                : `${run.drift >= 0 ? "+" : "−"}${fixed(Math.abs(run.drift), 1)}`} <span class="unit">°C</span></div>
              <div class="sub">${fixed(run.temperature, 1)} → ${fixed(run.nowTemperature, 1)} °C${
                drifted ? ` · past ${fixed(this._temperatureDelta, 1)} °C` : ""}</div>
            </div>` : ""}
          ${away !== null ? `
            <div class="stat-box">
              <div class="label">Focuser now</div>
              <div class="value">${run.nowPosition} <span class="unit">steps</span></div>
              <div class="sub">${
                // On a rejected run the focuser never moved to the computed
                // position, so measuring against it would read as though
                // something nudged the focuser afterwards. Sitting back at the
                // starting position is the signature of the restore.
                rejected
                  ? (run.nowPosition === run.startPosition
                      ? "Back where the run started" : "Not at the computed position")
                  : away === 0 ? "Where the run left it"
                  : `${away > 0 ? "+" : "−"}${Math.abs(away)} steps since the run`}</div>
            </div>` : ""}
        </div>` : ""}

      ${this._plottable(run) ? `
        <div class="chart-section">
          <div class="chart-label">${run.isHfr ? "HFR" : "Contrast"} against focuser position</div>
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
        ${atEdge ? `<span class="chip" style="border-color:rgba(244,162,97,0.45)">
          <span class="k">Focus at the edge of the sweep</span> widen the range</span>` : ""}
        ${lonely ? `<span class="chip" style="border-color:rgba(244,162,97,0.45)">
          <span class="k">No spread to report</span> ${lonely} ${lonely === 1 ? "position" : "positions"}</span>` : ""}
        <span class="chip"><span class="k">Points</span> ${shown(run.measured)} of ${run.curve.length}</span>
        <span class="chip"><span class="k">Took</span> ${duration(run.duration)}</span>
        ${shown(run.method) === "—" ? "" : `<span class="chip"><span class="k">Method</span> ${safe(run.method)}</span>`}
        ${shown(run.fitting) === "—" ? "" : `<span class="chip"><span class="k">Fitting</span> ${safe(run.fitting)}</span>`}
        ${shown(run.autofocuser) === "—" ? "" : `<span class="chip"><span class="k">By</span> ${safe(run.autofocuser)}</span>`}
        ${shown(run.detector) === "—" ? "" : `<span class="chip"><span class="k">Stars</span> ${safe(run.detector)}</span>`}
      </div>
    `;
  }

  _legend(run) {
    const items = [
      `<div class="item"><span class="dot" style="background:${CURVE}"></span>
        <span>Measured</span><span class="reading">${
          run.isHfr ? "± spread across stars" : "contrast score"}</span></div>`,
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
    // Against the axis the chart actually uses, padding included — otherwise a
    // minimum landing inside that padding is called below the axis here and
    // drawn as an ordinary in-range diamond there.
    const { min: floor } = axisRange(run.curve);
    for (const minimum of run.minima) {
      const colour = isTrend(minimum.name) ? TREND : FIT;
      // A minimum the mapper dropped for being negative has no value to plot,
      // and the chart skips it. Saying so beats a legend entry pointing at a
      // marker that is not there.
      const plotted = Number.isFinite(minimum.value);
      const under = plotted && minimum.value < floor;
      items.push(`<div class="item">
        <span class="diamond" style="background:${plotted ? colour : "var(--muted)"}"></span>
        <span${plotted ? "" : ` style="color:var(--muted)"`}>${pretty(minimum.name)}</span>
        <span class="reading">${shown(minimum.position)} · ${
          plotted ? `${reading(minimum.value)} ${run.unit}` : "negative · not plotted"}${
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
    const swept = run.curve.map((point) => point.position);
    // The step comes off the sweep alone. Folding the final position in first
    // would inflate it whenever the fit landed outside the swept range, and
    // with it the margin either side.
    const step = run.curve.length > 1
      ? (Math.max(...swept) - Math.min(...swept)) / (run.curve.length - 1)
      : 1;
    const positions = Number.isFinite(run.position) ? [...swept, run.position] : swept;
    const xMin = Math.min(...positions) - step * 0.5;
    // A sweep that collapsed onto one step would otherwise divide by zero and
    // silently draw nothing: canvas treats a NaN coordinate as a no-op.
    const xSpan = (Math.max(...positions) + step * 0.5 - xMin) || 1;
    const xMax = xMin + xSpan;

    const { measured, min: yMin, max: yMax } = axisRange(run.curve);

    const xOf = (x) => pad.l + ((x - xMin) / xSpan) * plotW;
    const yOf = (y) => pad.t + plotH - ((y - yMin) / (yMax - yMin)) * plotH;
    const inside = (y) => y >= yMin && y <= yMax;
    const onChart = (x) => x >= xMin && x <= xMax;

    ctx.font = "9px sans-serif";
    ctx.textBaseline = "middle";

    // Grid and the measurement axis. The precision follows the range rather
    // than assuming pixels: a contrast score spans thousandths, and five
    // gridlines all reading "0.0" carry nothing.
    const places = Math.min(4, Math.max(1, 1 - Math.floor(Math.log10((yMax - yMin) / 4))));
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
      ctx.fillText(value.toFixed(places), pad.l - 5, y);
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
      // Near-parallel trend lines cross a long way outside the sweep, which is
      // exactly the failed run this card exists to explain. Drawing it anyway
      // would put a marker on top of the axis labels or off the canvas; the
      // legend still carries its position.
      if (!onChart(minimum.position)) continue;
      const x = xOf(minimum.position);
      const below = minimum.value < yMin;
      const y = yOf(Math.min(Math.max(minimum.value, yMin), yMax));
      ctx.fillStyle = isTrend(minimum.name) ? TREND : FIT;
      ctx.strokeStyle = "rgba(255,255,255,0.5)";
      ctx.lineWidth = 0.8;
      const off = below || minimum.value > yMax;
      ctx.beginPath();
      if (off) {
        // Off the chart: a chevron pointing the way it went, pinned to the
        // edge.
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
      // Its real value beside it, because this is the one marker the chart
      // deliberately does not place where it belongs. Without the number a
      // glance reads the chevron's height as the value.
      if (off) {
        ctx.font = "9px sans-serif";
        ctx.textAlign = x > W / 2 ? "right" : "left";
        ctx.fillText(reading(minimum.value), x + (x > W / 2 ? -8 : 8), y + (below ? -5 : 5));
      }
    }
  }

  getCardSize() { return 7; }

  static getConfigForm() {
    return configForm([
      {
        name: "temperature_delta",
        label: "Temperature drift worth flagging",
        helper: "How far the focuser temperature may move from the last run's before the card marks it.",
        default: DEFAULT_TEMPERATURE_DELTA,
        selector: { number: { min: 0.1, step: 0.1, mode: "box", unit_of_measurement: "°C" } },
      },
    ]);
  }

  static getStubConfig() { return {}; }
}

// Guarded: see nina-frame-stats-card.js — a leftover 1.4.5 `/local/` resource
// defining the same tag would otherwise throw and abort this whole module.
if (!customElements.get("nina-autofocus-card")) {
  customElements.define("nina-autofocus-card", NinaAutofocusCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-autofocus-card",
  name: "N.I.N.A. Autofocus Card",
  description: "The last autofocus V-curve with its fits, minima and resulting focus position.",
  preview: true,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-AUTOFOCUS-CARD %c v${VERSION} `,
  "background:#5bcfcf;color:#1c1c2e;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px",
  "background:#1c1c2e;color:#5bcfcf;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

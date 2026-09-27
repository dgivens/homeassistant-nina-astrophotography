/**
 * N.I.N.A. Observatory Card
 * A custom Lovelace card providing a full astrophotography session dashboard.
 *
 * Ships with the integration and registers itself as a dashboard resource —
 * nothing to copy or add under Resources. One rig needs no configuration at
 * all: the card finds its own equipment in the registry.
 *   type: custom:nina-observatory-card
 *   device_id: abc123   # which rig, for two or more; any one of its devices
 *   prefix: n_i_n_a     # fallback only, for the entities that cannot resolve
 */

import { DEFAULT_PREFIX, configForm } from "./nina-card-config.js";
import {
  LinkGrace, hubEntityIds, linkLostSince, RigEntities,
} from "./nina-entity-resolver.js";
import { displayed, missing, quantity, quantityIn, shown } from "./nina-units.js";

const VERSION = "2.0.0";

// Home Assistant has no per-press confirmation for a custom card's own
// buttons, and a mis-tap on any of these costs the rest of the night.
const CONFIRM = {
  sequence_stop: "Stop the running sequence?",
  mount_park: "Park the mount? Imaging stops.",
  dome_close: "Close the dome?",
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function state(hass, entity_id, fallback = "—") {
  const e = hass.states[entity_id];
  return e ? e.state : fallback;
}

function attr(hass, entity_id, attribute, fallback = "—") {
  const e = hass.states[entity_id];
  return e ? (e.attributes[attribute] ?? fallback) : fallback;
}

function isOn(hass, entity_id) {
  return state(hass, entity_id) === "on";
}

// A disconnected device makes its entities unavailable, so availability is
// "connected". Probe an entity that ships enabled, or it reads as permanently
// disconnected. `unknown` also counts as disconnected.
function available(hass, entity_id) {
  return !missing(hass.states[entity_id]?.state);
}

// On, off, or null when there is no state to read: a device that is down, a
// disabled row, a row Home Assistant has no value for.
function onOff(hass, entity_id) {
  return available(hass, entity_id) ? isOn(hass, entity_id) : null;
}

// `Stopped` is one of the mount's own tracking rates, and the one guider status
// that is not guiding.
function notStopped(hass, entity_id) {
  return available(hass, entity_id) ? state(hass, entity_id) !== "Stopped" : null;
}

// Why a control is disabled when no state says which of its pair applies.
function unread(value, device) {
  return value === null ? `The card cannot read the ${device} state` : "";
}

function numState(hass, entity_id, decimals = 1, fallback = "—") {
  const v = parseFloat(state(hass, entity_id, NaN));
  return isNaN(v) ? fallback : v.toFixed(decimals);
}

// A reading printed in the unit Home Assistant converted it to, and with no
// unit at all when there is no reading.
function measured(hass, entity_id, decimals = 1) {
  const q = quantity(hass, entity_id);
  return { value: displayed(q, decimals) ?? "—", unit: q?.unit ?? "" };
}

// No data is not a stopped rig.
function unreachableBanner(since, dome) {
  const time = since
    ? ` since ${new Date(since).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : "";
  return `
  <div class="session-banner unreachable">
    <span class="icon">📡</span>
    <div>
      <div class="label">N.I.N.A. unreachable</div>
      <div class="detail">No data from N.I.N.A.${time}; it may still be imaging. ${dome ? "Stop, park and close" : "Stop and park"} still send.</div>
    </div>
  </div>`;
}

function statusDot(on) {
  return `<span class="dot ${on ? "dot-on" : "dot-off"}"></span>`;
}

// ─── Template ────────────────────────────────────────────────────────────────

const STYLE = `
  :host {
    --card-bg: var(--ha-card-background, var(--card-background-color, #1c1c2e));
    --card-border: var(--divider-color, rgba(255,255,255,0.1));
    --accent: #7b8de8;
    --accent2: #5bcfcf;
    --warn: #f4a261;
    --danger: #e76f51;
    --success: #57cc99;
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

  /* ── Header ── */
  .header {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 18px 10px;
    border-bottom: 1px solid var(--card-border);
    background: rgba(123,141,232,0.08);
  }
  .header .title {
    font-size: 1.05rem;
    font-weight: 600;
    flex: 1;
    letter-spacing: .3px;
  }
  .header .subtitle {
    font-size: 0.72rem;
    color: var(--muted);
    margin-top: 1px;
  }
  .nina-icon { font-size: 1.4rem; }

  /* ── Section grid ── */
  .body { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 12px; }

  /* ── Session banner ── */
  .session-banner {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: rgba(91,207,207,0.08);
    border: 1px solid rgba(91,207,207,0.2);
    border-radius: 10px;
    padding: 10px 14px;
  }
  .session-banner .target { font-size: 1rem; font-weight: 600; color: var(--accent2); }
  .session-banner .progress-track {
    width: 130px;
    height: 6px;
    background: rgba(255,255,255,0.1);
    border-radius: 3px;
    overflow: hidden;
  }
  .session-banner .progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    border-radius: 3px;
    transition: width 0.6s ease;
  }
  .session-banner .frame-count { font-size: 0.75rem; color: var(--muted); text-align: right; }

  /* The lost link, in the weather card's colours */
  .session-banner.unreachable {
    justify-content: flex-start;
    gap: 12px;
    background: rgba(244,162,97,0.10);
    border-color: rgba(244,162,97,0.30);
  }
  .session-banner .icon { font-size: 1.5rem; flex-shrink: 0; }
  .session-banner .label { font-size: 1rem; font-weight: 700; color: var(--warn); }
  .session-banner .detail { font-size: 0.68rem; color: var(--muted); margin-top: 2px; }

  /* ── Equipment status row ── */
  .equip-row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
  .equip-chip {
    display: flex;
    align-items: center;
    gap: 5px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--card-border);
    border-radius: 20px;
    padding: 4px 10px;
    font-size: 0.72rem;
    font-weight: 500;
  }
  .equip-chip.connected { border-color: rgba(87,204,153,0.4); }
  .equip-chip.disconnected { opacity: 0.5; }

  /* ── Section ── */
  .section { display: flex; flex-direction: column; gap: 6px; }
  .section-title {
    font-size: 0.65rem;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    color: var(--muted);
    padding-bottom: 2px;
    border-bottom: 1px solid var(--card-border);
  }
  .metric-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 7px;
  }
  .metric {
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 8px 10px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }
  .metric .label { font-size: 0.62rem; color: var(--muted); font-weight: 500; }
  .metric .value { font-size: 0.88rem; font-weight: 600; }
  .metric .unit { font-size: 0.6rem; color: var(--muted); margin-left: 2px; }

  /* ── Guiding section ── */
  .guider-row { display: flex; gap: 8px; align-items: flex-start; }
  .guider-meter {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 8px 10px;
  }
  .rms-bars { display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
  .rms-bar-wrap { display: flex; align-items: center; gap: 6px; }
  .rms-label { width: 28px; font-size: 0.65rem; color: var(--muted); }
  .rms-track {
    flex: 1; height: 5px; background: rgba(255,255,255,0.1);
    border-radius: 3px; overflow: hidden;
  }
  .rms-fill {
    height: 100%; border-radius: 3px;
    transition: width 0.5s ease;
  }
  .rms-fill.ra { background: var(--accent); }
  .rms-fill.dec { background: var(--accent2); }
  .rms-fill.warn { background: var(--warn); }
  .rms-fill.danger { background: var(--danger); }
  .rms-value { width: 40px; font-size: 0.65rem; text-align: right; }

  /* ── Buttons row ── */
  .btn-row { display: flex; gap: 8px; flex-wrap: wrap; }
  .nina-btn {
    flex: 1;
    min-width: 80px;
    padding: 8px 12px;
    border: 1px solid var(--card-border);
    border-radius: 8px;
    background: rgba(255,255,255,0.06);
    color: var(--text);
    font-size: 0.78rem;
    font-weight: 600;
    cursor: pointer;
    text-align: center;
    transition: background 0.15s, transform 0.1s;
    display: flex; align-items: center; justify-content: center; gap: 5px;
  }
  .nina-btn:not(:disabled):hover { background: rgba(255,255,255,0.12); }
  .nina-btn:not(:disabled):active { transform: scale(0.97); }
  .nina-btn.primary { background: rgba(123,141,232,0.18); border-color: var(--accent); color: var(--accent); }
  .nina-btn.danger  { background: rgba(231,111,81,0.15); border-color: var(--danger); color: var(--danger); }
  .nina-btn.success { background: rgba(87,204,153,0.15); border-color: var(--success); color: var(--success); }
  .nina-btn:disabled { opacity: 0.4; cursor: not-allowed; }

  /* ── Status dots ── */
  .dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; }
  .dot-on  { background: var(--success); box-shadow: 0 0 5px var(--success); }
  .dot-off { background: var(--muted); }
  .dot-warn { background: var(--warn); box-shadow: 0 0 5px var(--warn); }

  /* ── Image stats ── */
  .img-stats-row {
    display: flex; gap: 8px;
  }
  .img-stat {
    flex: 1;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--card-border);
    border-radius: 8px;
    padding: 6px 8px;
    text-align: center;
  }
  .img-stat .label { font-size: 0.58rem; color: var(--muted); }
  .img-stat .value { font-size: 0.9rem; font-weight: 700; }

  /* ── Flip alert ── */
  .flip-alert {
    display: flex; align-items: center; gap: 8px;
    background: rgba(244,162,97,0.12);
    border: 1px solid rgba(244,162,97,0.4);
    border-radius: 8px; padding: 7px 12px;
    font-size: 0.78rem; color: var(--warn);
  }
`;

// ─── Card class ──────────────────────────────────────────────────────────────

class NinaObservatoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._grace = new LinkGrace(() => this._render());
  }

  setConfig(config) {
    this._config = config || {};
    this._rig = new RigEntities(
      this._config.prefix || DEFAULT_PREFIX, this._config.device_id);
    this._grace.reset();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._rig.refresh(hass)) {
      this._linkRows = hubEntityIds(hass, this._config.device_id) ?? [
        this._eid("binary_sensor", "sequencer_running"),
        this._eid("binary_sensor", "imaging"),
        this._eid("sensor", "session_image_count"),
      ];
    }
    this._render();
  }

  // Falls back to a prefixed `slug` when nothing resolves. The select keyed
  // `filter` lives on the Filter Wheel device; `guider_rms_dec` is named "RMS
  // declination".
  _eid(domain, key, slug = key) {
    return this._rig.id(domain, key, slug);
  }

  _callService(domain, service, data = {}) {
    // The actions resolve which rig they mean from the device targeted; an
    // untargeted call is refused as soon as a second instance is configured.
    const device_id = this._config.device_id;
    this._hass.callService(domain, service,
                           device_id ? { ...data, device_id } : data);
  }

  _render() {
    const h = this._hass;
    if (!h) return;

    // The sequencer and the camera answer different questions: a rig waiting
    // out a target's start window is running and taking nothing.
    const seqId       = this._eid("binary_sensor", "sequencer_running");
    const imagingId   = this._eid("binary_sensor", "imaging");
    const frameCountId = this._eid("sensor", "session_image_count");
    const seqRunning  = isOn(h, seqId);
    const imaging     = isOn(h, imagingId);
    const lostSince = linkLostSince(h, this._linkRows);
    if (this._grace.hold(lostSince)) return;
    const unreachable = lostSince !== null;
    const camConnected = available(h, this._eid("sensor", "camera_state"));
    const mntConnected = available(h, this._eid("sensor", "mount_right_ascension"));
    const focConnected = available(h, this._eid("number", "focuser_position"));
    const fwConnected  = available(h, this._eid("select", "filter", "filter_wheel_filter"));
    const gdrStatusId  = this._eid("sensor", "guider_status");
    const gdrConnected = available(h, gdrStatusId);
    // Every dome entity ships disabled, so the section stays hidden until a
    // dome owner enables them (issue #93).
    const domeParkId   = this._eid("binary_sensor", "dome_at_park");
    const domeConnected = available(h, domeParkId);
    // Any row, even `unavailable`: Close Dome must survive a lost link.
    const domeEnabled  = !!h.states[domeParkId];

    // The guider switch has no `translation_key` and stays on the prefix path,
    // so a prefix that does not match the instance loses it; the status sensor
    // it is derived from resolves.
    const guiding      = onOff(h, this._eid("switch", "guider")) ?? notStopped(h, gdrStatusId);
    const cooling      = onOff(h, this._eid("switch", "camera_cooler"));
    const parkedId     = this._eid("binary_sensor", "mount_at_park");
    // No state reads as unparked on purpose: Park is an emergency control, and
    // a parked mount sent it again does nothing.
    const parked       = isOn(h, parkedId);
    const tracking     = notStopped(h, this._eid("select", "mount_tracking_rate"));
    // The shutter reports its own state; `Open` is the only one that is open.
    // Disabled as well, so this reads false until enabled — see above.
    const domeOpen     = state(h, this._eid("sensor", "dome_shutter_status")) === "Open";

    const target       = state(h, this._eid("sensor", "sequence_target"), "No target");
    // Ships disabled and reads `unknown` on a Target Scheduler rig; a bar at 0%
    // would claim a count the rig never published, so the bar is omitted.
    const progress     = parseFloat(state(h, this._eid("sensor", "sequence_progress"), ""));
    const frameCount   = shown(state(h, frameCountId, "0"));

    const camTemp      = measured(h, this._eid("sensor", "camera_temperature"));
    const camTargTemp  = measured(h, this._eid("number", "camera_target_temperature"));
    const coolerPwr    = numState(h, this._eid("sensor", "camera_cooler_power"), 0);
    const camGain      = shown(state(h, this._eid("sensor", "camera_gain")));
    const camFilter    = shown(state(h, this._eid("select", "filter", "filter_wheel_filter")));

    const mntRa        = numState(h, this._eid("sensor", "mount_right_ascension"), 4);
    const mntDec       = numState(h, this._eid("sensor", "mount_declination"), 3);
    const mntAlt       = numState(h, this._eid("sensor", "mount_altitude"), 1);
    const mntAz        = numState(h, this._eid("sensor", "mount_azimuth"), 1);
    // The flip fires at (Max − Min), not zero, so the warning window adds the
    // sensor's own published offset rather than a bare number.
    const flipId       = this._eid("sensor", "mount_time_to_meridian_flip");
    const ttf          = quantityIn(h, flipId, "min") ?? NaN;
    const flipFiresAt  = parseFloat(attr(h, flipId, "flip_fires_at_minutes", "")) || 0;

    const focPos       = shown(state(h, this._eid("number", "focuser_position")));
    const focTemp      = measured(h, this._eid("sensor", "focuser_temperature"));

    // NaN rather than 0 when there is no reading: a missing RMS rendered as
    // 0.00" is indistinguishable from perfect guiding.
    const rmsTotal     = parseFloat(state(h, this._eid("sensor", "guider_rms_total"), ""));
    const rmsRa        = parseFloat(state(h, this._eid("sensor", "guider_rms_ra"), ""));
    const rmsDec       = parseFloat(
      state(h, this._eid("sensor", "guider_rms_dec", "guider_rms_declination"), ""));
    const guided       = Number.isFinite(rmsTotal);

    const hfr          = numState(h, this._eid("sensor", "last_image_hfr"), 2);
    const stars        = shown(state(h, this._eid("sensor", "last_image_star_count")));
    const meanAdu      = shown(state(h, this._eid("sensor", "last_image_mean_adu")));

    // RMS bar widths (max = 4 arcsec = 100%)
    const rmsMax = 4;
    const pct = (v) => Math.min((v / rmsMax) * 100, 100).toFixed(1);
    const rmsClass = (v) => v > 3 ? "danger" : v > 1.5 ? "warn" : "";

    const [status, dot] = unreachable ? ["Unreachable", "dot-warn"]
      : seqRunning ? ["Session active", "dot-on"] : ["Standby", "dot-off"];
    // The park row, not the RA probe, which a user may disable.
    const mountStatus = !available(h, parkedId) ? ""
      : parked ? " · Parked" : tracking ? " · Tracking" : " · Idle";

    // `off` is why the button is disabled, or empty for a live one.
    const btn = (id, label, cls = "", off = "") =>
      `<button class="nina-btn${cls && ` ${cls}`}" id="${id}"`
      + `${off ? ` disabled title="${off}"` : ""}>${label}</button>`;
    const LOST = "N.I.N.A. unreachable";
    // With no state to choose either of a pair, the set is fixed: commands
    // that end activity stay live, the rest wait.
    const controls = unreachable ? [
      [
        btn("btn-stop", "⏹ Stop Sequence", "danger"),
        btn("btn-park", "⏸ Park"),
        domeEnabled ? btn("btn-dome-close", "🔒 Close Dome") : "",
      ],
      [
        btn("btn-start", "▶ Start Sequence", "success", LOST),
        btn("btn-af", "🔍 Auto Focus", "", LOST),
        btn("btn-cool", "❄ Cool Camera", "primary", LOST),
        btn("btn-start-guide", "▶ Start Guiding", "success", LOST),
      ],
    ] : [
      [
        seqRunning
          ? btn("btn-stop", "⏹ Stop Sequence", "danger")
          : btn("btn-start", "▶ Start Sequence", "success"),
        parked ? btn("btn-unpark", "⬆ Unpark", "primary") : btn("btn-park", "⏸ Park"),
        btn("btn-af", "🔍 Auto Focus"),
        !domeConnected ? ""
          : domeOpen
            ? btn("btn-dome-close", "🔒 Close Dome")
            : btn("btn-dome-open", "🔓 Open Dome", "primary"),
      ],
      // Neither cooling nor guiding is an emergency to end, so with no state
      // to pick one of the pair, these wait for one.
      [
        cooling
          ? btn("btn-warm", "🌡 Warm Camera")
          : btn("btn-cool", "❄ Cool Camera", "primary", unread(cooling, "camera cooler")),
        guiding
          ? btn("btn-stop-guide", "◼ Stop Guiding", "danger")
          : btn("btn-start-guide", "▶ Start Guiding", "success", unread(guiding, "guider")),
      ],
    ];

    // Meridian flip warning
    const showFlipWarning =
      tracking && Number.isFinite(ttf) && ttf > 0 && ttf < 15 + flipFiresAt;

    const html = `
      <style>${STYLE}</style>
      <ha-card>
        <div class="header">
          <span class="nina-icon">🔭</span>
          <div>
            <div class="title">N.I.N.A. Observatory</div>
            <div class="subtitle">Advanced API v2 · ${status}</div>
          </div>
          <span class="dot ${dot}"></span>
        </div>

        <div class="body">

          ${unreachable ? unreachableBanner(lostSince, domeEnabled) : `
          <div class="session-banner">
            <div>
              <div class="target">${seqRunning ? target : "—"}</div>
              <div style="font-size:0.68rem;color:var(--muted);margin-top:2px;">${imaging ? "Imaging" : seqRunning ? "Running, not imaging" : "Sequence not running"}</div>
            </div>
            <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
              ${isNaN(progress) ? "" : `
              <div class="progress-track">
                <div class="progress-fill" style="width:${progress}%"></div>
              </div>`}
              <div class="frame-count">${isNaN(progress) ? "" : `${progress.toFixed(0)}% · `}${frameCount} frames</div>
            </div>
          </div>`}

          ${unreachable ? "" : `
          <div class="equip-row">
            ${chip("Camera", camConnected)}
            ${chip("Mount", mntConnected)}
            ${chip("Focuser", focConnected)}
            ${chip("Filter Wheel", fwConnected)}
            ${chip("Guider", gdrConnected)}
            ${domeConnected ? chip("Dome", domeConnected) : ""}
          </div>`}

          ${showFlipWarning ? `
            <div class="flip-alert">
              ⚠️ Meridian flip in <strong style="margin:0 4px;">${ttf.toFixed(0)} min</strong>
            </div>
          ` : ""}

          <div class="section">
            <div class="section-title">Camera ${cooling ? "· ❄️ Cooling" : ""}</div>
            <div class="metric-grid">
              ${metric("Temp", camTemp.value, camTemp.unit)}
              ${metric("Setpoint", camTargTemp.value, camTargTemp.unit)}
              ${metric("Cooler", coolerPwr, "%")}
              ${metric("Gain", camGain, "")}
              ${metric("Filter", camFilter, "")}
            </div>
          </div>

          <div class="section">
            <div class="section-title">Mount${mountStatus}</div>
            <div class="metric-grid">
              ${metric("RA", mntRa, "h")}
              ${metric("Dec", mntDec, "°")}
              ${metric("Alt", mntAlt, "°")}
              ${metric("Az", mntAz, "°")}
              ${ttf < 999 ? metric("Flip in", ttf.toFixed(0), "min") : ""}
            </div>
          </div>

          <div class="section">
            <div class="section-title">Focuser</div>
            <div class="metric-grid">
              ${metric("Position", focPos, "steps")}
              ${metric("Temp", focTemp.value, focTemp.unit)}
            </div>
          </div>

          ${gdrConnected ? `
            <div class="section">
              <div class="section-title">Guiding · ${guiding === null ? "" : guiding ? "Active · " : "Stopped · "}bars full scale 4"</div>
              <div class="guider-meter">
                <div style="font-size:0.72rem;color:var(--muted);">
                  Total RMS: <strong style="color:var(--text)">${guided ? `${rmsTotal.toFixed(2)}"` : "—"}</strong>
                </div>
                ${guided ? `
                  <div class="rms-bars">
                    <div class="rms-bar-wrap">
                      <span class="rms-label">RA</span>
                      <div class="rms-track"><div class="rms-fill ra ${rmsClass(rmsRa)}" style="width:${pct(rmsRa)}%"></div></div>
                      <span class="rms-value">${rmsRa.toFixed(2)}"</span>
                    </div>
                    <div class="rms-bar-wrap">
                      <span class="rms-label">Dec</span>
                      <div class="rms-track"><div class="rms-fill dec ${rmsClass(rmsDec)}" style="width:${pct(rmsDec)}%"></div></div>
                      <span class="rms-value">${rmsDec.toFixed(2)}"</span>
                    </div>
                  </div>
                ` : ""}
              </div>
            </div>
          ` : ""}

          <div class="section">
            <div class="section-title">Last Image</div>
            <div class="img-stats-row">
              ${imgStat("HFR", hfr, "px")}
              ${imgStat("Stars", stars)}
              ${imgStat("Mean ADU", meanAdu)}
            </div>
          </div>

          <div class="section">
            <div class="section-title">Controls</div>
            ${controls.map((row) => `<div class="btn-row">${row.join("")}</div>`).join("")}
          </div>

        </div>
      </ha-card>
    `;

    this.shadowRoot.innerHTML = html;
    this._attachListeners();
  }

  _attachListeners() {
    const bind = (id, fn) => {
      const el = this.shadowRoot.getElementById(id);
      if (el) el.addEventListener("click", fn);
    };
    const svc = (s, d) => {
      if (CONFIRM[s] && !window.confirm(CONFIRM[s])) return;
      this._callService("nina_astrophotography", s, d);
    };

    bind("btn-start",      () => svc("sequence_start"));
    bind("btn-stop",       () => svc("sequence_stop"));
    bind("btn-park",       () => svc("mount_park"));
    bind("btn-unpark",     () => svc("mount_unpark"));
    bind("btn-af",         () => svc("focuser_auto_focus"));
    bind("btn-dome-open",  () => svc("dome_open"));
    bind("btn-dome-close", () => svc("dome_close"));
    bind("btn-cool",       () => svc("camera_cool", { temperature: -10, minutes: 15 }));
    bind("btn-warm",       () => svc("camera_warm", { minutes: 20 }));
    bind("btn-start-guide",() => svc("guider_start"));
    bind("btn-stop-guide", () => svc("guider_stop"));
  }

  getCardSize() { return 8; }

  static getConfigForm() { return configForm(); }

  static getStubConfig() {
    return {};
  }
}

function chip(label, connected) {
  return `<div class="equip-chip ${connected ? "connected" : "disconnected"}">
    ${statusDot(connected)} ${label}
  </div>`;
}

function metric(label, value, unit) {
  return `<div class="metric">
    <div class="label">${label}</div>
    <div class="value">${value}<span class="unit">${value === "—" ? "" : unit}</span></div>
  </div>`;
}

function imgStat(label, value, unit = "") {
  return `<div class="img-stat">
    <div class="label">${label}</div>
    <div class="value">${value}${value === "—" || !unit ? "" : ` ${unit}`}</div>
  </div>`;
}

// Guarded: a stale 1.4.5 `/local/` resource defining the same tag would
// otherwise throw and abort the rest of this module.
if (!customElements.get("nina-observatory-card")) {
  customElements.define("nina-observatory-card", NinaObservatoryCard);
}

window.customCards = window.customCards || [];
window.customCards.push({
  type: "nina-observatory-card",
  name: "N.I.N.A. Observatory Card",
  description: "Full session dashboard for N.I.N.A. astrophotography software.",
  preview: true,
  documentationURL: "https://github.com/dgivens/homeassistant-nina-astrophotography#lovelace-cards",
});

console.info(
  `%c NINA-OBSERVATORY-CARD %c v${VERSION} `,
  "background:#7b8de8;color:#fff;font-weight:700;padding:2px 6px;border-radius:4px 0 0 4px",
  "background:#1c1c2e;color:#7b8de8;font-weight:700;padding:2px 6px;border-radius:0 4px 4px 0"
);

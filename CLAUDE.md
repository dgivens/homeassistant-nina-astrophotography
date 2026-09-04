# N.I.N.A. Astrophotography — Home Assistant integration

A custom integration bridging N.I.N.A.'s Advanced API plugin into Home
Assistant. This repository is the maintained fork; upstream is inactive.

`docs/v2.0-design.md` is the design of record for the 2.0 rewrite. Read it
before making structural changes — it carries measured numbers and verified API
behaviour that are expensive to rediscover.

## Quality bar

Target the Home Assistant **Bronze** quality-scale tier, and treat Silver/Gold
rules as guidance rather than gates. The Bronze rules that bind us:

- `config-flow-test-coverage` — **100%** on the config flow, including error
  recovery and the duplicate-entry guard
- `test-before-configure` / `test-before-setup` — validate the connection in the
  config flow; raise `ConfigEntryNotReady` vs `ConfigEntryError` correctly
- `runtime-data` — state lives on `entry.runtime_data`, never
  `hass.data[DOMAIN][entry_id]`
- `common-modules` — the coordinator is `coordinator.py`, the base entity is
  `entity.py`
- `has-entity-name` — entity names derive from their device
- `appropriate-polling`, `entity-unique-id`, `entity-event-setup`

`reauthentication-flow` is **exempt**: the Advanced API has no authentication.
Record exemptions in `quality_scale.yaml` rather than leaving them looking
unimplemented.

## Testing

Two suites, one command:

- `tests/unit/` — **no Home Assistant import.** Runs in milliseconds. Covers the
  API client, wire→model mapping, pure computations, and event parsing. Keep it
  HA-free: `api/errors.py` subclasses builtins only, and nothing under `api/`
  imports `homeassistant`.
- `tests/ha/` — `pytest-homeassistant-custom-component`. Covers config flow,
  setup/unload, the device and entity registries, availability, and actions.

Test through **public Home Assistant interfaces**: set up via
`hass.config_entries.async_setup`, assert via `hass.states`, `hass.services`,
and the registries. Do not reach into coordinator internals — tests that do stop
surviving refactors, which defeats the point during a restructure.

### Keep tests tightly scoped

- One behaviour per test. If a test needs a paragraph to explain what it proves,
  it is testing too much.
- **Do not test the standard library or third-party packages.** No tests that
  `json.loads` parses JSON, that `aiohttp` performs HTTP, that
  `dataclasses.frozen` prevents assignment, or that Home Assistant's own
  `CoordinatorEntity` propagates availability. Test *our* logic.
- Prefer a table of cases over near-duplicate test functions.
- No incidental assertions. Asserting six unrelated fields to prove one mapping
  makes the failure message useless and the test brittle.
- Verbose setup is a smell: reach for a fixture, not more lines.

Coverage is deliberately uneven — 100% on the config flow, high on the mapper
and the pure computation modules, no global percentage gate.

## Test fixtures: capture from a live rig, then redact

Fixtures are **recorded from real hardware**, never hand-written. The published
OpenAPI spec is accurate about field *names* and unreliable about *types*, and
it contains at least one enum value that does not match the wire. Hand-written
fixtures encode the spec's mistakes; captured ones encode reality.

**Trust the rig over the spec wherever they disagree.**

Capture with `scripts/capture_fixtures.py`. Two hard rules:

**1. Read-only against a live rig.** Only `GET` endpoints that report state:
`/version`, `/equipment/info`, `/equipment/*/info`, `/image-history`,
`/sequence/json`, `/event-history`, `/flats/status`, `/equipment/focuser/last-af`.
**Never** call anything that commands equipment — slew, capture, park, home,
connect, disconnect, guider, filter change, focuser move, flat light, dome,
sequence start/stop, profile switch — unless the operator has explicitly said
the rig is idle and it is safe. A rig may be imaging, and a wasted night is not
recoverable. If unsure whether a call mutates state, do not make it.

**2. Redact before committing.** A profile dump contains live credentials.

| Field pattern | Action |
|---|---|
| `*ApiKey`, `*Token`, `*Secret`, `*Password`, `*Credential` | `"REDACTED"` |
| `*Path`, `*Folder`, `*Directory`, `*Host`, `*Url` | `"REDACTED"` |
| any Windows path or bare IPv4 in a value | `"REDACTED"` |
| `SiteLatitude`, `SiteLongitude`, `SiteElevation`, `Latitude`, `Longitude`, `Elevation` | `0` |
| `TelescopeName`, `CameraName` | `"Telescope"`, `"Camera"` |
| `Filename` | renumbered `frame_NNNN.fits` |
| `TargetName` | keep — an astronomical object, not identifying |

`/profile/show` is excluded from the corpus entirely; its secret surface is too
large to redact confidently.

The corpus needs **states**, not one snapshot — imaging, dawn flats (calibration
sentinels), before the first sub, equipment disconnected, sequence complete,
Home Assistant started before N.I.N.A. Capture them opportunistically as the
rig produces them.

## Comments and docstrings

Keep both concise, and prefer explaining *why* over restating *what*.

**Docstrings carry durable knowledge, not session history.** The test: would
this help someone touching this code a year from now with no memory of how it
came to be written?

- **Keep:** non-obvious API behaviour a reader would otherwise get wrong —
  "`Success` alone is not enough to key on: some handlers assign it from the
  driver's return value, so it can be false on a call that worked."
- **Drop:** how we discovered it, which PR changed it, what the code used to do,
  what bug prompted the change, or that a live rig was involved. Git history and
  `docs/` hold that; a docstring that narrates it ages into noise.

The same applies to inline comments. A comment justifying a surprising line is
worth keeping; a comment recounting the debugging session that produced it is
not.

## API behaviour that will otherwise catch you out

- **The HTTP status is almost always 200.** The handler layer never sets it, so
  refused commands, `409 Sequencer not initialized` and handler exceptions all
  arrive as HTTP 200 with the real code in the body's `StatusCode`. Only routing
  and parameter-binding failures produce a real 4xx, and those return HTML.
- **`NaN` arrives as the JSON string `"NaN"`**, not a number — .NET serializes
  it that way. Map it to `None` across every numeric field, or it corrupts
  long-term statistics.
- **Sentinels are pervasive:** calibration frames report `HFR 0` / `Stars -1`;
  an empty image history answers `Index out of range`; a mount with tracking off
  reports 24 hours to meridian flip; an idle flat wizard reports `-1` iterations.
  Normalize them to `None` in the wire→model mapper, never above it.
- **Ranges are per-device.** Flat panel brightness is `MinBrightness`–
  `MaxBrightness` and varies by hardware; mount tracking modes come from
  `TrackingModes` and differ by mount. Never hardcode either.
- **Out-of-range input is silently clamped** and answers `Success: true`.
  Validate client-side and raise `ServiceValidationError`.

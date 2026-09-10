# N.I.N.A. Astrophotography — Home Assistant integration

A custom integration bridging N.I.N.A.'s Advanced API plugin into Home
Assistant. This repository is the maintained fork; upstream is inactive.

`docs/v2.0-design.md` is the design of record for the 2.0 rewrite. Read it
before making structural changes — it carries measured numbers and verified API
behaviour that are expensive to rediscover.

## Commands

```bash
uv sync                                                  # the `test` group only — no Home Assistant
uv run pytest tests/unit -p no:homeassistant -q          # fast: well under a second
uv run --group test-ha pytest tests/ha -q                # the Home Assistant suite; never -n auto
uv run pytest tests/unit/test_api_envelope.py -v
```

**A bare `uv run pytest` collects both suites** and loads Home Assistant before
collection; always name the suite.

Dependencies and pytest config live in `pyproject.toml`; there is no
`requirements*.txt` and no `pytest.ini`. Groups: `test` (lean, HA-free),
`test-ha` (`pytest-homeassistant-custom-component`, pinned — add with
`uv sync --group test-ha`), `dev` (schema generator, pre-commit).

**Keep `uv sync` free of Home Assistant.** That is what makes the fast suite
fast, and the modules it covers have no `homeassistant` imports.

`pythonpath = ["tests", "."]` means helpers import as `from helpers import ...`.
CI is `.github/workflows/ci.yml` (both suites, coverage floors, fixture
redaction, hassfest, HACS); no linter or formatter is configured.

## Layout (current)

```
custom_components/nina_astrophotography/
  __init__.py         entry setup and unload, the socket wiring, the services
  api/                the version-independent seam: errors.py, models.py (THE CONTRACT)
  api/v2/             client.py (the only module that talks to N.I.N.A.), mapper.py
                      (wire → models; every sentinel dies here), schema.py (generated),
                      events.py (the event socket inside the seam; emits NinaEvent)
  legacy_api.py       the 1.4.x client the unmigrated services still use
  coordinator.py      DataUpdateCoordinator publishing NinaData; owns frames/events
  entity.py           the shared entity base
  device.py           the hub and one device per equipment type; the only
                      writer of driver metadata into the device registry
  derive.py           pure maths; session.py — the pure session fold
  polling.py          HA-free polling decisions: restart, reseed, tiers, event ledger
  const.py            domain, config keys, service names, enums
  config_flow.py      UI setup
  light.py            the flat panel (migrated); the other platforms are
                      unregistered until phase C migrates them
blueprints/automation/nina_astrophotography/   5 automation blueprints
www/                                           5 Lovelace cards
tests/unit/                                    HA-free; tests/ha/ under PHACC
```

## Branches

- `main` — the shipping line, at 1.4.5
- `v2` — the 2.0 integration branch; work lands as stacked task PRs onto it
- **`wip/v2.0` — a read-only reference. Never merge or rebase it.** It predates
  every fix on `main` and has no tests; its value is the API audit in its
  CHANGELOG and README, which `docs/v2.0-design.md` supersedes.

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

Two suites, run separately:

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

Capture with `scripts/capture_fixtures.py`; install the redaction guard once
with `uv run --group dev pre-commit install` so a fixture cannot be committed
unredacted. Two hard rules:

**1. Read-only against a live rig.** Only `GET` endpoints that report state:
`/version`, `/version/nina`, `/equipment/info`, `/equipment/*/info`, `/image-history`,
`/sequence/json`, `/sequence/state`, `/event-history`, `/flats/status`,
`/equipment/focuser/last-af`, `/application-start`, `/livestack/status`, and
`/profile/show` (as an allowlist projection only — see below).
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
| any Windows path, bare IPv4, UUID or HA entity id in a value | `"REDACTED"` |
| a site or facility identifier in `Name`, `DisplayName`, `Description` or `ProjectName` | `"REDACTED"` |
| a facility token inside any other string value | the token → `"REDACTED"`, the rest of the string kept |
| `DeviceId`, `EntityId` | stable pseudonym `device-<8 hex>`, preserving distinctness |
| `TelescopeName`, `CameraName` | `"Telescope"`, `"Camera"` |
| `Filename` | stable pseudonym `frame_<8 hex>.fits`, derived from the original |
| `TargetName` | keep — an astronomical object, not identifying |
| `SiteLatitude`, `SiteLongitude`, `SiteElevation`, `Altitude`, `SiderealTime`, `SideOfPier` | **keep** — see below |

**Site coordinates are kept, deliberately.** The rig is hosted at a public
commercial facility and its location is not sensitive here. Zeroing them was
also ineffective: a mount parked at the pole reports `Altitude` equal to the
site latitude, and `SiderealTime` against `Coordinates.DateTime.UtcNow` solves
for longitude — so the coordinates were derivable from fixtures whose named
fields were all correctly zeroed.

Keeping them is what makes §11's meridian-flip maths testable:
`(RA_JNOW − LST) mod 12` needs a real `SiderealTime`, and the pier-side windows
that add 12 h need a real `SideOfPier`. The alternative is a hand-written
synthetic `(LST, RA, longitude)` triple, and hand-written fixtures encode the
spec's mistakes rather than reality.

**`Filename` is pseudonymised by hashing the original, never numbered by
position.** Frame identity is `(Date, Filename)` and the fold spans fixtures, so
a per-file counter both collides distinct frames across files and splits
identical ones — which would make the path-equivalence property untestable.

The **existing corpus predates this rule** and still carries zeroed coordinates
and a `SideOfPier` of `"REDACTED"`. Re-capture will change those fields, so a
re-capture is not byte-identical to what is committed today; that is expected,
not a regression.

`/profile/show` is captured as an **allowlist projection** — only
`TelescopeSettings.FocalLength`, `FocuserSettings.{AutoFocusTimeoutSeconds,
RSquaredThreshold}`, `MeridianFlipSettings.*` and `CameraSettings.PixelSize`.
Never denylist it: its secret surface is too large to redact confidently, and it
held a live `WeatherUndergroundAPIKey` on a trial capture.

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

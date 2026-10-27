# N.I.N.A. Astrophotography — Home Assistant integration

A custom integration bridging N.I.N.A.'s Advanced API plugin into Home
Assistant. This repository is the maintained fork; upstream is inactive.

`docs/v2.0-design.md` is the design of record for the 2.0 rewrite. Read it
before making structural changes — it carries measured numbers and verified API
behaviour that are expensive to rediscover.

## Read before you touch

| Before you… | Read |
|---|---|
| change a Lovelace card in `www/`, or claim one verified | `docs/contributing/cards.md` |
| send any request to a rig, or capture, redact or commit a fixture | `docs/contributing/fixtures.md` |
| write a test in `tests/ha/` | `tests/scenarios/README.md`, then `docs/contributing/testing.md` |
| open, stack or release a PR | `docs/contributing/pull-requests.md` |
| write a design doc | `docs/contributing/design-docs.md` |
| work on the simulated rig or the 1.4.5 upgrade | `docs/test-vm.md`, `tools/windows-rig/README.md`, `tools/upgrade-harness/README.md` |

## Commands

```bash
uv sync                                                  # the `test` group only — no Home Assistant
uv run pytest tests/unit -p no:homeassistant -q          # fast: well under a second
uv run --group test-ha pytest tests/ha -q                # the Home Assistant suite; never -n auto
uv run --group dev --group test-ha pyright                      # custom_components/, scripts/, tests/, tools/
uv run --group dev ruff check --fix . && uv run --group dev ruff format .   # lint and format
```

`just ci` runs everything CI checks; the coverage floors and the redaction
guard are in `docs/contributing/testing.md`.

- **Always name the suite.** A bare `uv run pytest` collects both and loads
  Home Assistant before collection.
- **Never pass `-p no:logging` to `tests/ha`.** Every test using `caplog` then
  errors with "recursive dependency involving fixture 'caplog'", which reads
  like a broken test rather than a bad flag.
- **The Bash sandbox blocks all network.** Rig requests need
  `dangerouslyDisableSandbox`, and Tailscale up for the real rig, or the host
  times out rather than refusing.
- **Keep `uv sync` free of Home Assistant.** That is what makes the fast suite
  fast: `tests/unit/` and everything under `api/` import no `homeassistant`,
  and `api/errors.py` subclasses builtins only.
- Dependencies and the pytest, ruff and pyright config live in
  `pyproject.toml`; there is no `requirements*.txt` or `pytest.ini`.
  `pythonpath = ["tests", "."]`, so helpers import as `from helpers import ...`.

## Layout (current)

```
custom_components/nina_astrophotography/
  __init__.py         entry setup and unload, the socket wiring, and the
                      actions — registered in `async_setup`, so they exist
                      whether or not an entry is loaded, and resolve which rig
                      they mean from the device targeted
  api/                the version-independent seam: errors.py, models.py (THE CONTRACT)
  api/v2/             client.py (the only module that talks to N.I.N.A.), mapper.py
                      (wire → models; every sentinel dies here), schema.py (generated),
                      events.py (the event socket inside the seam; emits NinaEvent)
  coordinator.py      DataUpdateCoordinator publishing NinaData; owns frames/events
  entity.py           the shared entity base
  device.py           the hub and one device per equipment type; the only
                      writer of driver metadata into the device registry
  derive.py           pure maths; session.py the pure session fold;
                      sequence.py the pure /sequence/json walks
  polling.py          HA-free polling decisions: restart, reseed, tiers, event ledger
  const.py            domain, config keys, action names, enums
  config_flow.py      UI setup
  services.yaml       the action schemas the UI reads; strings.json and
                      translations/en.json must agree with it, field for field
  binary_sensor.py sensor.py number.py select.py light.py switch.py
  button.py image.py event.py   every platform is a table of entity
                      descriptors over NinaData; copy binary_sensor.py
  www/                6 Lovelace cards and four shared modules; see
                      docs/contributing/cards.md. `frontend.py` serves them and
                      registers each as a Lovelace resource
blueprints/automation/nina_astrophotography/   6 automation blueprints; entities
                      come from typed `!input` selectors, never hardcoded, and
                      each is instantiated for real in tests/ha/test_blueprints.py
tests/unit/                                    HA-free; tests/ha/ under PHACC
tests/scenarios/                               FakeRig — see its README
```

`PLATFORMS` in `__init__.py` is the list that is actually loaded; a module on
disk proves nothing.

## Entity rules

- **A platform is a descriptor table**, not a class per entity: a frozen
  dataclass carrying `value` (a lambda over `NinaData`), `kind` (the child
  device, `None` for the hub) and `verified`. Copy `binary_sensor.py`.
- **An entity is created only once its `kind`'s model is non-`None`**, and a
  listener adds the ones whose device appears later: `entity.async_add_observed`. A descriptor whose slot is
  absent must not be registered: it would mint a nameless device and take the
  wrong entity id. Every equipment platform needs that listener, even one with a
  single entity; gating only at setup misses equipment a sequence connects hours
  later. Test it by setting up with the device never observed, then refreshing
  with a captured snapshot where it is (`test_light.py`).
- **Observation is latched in memory, not persisted.** After a restart, a
  device that was down at setup shows restored `unavailable` registry rows
  until the rig reports it again.
- **A surviving entity keeps its 1.4.5 `unique_id`** through
  `unique_id_suffix`; only names and translation keys change. An orphaned
  registry row silently breaks the automation pointing at it — which for the
  safety monitor means a roof that does not close.
- **A destructive control ships enabled, and the card confirms it.** Home
  Assistant has no per-entity press confirmation, but a Lovelace `tap_action`
  takes a `confirmation:` block. Shipping the entity disabled instead only hides
  it from new installs while leaving upgraded registry rows enabled — and abort
  exposure is the emergency stop. Applies to abort exposure, clear guider
  calibration, park, dome close, sequence stop and the flat panel.
- **Every PR that renames anything a user references — an entity, an action
  field, a blueprint input — appends to `docs/2.0-renames.md`.**
- **`tests/ha/snapshots/` is the contract.** `test_snapshots.ambr` is the
  authoritative rename record and `entity_ids.txt` the plain list phase D reads.
  Regenerate them in their own commit, and reconcile both directions against
  `docs/2.0-renames.md` — ids the doc promises but the snapshot lacks are only
  legitimate for dome hardware and `"NaN"` weather channels.

## Testing

- `tests/unit/` — **no Home Assistant import.** Runs in milliseconds. Covers the
  API client, wire→model mapping, pure computations, and event parsing.
- `tests/ha/` — `pytest-homeassistant-custom-component`. Covers config flow,
  setup/unload, the device and entity registries, availability, and actions,
  against a **fake rig** (`tests/scenarios/`) serving captured envelopes to the
  real client.

Test through **public Home Assistant interfaces**: set up via
`hass.config_entries.async_setup`, assert via `hass.states`, `hass.services`,
and the registries. Do not reach into coordinator internals — tests that do stop
surviving refactors, which defeats the point during a restructure.

Wire data constructed rather than captured is marked `@pytest.mark.synthetic`.
Its docstring names what was fabricated only when the body does not show it — a
reading moved inside a scenario state, not an event list built in the test.

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

## Fixtures and the live rig

Fixtures are **recorded from real hardware**, never hand-written; trust the rig
over the published spec wherever they disagree. **Never send a live rig
anything but the read-only `GET` allowlist** in `docs/contributing/fixtures.md`
unless the operator has said it is idle — a rig may be imaging, and a wasted
night is not recoverable. A simulator rig is exempt. Redact before committing;
the pre-commit guard enforces it.

## Comments and docstrings

Keep both concise, and prefer explaining *why* over restating *what*. If the
code already makes it plain, it does not need saying.

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

**Test docstrings are held to the same bar.** The name says what the test
proves; a docstring adds only what the name and body cannot — why the behaviour
matters, or the API fact that makes it non-obvious. Most tests need none. Never
restate the name, the setup or the assertion.

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
- **The camera's setpoint is `TemperatureSetPoint`, not `TargetTemp`.**
  `TargetTemp` reads 0 whatever the camera is cooling to. A warm-up leaves the
  setpoint at its final value.
- **`/flats/status` only tracks flats started through the API** (`/flats/*`).
  Target Scheduler flats and the flat wizard leave it `Finished` / `-1`; they
  show up as FLAT frames in the image history. Rotator `Position` is the sky
  angle; `ROTATOR-MOVED` carries the mechanical angle.
- **Out-of-range input is silently clamped** and answers `Success: true`.
  Validate client-side and raise `ServiceValidationError` — schema validation
  raising `vol.Invalid` is not the same thing, and Home Assistant re-raises it
  as-is.
- **An action must not confirm from a command's own response.** It returns when
  N.I.N.A. accepts the command; the equipment moves seconds later, and no
  operation handle exists to wait on.

## Branches and quality

`main` is the trunk; every PR targets it, one branch per task, squash-merged.
Target the Home Assistant **Bronze** quality scale: 100% coverage on the config
flow, state on `entry.runtime_data`, and exemptions recorded with their reason
in `quality_scale.yaml`. Stacking, releases and the full Bronze list are in
`docs/contributing/pull-requests.md`.

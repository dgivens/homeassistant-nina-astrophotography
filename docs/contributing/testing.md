# Testing, CI and the rig tooling

The rules most test work needs are in `CLAUDE.md`; this holds the rest.

## Coverage floors and the redaction guard

```bash
# The coverage floors, exactly as CI computes them: each suite records its own
# data, `combine` merges them, and the script reads the JSON.
uv run coverage run -m pytest tests/unit -p no:homeassistant -q
uv run --group test-ha coverage run -m pytest tests/ha -q
uv run coverage combine && uv run coverage json
uv run python scripts/coverage_floors.py

uv run python scripts/check_fixtures.py tests/fixtures/*.json tests/fixtures/rig/*   # the redaction guard
```

## Dependencies, CI and linting

Dependencies and pytest config live in `pyproject.toml`; there is no
`requirements*.txt` and no `pytest.ini`. Groups: `test` (lean, HA-free),
`test-ha` (`pytest-homeassistant-custom-component`, pinned — add with
`uv sync --group test-ha`), `dev` (schema generator, pre-commit, pyright, ruff).

`pythonpath = ["tests", "."]` means helpers import as `from helpers import ...`.
CI is `.github/workflows/ci.yml` (both suites, coverage floors, ruff, pyright,
fixture redaction, hassfest, HACS). Ruff lints and formats with Home Assistant
core's rule set, minus the docstring rules that demand boilerplate or a
one-line summary — see `[tool.ruff]`; the pre-commit hooks run both.
Pyright's scope and rules are `[tool.pyright]` in `pyproject.toml`: it gates
`custom_components/`, `scripts/`, `tests/` and `tools/`, and turns off
`reportIncompatibleVariableOverride`, which every override of a Home Assistant
entity property trips.

Coverage is deliberately uneven — 100% on the config flow, high on the mapper
and the pure computation modules, no global percentage gate.

## The fake rig

The Home Assistant suite drives a **fake rig**: `tests/scenarios/` serves the
captured envelope for each endpoint to the real client, so the envelope
classification, the `"NaN"` rule and the mapper all run against recorded bytes.
`goto` and `advance` move it between named states, `push` feeds the event
socket, and `rig.sent` records commands — which are answered `Success: true`
and never confirm anything. Read `tests/scenarios/README.md` before writing a
test. Wire data constructed rather than captured is marked
`@pytest.mark.synthetic` and says in its docstring what it fabricates.

**`advance()` cannot reach a state that differs only in a tier-polled
endpoint** — `/profile/show`, `/livestack/status`,
`/equipment/focuser/last-af`. Every state but `imaging_guiding` withholds
those, so the coordinator's not-served latch fires at setup and one refresh
will not retry. Set the entry up with the rig already in the state instead
(the `set_up_at` fixture in `tests/ha/conftest.py`). The same applies to
`/event-history`, which is replayed once.

## Registry snapshots

**Registry snapshots live in `tests/ha/snapshots/`, and the extension is pinned
in `tests/ha/conftest.py`.** Syrupy and `pytest-homeassistant-custom-component`
both register a plugin fixture named `snapshot`, and pytest settles the clash by
entry-point load order — which is not stable across machines. Syrupy winning
stores under `__snapshots__/`, PHACC winning under `snapshots/`, so an unpinned
corpus recorded on one host is invisible on the next: every read misses, and the
same snapshots are reported both "does not exist" and "unused". Keep the
conftest fixture, which outranks both plugins.

## The simulated rig and the upgrade harness

`tools/upgrade-harness/` upgrades a throwaway Home Assistant in Docker from one
git ref to another against a N.I.N.A. and holds the result to
`docs/2.0-renames.md`; its README has the commands.

`docs/test-vm.md` designs the simulated rig: a disposable
Windows VM on macOS/Apple silicon running stable or nightly N.I.N.A. against
simulators. It also defines the `tests/rig/` tier. Host-specific code belongs
only in its host backend (§4.1 there). `tools/windows-rig/` builds and runs
it; its README has the commands, and a build needs `dangerouslyDisableSandbox`.

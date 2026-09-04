# Phase A · Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the test harness, the capture/generate/guard tooling and the
whole `api/` seam, and prove the shape end-to-end on one entity (`light.py`).

**Architecture:** A version-independent seam (`api/errors.py`, `api/models.py`)
with all wire knowledge under `api/v2/` — generated `TypedDict`s from a
committed OpenAPI spec, a client that unwraps the envelope and keys on the
body's `StatusCode`, and a mapper that turns wire dicts into frozen dataclasses
with every sentinel already normalized to `None`. Above the seam, a single
`DataUpdateCoordinator[NinaData]` and pure modules (`derive.py`, `session.py`)
that never see a dict. The test suite splits in two: a millisecond
Home-Assistant-free `tests/unit`, and `tests/ha` under
`pytest-homeassistant-custom-component`.

**Tech Stack:** Python 3.14.2, Home Assistant 2026.9.0, uv dependency groups,
pytest + pytest-asyncio, `pytest-homeassistant-custom-component`, syrupy,
hypothesis, `datamodel-code-generator`, GitHub Actions.

**Spec:** [`docs/v2.0-design.md`](../../v2.0-design.md) (Rev 4). Read §3, §4, §7
and §8 before starting. Section references below are to that document.

## Global Constraints

Every task's requirements implicitly include this section.

- **Branch.** All phase-A PRs target `v2`, cut from `main`. `wip/v2.0` is a
  read-only reference; **never merge or rebase it**.
- **min-HA is `2026.9.0`** (D-13). `hacs.json` declares it.
- **`requires-python = ">=3.14.2"`**, not `>=3.14` — uv resolves every group at
  lock time, so `homeassistant==2026.9.0`'s patch floor applies even to the lean
  install (§8.1).
- **Pin PHACC exactly:** `pytest-homeassistant-custom-component==0.13.363`. It
  hard-pins `homeassistant==2026.9.0`, `pytest==9.0.3`, `pytest-asyncio==1.4.0`,
  `syrupy==6.0.0`.
- **`syrupy==6.0.0` and `hypothesis` belong to the `test` group, not `dev`.** The
  drift guard and the fold properties both live in `tests/unit`, and the unit CI
  job installs `test` only. syrupy must match PHACC's pin exactly or the two
  groups cannot resolve into one lockfile.
- **`datamodel-code-generator==0.76.1`**, pinned — its output is committed.
- **`manifest.json` keeps `requirements: []`.** Every generator and test tool is
  dev-only; anything added to `[project].dependencies` would not be installed by
  Home Assistant.
- **Nothing under `api/`, `derive.py`, `session.py` or `const.py` imports
  `homeassistant`.** `api/errors.py` subclasses **builtins only** (§7.1).
- **No dicts and no wire vocabulary cross the `api/` boundary** (§4.1). §4.1's
  literal wording — "nothing above `api/` imports from `api/v2/`" — is violated
  by `coordinator.py`, `light.py`, `config_flow.py` and every phase-C command
  platform the moment they hold a client, and §4 defers `create_client()`, so
  nothing enforces it. **Amend §4.1 in Task A10's PR** to the rule that is both
  true and worth having: *the client type may be imported; wire data and wire
  vocabulary may not.* Task A2's seam guard gains a second assertion — no module
  above `api/` imports `api.v2.mapper` or `api.v2.schema`.
- **The blanket rule:** `"NaN"` → `None` across **every** numeric field, no
  allowlist (§4.2).
- **`HFR == 0` is the calibration marker → `None`. `Stars == -1` appears on
  flats but not darks** — normalize it, but never key calibration on it (§3.4).
- **Never generate request parameter names from the spec** (§3.2). Response
  shapes only. Request parameters are pinned by test.
- **Never pre-transform slew coordinates** — send J2000 in degrees (§3.7).
- **No command on this API can be confirmed from its own response** (§3.5). Read
  state back from the poll, never from the command's reply.
- **Session aggregate scope.** `image_count` counts **every** frame;
  `light_count`, `integration_seconds`, `by_target`, `by_filter`, every HFR
  aggregate and `star_count_mean` are over `image_type == "LIGHT"` **only**.
  Measured on the captured night: all 122 frames sum to 6.2301 h and carry six
  filters; the 55 lights sum to 6.2000 h and carry five. Integration time is
  light-frame time — a per-filter breakdown containing a G flat with no G lights
  is noise.
- **Calibration is keyed on `ImageType`, not on `HFR == 0`.** `ImageType` is
  present on **both** paths (`/image-history` frames and the `IMAGE-SAVE`
  payload). `HFR == 0` stays as a secondary null-out *within* light frames, so a
  light shot through thick cloud keeps its `stars: 0` — the single most
  diagnostic reading of a clouded-out sub. Keying calibration on `HFR == 0`
  alone would discard it.
- **Every `NinaEvent.time` is offset-aware.** Log-scraped `ERROR-*` timestamps
  are naive local; left naive they crash `fold`'s sorted iteration the first
  time an `ERROR-PLATESOLVE` lands beside 600 offset-aware events. The mapper
  stamps them with the rig offset learned from
  `Mount.Coordinates.DateTime.{Now,UtcNow}`.
- **Coverage floors** (§8.7): `config_flow.py` 100, `derive.py` 95,
  `session.py` 95, `api/v2/mapper.py` 90. `branch = true`. No global gate. A
  floor for a module that does not exist yet lives in `PENDING`, printed as a
  warning; `PENDING` must be empty by D5.
- **Do not run the HA suite under `-n auto`** (§8.8).
- **Every PR is green.** The branch is not required to boot (§9, D-10).
- **Amendment rule.** A PR that contradicts the spec amends it in the same PR
  and bumps the rev in its header.

## Spec amendments this phase makes

Each is carried by the PR that first needs it, per the amendment rule. The last
three were found by running the plan's own code against the captured corpus.

1. **§12's phase-A exit criterion** says "no file under `custom_components/`
   changed except new `api/` scaffolding and `light.py`". That contradicts §9,
   which puts `coordinator.py`, `entity.py` and `runtime_data` in phase A.
   Amend it to: *no **platform** module changed except `light.py`*.
2. **`PLATFORMS` narrows to `[Platform.LIGHT]` for phases A–B**, and each
   platform is re-added by the phase-C PR that migrates it. The unmigrated
   platform modules stay on disk, unregistered. §9's "tests green, not bootable"
   rule permits leaving them broken, but an unregistered platform costs nothing
   and keeps the HA suite meaningful from phase A onward. Record it in §9.

3. **§3.2's `MountInfo.TrackingMode` row is wrong.** It says the wire sends
   `null` when disconnected. It does not: the key is **absent**, together with
   13 others — `Coordinates`, `DeviceId`, `Name`, `DisplayName`, `TrackingModes`,
   `PrimaryAxisRates`, `SecondaryAxisRates`, `SupportedActions` and the five
   `*String` fields. The connected Mount carries 51 keys, the disconnected one
   37. Correct the row in Task A7's PR.
4. **§8.5's justification for the whole-corpus rule is wrong for the same
   reason** — it cites nullability. The real reason is key presence, which is a
   stronger argument: a single-fixture guard records whichever half it read and
   calls the other half drift.
5. **§5.2.2's first-sight rule needs a definition of "observed".**
   `/equipment/info` always emits all eleven device blocks, including a full
   `Dome` block on a rig that has never had one, so block presence proves
   nothing. A device is observed once it has carried a `DeviceId` — which
   disconnection removes, so the coordinator latches it. Record this in §5.2.2
   in Task A9's PR.

Services keep the old `api.py` client through phases A–B (§9 puts service work
in D, but phase C's last PR deletes `api.py` — so C's last PR ports the service
call sites mechanically; D redesigns them). `runtime_data` therefore carries two
clients for the interregnum. This is **not** the `NinaData.legacy` field D-10
rejects — no compatibility shape enters the snapshot.

## File structure

| File | Responsibility |
|---|---|
| `custom_components/nina_astrophotography/api/__init__.py` | Re-export the error taxonomy. Nothing else. |
| `…/api/errors.py` | Five exception types. Subclasses builtins only. |
| `…/api/models.py` | Frozen dataclasses — **the contract**. Sized by what entities consume. |
| `…/api/v2/__init__.py` | Re-export `NinaClientV2`. |
| `…/api/v2/schema.py` | **Generated, committed.** `TypedDict`s from the spec. Never hand-edited. |
| `…/api/v2/client.py` | Paths, envelope unwrapping, `StatusCode` keying, "no data yet" → `None`/`[]`. |
| `…/api/v2/mapper.py` | Wire → models. Every sentinel, timezone and quirk dies here. |
| `…/derive.py` | Pure, version-independent maths. No wire vocabulary. |
| `…/session.py` | `fold(frames, events, generation) -> SessionStats`. Stateless. |
| `…/coordinator.py` | `NinaCoordinator(DataUpdateCoordinator[NinaData])`. Owns the accumulated sets. |
| `…/entity.py` | `NinaEntity` base — `has-entity-name`, device linking, availability. |
| `…/light.py` | Rewritten: the vertical slice, carrying §5.3.4's three fixes. |
| `tests/unit/` | No HA import. Milliseconds. |
| `tests/ha/` | PHACC. Public interfaces only. |
| `tests/redaction.py` | Redaction rules, shared by the capture script and the guard. |
| `tests/spec_deviations.json` | Committed waivers — one entry per §3.2 row. |
| `scripts/capture_fixtures.py` | Read-only capture + redact. |
| `scripts/generate_schema.sh` | Spec → `api/v2/schema.py`, reproducibly. |
| `scripts/measure_payloads.sh` | Re-measure §3.3 like-for-like. |
| `scripts/coverage_floors.py` | Per-file floors from `coverage json`. |
| `.github/workflows/ci.yml` | Four jobs: unit, ha, hassfest, HACS. |
| `.pre-commit-config.yaml` | Redaction guard before the commit, not after the push. |

---

## Task A1: Split the test harness

**Files:**
- Create: `tests/unit/__init__.py` (empty), `tests/unit/conftest.py`, `tests/ha/conftest.py`, `tests/ha/test_smoke.py`
- Move: all 17 files matching `tests/test_*.py` → `tests/unit/`
- Modify: `tests/conftest.py` (emptied of the stub), `pyproject.toml`
- Test: `tests/ha/test_smoke.py`

**Interfaces:**
- Produces: `tests/unit/` and `tests/ha/` as separate, separately-invoked
  suites; `pytest tests/unit -p no:homeassistant` and `pytest tests/ha`.

- [ ] **Step 1: Move the existing tests, unchanged**

```bash
mkdir -p tests/unit tests/ha
git mv tests/test_*.py tests/unit/
touch tests/unit/__init__.py tests/ha/__init__.py
```

- [ ] **Step 2: Move the import stub to `tests/unit/conftest.py`**

Cut the whole body of `tests/conftest.py` into `tests/unit/conftest.py` and
leave `tests/conftest.py` holding only a docstring. The stub must **not** apply
to the HA suite: it registers a top-level `nina_astrophotography` module while
Home Assistant loads the integration as
`custom_components.nina_astrophotography`, so applying both imports the same
source twice and `pytest.raises(NinaConnectionError)` fails incomprehensibly
(§8.0).

`tests/unit/conftest.py`:

```python
"""Registers the integration package for import, for the HA-free suite only.

The modules under test import no Home Assistant code, so these tests run with
`uv sync` and no HA checkout. The integration's `__init__.py` does import Home
Assistant, so the package is registered here with its `__path__` set but never
executed — submodules and their relative imports still resolve.

This must not apply to tests/ha: Home Assistant loads the integration as
`custom_components.nina_astrophotography`, and registering it under a second
name would import the same source twice into two distinct class objects.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "nina_astrophotography"
)

if "nina_astrophotography" not in sys.modules:
    _pkg = types.ModuleType("nina_astrophotography")
    _pkg.__path__ = [str(_COMPONENT)]
    sys.modules["nina_astrophotography"] = _pkg
```

`tests/conftest.py` becomes:

```python
"""Root conftest.

Deliberately empty of fixtures. The two suites are independent: tests/unit runs
without Home Assistant, tests/ha runs under pytest-homeassistant-custom-component.
Shared *data* helpers live in tests/helpers.py, which imports neither.
"""
```

- [ ] **Step 3: Guard the stub in `tests/ha/conftest.py`**

```python
"""Fixtures for the Home-Assistant-dependent suite."""
from __future__ import annotations

import sys

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import (
    CONF_HOST,
    CONF_PORT,
    DOMAIN,
)


def pytest_collection_modifyitems(config, items):
    """Fail loudly if tests/unit's import stub has leaked into this suite.

    Both suites importing the same source under two module names produces two
    distinct class objects, so `pytest.raises(NinaConnectionError)` fails with
    an error that names the same class twice.
    """
    if "nina_astrophotography" in sys.modules:
        pytest.exit(
            "tests/unit's import stub leaked into tests/ha — run the suites "
            "separately",
            returncode=1,
        )


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """PHACC requires this opt-in before a custom component will load."""
    return


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="N.I.N.A.",
        data={CONF_HOST: "nina.local", CONF_PORT: 1888},
        entry_id="01JTESTENTRY0000000000000",
    )
```

- [ ] **Step 4: Write the harness smoke test**

`tests/ha/test_smoke.py` proves PHACC loads the custom component at all. It does
not set up an entry yet — that arrives in Task A15.

```python
"""The HA harness itself works: the custom component is discoverable."""
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.nina_astrophotography.const import DOMAIN


async def test_integration_is_loadable(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.config_flow is True
```

- [ ] **Step 5: Configure both suites in `pyproject.toml`**

Drop `testpaths` so a bare `pytest` cannot silently mix the suites (§8.1). Add
the `ha` marker-free split by invocation, not by config.

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
# tests/ on sys.path so `from helpers import ...` works under any import mode.
pythonpath = ["tests"]
# No testpaths: `pytest` with no argument must not mix the two suites. The unit
# suite runs HA-free, the ha suite runs under PHACC, and loading PHACC's
# pytest11 entry point imports Home Assistant before collection.
```

- [ ] **Step 6: Run both suites**

```bash
uv run pytest tests/unit -p no:homeassistant -q
uv sync --group test-ha
uv run pytest tests/ha -q
```

Expected: 101 passed for `tests/unit`; 1 passed for `tests/ha`.

- [ ] **Step 7: Commit**

```bash
git add tests pyproject.toml
git commit -m "test: split the suite into HA-free unit and HA-dependent halves"
```

---

## Task A2: The seam guard

**Files:**
- Create: `tests/unit/test_seam.py`
- Test: itself

**Interfaces:**
- Consumes: nothing.
- Produces: a static guarantee that `api/`, `derive.py`, `session.py` and
  `const.py` — plus the transitive closure of their first-party imports — never
  import `homeassistant`.

- [ ] **Step 1: Write the failing test**

The guard is **static, not runtime**. PHACC registers a `pytest11` entry point
named `homeassistant` whose module imports Home Assistant 22 times at import
scope, and pytest loads entry points before collection — so
`"homeassistant" not in sys.modules` fails unconditionally once PHACC is
installed (§8.1).

```python
"""The seam holds: nothing HA-free imports Home Assistant.

Static, not runtime. Once pytest-homeassistant-custom-component is installed its
pytest11 entry point imports Home Assistant before collection, so a sys.modules
check can never pass.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "nina_astrophotography"
)

SEAM_ROOTS = ("api", "derive.py", "session.py", "const.py")


def _seam_files() -> set[Path]:
    """Every seam module plus the transitive closure of its own imports."""
    pending = set()
    for root in SEAM_ROOTS:
        target = COMPONENT / root
        pending.update(target.rglob("*.py") if target.is_dir() else {target})

    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for name in _first_party_imports(path):
            candidate = COMPONENT / (name.replace(".", "/") + ".py")
            package = COMPONENT / name.replace(".", "/") / "__init__.py"
            pending.update(p for p in (candidate, package) if p.exists())
    return seen


def _first_party_imports(path: Path) -> set[str]:
    """Relative-import targets, resolved to dotted paths under the component."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = path.relative_to(COMPONENT).parent.as_posix().replace("/", ".")
    package = "" if package == "." else package
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            parts = package.split(".") if package else []
            parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
            base = ".".join(p for p in [*parts, node.module or ""] if p)
            found.add(base)
            found.update(f"{base}.{alias.name}" if base else alias.name
                         for alias in node.names)
    return found


@pytest.mark.parametrize("path", sorted(_seam_files()), ids=lambda p: p.name)
def test_seam_module_does_not_import_homeassistant(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names = [node.module or ""]
        else:
            continue
        assert not any(n == "homeassistant" or n.startswith("homeassistant.")
                       for n in names), f"{path.name} imports Home Assistant"


def test_seam_guard_sees_the_modules_it_claims_to() -> None:
    """A guard that collects nothing passes vacuously."""
    assert {"const.py"} <= {p.name for p in _seam_files()}


def test_nothing_above_the_seam_imports_the_wire_layer() -> None:
    """The client TYPE may be imported; the mapper and the generated schema may
    not. Holding a NinaClientV2 is not knowing a wire format — calling
    map_equipment_info, or naming a TypedDict, is.
    """
    above = [p for p in COMPONENT.rglob("*.py")
             if "api" not in p.relative_to(COMPONENT).parts]
    offenders = [
        p.name for p in above
        if any(m in p.read_text(encoding="utf-8")
               for m in ("api.v2.mapper", "api.v2.schema",
                         "from .api.v2.mapper", "from .api.v2.schema"))
    ]
    assert not offenders, f"wire layer imported above the seam: {offenders}"
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/unit/test_seam.py -v
```

Expected: PASS for `const.py`; `api`, `derive.py` and `session.py` do not exist
yet, so only `const.py` is collected. That is why
`test_seam_guard_sees_the_modules_it_claims_to` exists.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_seam.py
git commit -m "test: guard the seam statically against Home Assistant imports"
```

---

## Task A3: CI and the coverage floors

**Files:**
- Create: `.github/workflows/ci.yml`, `scripts/coverage_floors.py`
- Modify: `pyproject.toml` (`[tool.coverage.*]`)

**Interfaces:**
- Consumes: Task A1's two suites, Task A2's seam guard.
- Produces: four green CI jobs; `python scripts/coverage_floors.py` exits
  non-zero when a floor is breached.

- [ ] **Step 1: Write the floors script**

coverage.py has no per-file threshold, so read `coverage json` (§8.7).

```python
#!/usr/bin/env python3
"""Enforce per-file coverage floors.

coverage.py has no per-file threshold and this project has no global gate:
coverage is deliberately uneven. Reads coverage.json, written by
`coverage json` after `coverage combine`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FLOORS = {
    "derive.py": 95,
    "session.py": 95,
    "api/v2/mapper.py": 90,
}

# Floors for modules a later phase creates. Printed as a warning, never a
# failure — a required job that is knowingly red for two phases trains everyone
# to ignore it. B7 promotes config_flow.py into FLOORS; D5 asserts PENDING empty.
PENDING = {"config_flow.py": 100}

PREFIX = "custom_components/nina_astrophotography/"


def main() -> int:
    report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
    files = report["files"]
    failures = []
    for relative, floor in FLOORS.items():
        key = PREFIX + relative
        if key not in files:
            failures.append(f"{relative}: not measured — the floor is unenforced")
            continue
        actual = files[key]["summary"]["percent_covered"]
        if actual + 1e-9 < floor:
            failures.append(f"{relative}: {actual:.1f}% < {floor}%")
    for relative, floor in PENDING.items():
        print(f"coverage floor pending (not enforced): {relative} >= {floor}%",
              file=sys.stderr)
    for line in failures:
        print(f"coverage floor breached: {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Test the script against a synthetic report**

`tests/unit/test_coverage_floors.py`:

```python
"""The floors script fails on a breach and on an unmeasured file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import coverage_floors  # noqa: E402

PREFIX = coverage_floors.PREFIX


def _report(tmp_path: Path, files: dict[str, float]) -> None:
    (tmp_path / "coverage.json").write_text(json.dumps({
        "files": {PREFIX + name: {"summary": {"percent_covered": pct}}
                  for name, pct in files.items()}
    }), encoding="utf-8")


def test_a_met_floor_passes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _report(tmp_path, {"derive.py": 96.0, "session.py": 95.0,
                       "api/v2/mapper.py": 90.0})
    assert coverage_floors.main() == 0


def test_a_breached_floor_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _report(tmp_path, {"derive.py": 94.9, "session.py": 95.0,
                       "api/v2/mapper.py": 90.0})
    assert coverage_floors.main() == 1


def test_an_unmeasured_file_fails_rather_than_passing_silently(
    tmp_path, monkeypatch
) -> None:
    """An unenforced floor is worse than no floor."""
    monkeypatch.chdir(tmp_path)
    _report(tmp_path, {"derive.py": 96.0, "session.py": 95.0})
    assert coverage_floors.main() == 1
```

Run:

```bash
uv run pytest tests/unit/test_coverage_floors.py -v
```

Expected: three PASS. The floors job is green from this commit onward, because
`config_flow.py` sits in `PENDING` until B7 promotes it.

- [ ] **Step 3: Write the workflow**

```yaml
name: CI

on:
  push:
    branches: [main, v2]
  pull_request:

jobs:
  unit:
    name: Unit suite (HA-free)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync
      # -p no:homeassistant makes the runtime half of the seam guard meaningful
      # as a secondary; tests/unit/test_seam.py is the real check.
      - run: uv run coverage run -m pytest tests/unit -p no:homeassistant -q
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-unit
          path: .coverage.*
          include-hidden-files: true

  ha:
    name: Home Assistant suite
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - run: uv sync --group test-ha
      # No -n auto: pytest-socket is active under PHACC and the push path
      # creates tasks outside the test's control.
      - run: uv run coverage run -m pytest tests/ha -q
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-ha
          path: .coverage.*
          include-hidden-files: true

  coverage:
    name: Coverage floors
    needs: [unit, ha]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - uses: actions/download-artifact@v4
        with:
          pattern: coverage-*
          merge-multiple: true
      - run: uv sync --group test-ha
      - run: uv run coverage combine
      - run: uv run coverage json
      - run: uv run python scripts/coverage_floors.py

  hassfest:
    name: hassfest
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: home-assistant/actions/hassfest@master

  hacs:
    name: HACS validation
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hacs/action@main
        with:
          category: integration

  fixtures:
    name: Fixture redaction
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      # The backstop. The pre-commit hook (Task A6) is the actual guard: CI
      # fires after the push, by which time a leaked credential is permanent.
      - run: uv run python scripts/check_fixtures.py tests/fixtures/*.json
```

The `fixtures` job references `scripts/check_fixtures.py`, which Task A6
creates. Until then the job is red — so add this job in **A6's** commit, not
this one, and write the other five here.

- [ ] **Step 4: Add coverage config**

```toml
[tool.coverage.run]
branch = true
parallel = true
source = ["custom_components/nina_astrophotography"]

[tool.coverage.paths]
# The two suites import the integration under different names; combine must
# treat them as one file or every per-file floor reads zero.
component = [
    "custom_components/nina_astrophotography",
    "*/custom_components/nina_astrophotography",
]
```

- [ ] **Step 5: Commit**

```bash
git add .github scripts/coverage_floors.py pyproject.toml
git commit -m "ci: run both suites, hassfest, HACS and per-file coverage floors"
```

---

## Task A4: `scripts/measure_payloads.sh`

**Files:**
- Create: `scripts/measure_payloads.sh`

**Interfaces:**
- Produces: a byte-count table comparable with §3.3, so post-2.0 comparisons are
  like-for-like.

- [ ] **Step 1: Write the script**

Read-only. Every path here reports state; none commands equipment.

```bash
#!/usr/bin/env bash
# Re-measure the payload sizes in docs/v2.0-design.md §3.3.
#
# READ-ONLY. Every endpoint below reports state. Never add one that commands
# equipment — a rig may be imaging, and a wasted night is not recoverable.
#
#   scripts/measure_payloads.sh <host> [port]
set -euo pipefail

HOST="${1:?usage: measure_payloads.sh <host> [port]}"
PORT="${2:-1888}"
BASE="http://${HOST}:${PORT}/v2/api"

PATHS=(
  "/version"
  "/application-start"
  "/equipment/info"
  "/sequence/json"
  "/sequence/state"
  "/image-history?count=true"
  "/image-history"
  "/image-history?all=true"
  "/event-history"
  "/flats/status"
  "/livestack/status"
  "/equipment/focuser/last-af"
)

printf '%-34s %10s\n' "endpoint" "bytes"
for path in "${PATHS[@]}"; do
  bytes=$(curl -sS --max-time 30 "${BASE}${path}" | wc -c | tr -d ' ')
  printf '%-34s %10s\n' "$path" "$bytes"
done
```

- [ ] **Step 2: Make it executable and shellcheck it**

```bash
chmod +x scripts/measure_payloads.sh
uv run --with shellcheck-py shellcheck scripts/measure_payloads.sh
```

Expected: no findings.

- [ ] **Step 3: Commit**

```bash
git add scripts/measure_payloads.sh
git commit -m "chore: add the payload measurement script referenced by the design"
```

---

## Task A5: Commit the OpenAPI spec and generate `schema.py`

**Files:**
- Create: `docs/v2.0/ninaapi-v2-openapi.json`, `scripts/generate_schema.sh`,
  `custom_components/nina_astrophotography/api/__init__.py`,
  `custom_components/nina_astrophotography/api/v2/__init__.py`,
  `custom_components/nina_astrophotography/api/v2/schema.py`
- Test: `tests/unit/test_schema_is_regenerable.py`

**Interfaces:**
- Produces: `api/v2/schema.py` exporting one `TypedDict` per documented
  response body — `CameraInfo`, `MountInfo`, `FocuserInfo`, `FilterWheelInfo`,
  `GuiderInfo`, `RotatorInfo`, `DomeInfo`, `FlatDeviceInfo`, `WeatherInfo`,
  `SafetyMonitorInfo`, `SwitchInfo`, `ImageHistoryItem`, `EventHistoryItem`,
  `SequenceNodeWire`, `FlatsStatusWire`, `LivestackStatusWire`, `AutoFocusRun`.
  Consumed by `api/v2/client.py` (Task A10) as return annotations only.

- [ ] **Step 1: Commit the spec**

Fetch the Advanced API's OpenAPI document from the running plugin and commit it
verbatim. It is an input artifact, not documentation — do not reformat it.

```bash
curl -sS "http://${NINA_HOST}:1888/swagger/v2/swagger.json" \
  | python -m json.tool --sort-keys > docs/v2.0/ninaapi-v2-openapi.json
```

If the plugin does not serve the document, take it from the ninaAPI release
matching **2.2.15.2** and record the source URL in a comment at the top of
`scripts/generate_schema.sh`. The version the spec was taken from must match the
`api_version` in the fixtures' `_meta` (Task A6).

- [ ] **Step 2: Write the generator script**

```bash
#!/usr/bin/env bash
# Regenerate custom_components/nina_astrophotography/api/v2/schema.py.
#
# The output is COMMITTED and a test diffs against it, so the generator is
# pinned in pyproject's `dev` group. Never hand-edit schema.py.
#
# Source: ninaAPI 2.2.15.2 OpenAPI document, committed at
# docs/v2.0/ninaapi-v2-openapi.json.
#
# The spec is reliable about response field NAMES and unreliable about types,
# enum values and request parameter names — see design §3.2. Generated types are
# a drift *detector*, not a source of truth; tests/spec_deviations.json records
# every place the wire disagrees.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${ROOT}/custom_components/nina_astrophotography/api/v2/schema.py"

uv run --group dev datamodel-codegen \
  --input "${ROOT}/docs/v2.0/ninaapi-v2-openapi.json" \
  --input-file-type openapi \
  --output "${OUT}" \
  --output-model-type typing.TypedDict \
  --target-python-version 3.13 \
  --use-standard-collections \
  --use-union-operator \
  --disable-timestamp \
  --custom-file-header "# GENERATED by scripts/generate_schema.sh — do not edit."

echo "wrote ${OUT}"
```

`--target-python-version 3.13` is the newest `datamodel-code-generator` 0.76.1
accepts; the output is valid on 3.14. `--disable-timestamp` is what makes the
result byte-reproducible.

- [ ] **Step 3: Generate and inspect**

```bash
chmod +x scripts/generate_schema.sh
mkdir -p custom_components/nina_astrophotography/api/v2
scripts/generate_schema.sh
head -40 custom_components/nina_astrophotography/api/v2/schema.py
```

Expected: a header comment and `TypedDict` classes. If the generator emits
Pydantic models instead, `--output-model-type` was dropped — the seam guard
would then fail on a third-party import, which is the intended backstop.

- [ ] **Step 4: Write the package inits**

`api/__init__.py`:

```python
"""Version-independent client seam.

Nothing above this package knows a wire format, and no dict crosses this
boundary. Everything that does live under api/<version>/.
"""
from .errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaError,
    NinaRequestError,
    NinaUnavailableError,
)

__all__ = [
    "NinaCommandError",
    "NinaConnectionError",
    "NinaEndpointError",
    "NinaError",
    "NinaRequestError",
    "NinaUnavailableError",
]
```

`api/v2/__init__.py`:

```python
"""ninaAPI v2 (2.2.15.x)."""
from .client import NinaClientV2

__all__ = ["NinaClientV2"]
```

These import modules that do not exist until Tasks A8 and A10. Write them in
this task but expect the import to fail until then; A8 lands `errors.py` and A10
lands `client.py`, in that order.

- [ ] **Step 5: Write the regenerability test**

```python
"""schema.py is exactly what the committed spec generates.

A hand-edit to a generated file is invisible in review and survives forever.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "custom_components" / "nina_astrophotography" / "api" / "v2" / "schema.py"


@pytest.mark.slow
def test_schema_regenerates_byte_identically(tmp_path: Path) -> None:
    before = SCHEMA.read_bytes()
    subprocess.run([str(ROOT / "scripts" / "generate_schema.sh")], check=True, cwd=ROOT)
    after = SCHEMA.read_bytes()
    if before != after:
        SCHEMA.write_bytes(before)
        pytest.fail("schema.py differs from what the committed spec generates")


def test_schema_carries_the_generated_header() -> None:
    assert SCHEMA.read_text(encoding="utf-8").startswith(
        "# GENERATED by scripts/generate_schema.sh"
    )
```

Register the marker in `pyproject.toml` so it can be deselected locally:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["tests"]
markers = [
    "slow: shells out to a generator; deselect with -m 'not slow'",
]
```

- [ ] **Step 6: Run**

```bash
uv run pytest tests/unit/test_schema_is_regenerable.py -v
```

Expected: both PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/v2.0/ninaapi-v2-openapi.json scripts/generate_schema.sh \
        custom_components/nina_astrophotography/api pyproject.toml \
        tests/unit/test_schema_is_regenerable.py
git commit -m "feat: commit the ninaAPI v2 spec and generate the wire types from it"
```

---

## Task A6: Capture and redaction

**Files:**
- Create: `tests/redaction.py`, `scripts/capture_fixtures.py`,
  `.pre-commit-config.yaml`, `tests/unit/test_redaction.py`
- Modify: every file in `tests/fixtures/` (add `_meta`),
  `tests/fixtures/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `tests.redaction.redact(value: Any, *, path: str = "") -> Any` — recursive,
    type-preserving.
  - `tests.redaction.scan(value: Any) -> list[str]` — dotted paths that still
    look sensitive. Empty means clean.
  - `tests.redaction.PROFILE_ALLOWLIST: tuple[str, ...]` — the dotted paths
    `/profile/show` is projected down to.
  - Fixtures carrying `_meta: {captured_at, nina_version, api_version, endpoint,
    params}` (§8.7), stripped before type-checking.

- [ ] **Step 1: Write the failing redaction test**

```python
"""Redaction rules — one module, shared by the capture script and the guard."""
from __future__ import annotations

import pytest

from redaction import PROFILE_ALLOWLIST, redact, scan


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"WeatherUndergroundAPIKey": "abc"}, {"WeatherUndergroundAPIKey": "REDACTED"}),
        ({"apikey": "abc"}, {"apikey": "REDACTED"}),
        ({"ImageFilePath": "C:\\Astro"}, {"ImageFilePath": "REDACTED"}),
        ({"Note": "C:\\Users\\dan\\N.I.N.A."}, {"Note": "REDACTED"}),
        ({"Note": "192.168.1.40"}, {"Note": "REDACTED"}),
        ({"Note": "sensor.observatory_roof"}, {"Note": "REDACTED"}),
        # Site and pointing fields are KEPT — see the module docstring.
        ({"SiteLatitude": 41.87}, {"SiteLatitude": 41.87}),
        ({"Altitude": 31.5478}, {"Altitude": 31.5478}),
        ({"SiderealTime": 5.4761}, {"SiderealTime": 5.4761}),
        ({"SideOfPier": "pierEast"}, {"SideOfPier": "pierEast"}),
        ({"TelescopeName": "Esprit 100"}, {"TelescopeName": "Telescope"}),
        ({"TargetName": "NGC 281"}, {"TargetName": "NGC 281"}),
    ],
)
def test_redacts_by_rule(payload: dict, expected: dict) -> None:
    assert redact(payload) == expected


def test_redaction_preserves_json_type() -> None:
    """A type-aware drift guard must check N.I.N.A.'s output, not the redactor's."""
    assert redact({"LastDownloadTime": 3.0, "ApiKey": None}) == {
        "LastDownloadTime": 3.0,
        "ApiKey": None,
    }


def test_device_ids_become_stable_distinct_pseudonyms() -> None:
    payload = {"a": {"DeviceId": "ASCOM.X"}, "b": {"DeviceId": "ASCOM.Y"},
               "c": {"DeviceId": "ASCOM.X"}}
    out = redact(payload)
    assert out["a"]["DeviceId"] == out["c"]["DeviceId"] != out["b"]["DeviceId"]
    assert out["a"]["DeviceId"].startswith("device-")


def test_filenames_become_stable_pseudonyms_not_positions() -> None:
    frames = [{"Filename": "D:\\a\\M31_001.fits"}, {"Filename": "D:\\a\\M31_002.fits"}]
    out = [f["Filename"] for f in redact(frames)]
    assert out[0] != out[1]
    assert all(name.startswith("frame_") and name.endswith(".fits") for name in out)


def test_scan_finds_what_redact_would_change() -> None:
    assert scan({"Outer": {"ApiKey": "live"}}) == ["Outer.ApiKey"]


def test_scan_is_clean_after_redaction_by_construction() -> None:
    """redact() is idempotent, so this cannot be satisfied by an escape hatch."""
    assert scan(redact({"Outer": {"ApiKey": "live"}, "DeviceId": "ASCOM.X"})) == []


def test_a_redacted_container_stays_a_container() -> None:
    """Type preservation covers dicts and lists, not only scalars — otherwise a
    dict under a key containing "path" becomes the string "REDACTED"."""
    out = redact({"ImagePathSettings": {"Enabled": True}})
    assert isinstance(out["ImagePathSettings"], dict)


def test_the_meridian_flip_inputs_survive_redaction() -> None:
    """SiderealTime is §11's LST input, and RightAscension its RA.

    A redactor that zeroes either leaves (RA - LST) mod 12 with no captured
    fixture to test against, and the only alternative is a hand-written
    synthetic triple — which the fixture rules forbid. Pinned so a later
    "tightening" cannot break the maths silently.
    """
    mount = {"SiteLatitude": 31.5478, "SiderealTime": 21.021944,
             "RightAscension": 22.071111, "SideOfPier": "pierWest"}
    assert redact(mount) == mount


def test_a_frame_keeps_one_identity_across_files() -> None:
    """Frame identity is (Date, Filename) and the fold spans fixtures, so a
    per-file counter both collides distinct frames and splits identical ones."""
    a = redact({"Filename": "D:\\astro\\M31_014.fits"})
    b = redact({"Other": 1, "Filename": "D:\\astro\\M31_014.fits"})
    c = redact({"Filename": "D:\\astro\\M31_015.fits"})
    assert a["Filename"] == b["Filename"] != c["Filename"]


def test_profile_allowlist_is_the_projection_not_a_denylist() -> None:
    """/profile/show is captured as a projection — its secret surface is too
    large to redact confidently."""
    assert "TelescopeSettings.FocalLength" in PROFILE_ALLOWLIST
    assert "CameraSettings.PixelSize" in PROFILE_ALLOWLIST
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/unit/test_redaction.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'redaction'`.

- [ ] **Step 3: Implement `tests/redaction.py`**

Matching is **case-insensitive** and redaction **preserves JSON type** (§8.3).

```python
"""Redaction rules for captured fixtures.

Imported by both scripts/capture_fixtures.py and the pre-commit guard so the two
cannot drift. A fixture is committed to a public repository; a profile dump
contains live credentials.

Two rules that are easy to get wrong:

**Redaction preserves the JSON type, containers included.** A string becomes
"REDACTED", a number 0, a null stays null, and a dict stays a dict — otherwise
the type-aware drift guard checks this module's output rather than N.I.N.A.'s,
and a whole settings subtree under a key containing "path" collapses to a
string.

**Site coordinates are kept, deliberately.** The rig is hosted at a public
commercial facility and the owner is content for the repository to show it, so
latitude, longitude, elevation and the pointing fields that reconstruct them
(Altitude at Dec 90, SiderealTime against Coordinates.DateTime.UtcNow) all stay
real. That is not laxity — SiderealTime is the input to the meridian-flip maths
in §11, and zeroing it would leave that formula with no captured fixture to test
against and force a hand-written substitute, which the fixture rules forbid.

Credentials, absolute paths, hostnames, IPv4 addresses, UUIDs and Home Assistant
entity ids are a different matter and are still redacted.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

REDACTED = "REDACTED"

# Substring match on the lowercased key.
_SECRET_KEYS = ("key", "token", "secret", "password", "credential")
_LOCATION_KEYS = ("path", "folder", "directory", "host", "url")

_RENAMED = {"telescopename": "Telescope", "cameraname": "Camera"}
_PSEUDONYM_KEYS = ("deviceid", "entityid")

# Kept deliberately, and asserted by test so a later "tightening" cannot quietly
# break the maths that depends on them:
#   TargetName    an astronomical object, not identifying
#   SideOfPier    not identifying; §11's already-flipped branch needs it
#   site + pointing fields   the site is a public hosting facility, and
#                            SiderealTime is §11's LST input
_KEEP = (
    "targetname", "sideofpier",
    "sitelatitude", "sitelongitude", "siteelevation",
    "latitude", "longitude", "elevation",
    "altitude", "altitudestring", "siderealtime", "siderealtimestring",
)

_VALUE_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),                                  # Windows path
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                  # bare IPv4
    re.compile(r"\b[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}\b", re.I),  # UUID
    re.compile(r"\b(?:sensor|binary_sensor|switch|light|number|select|button|"
               r"image|event|camera|climate|cover)\.[a-z0-9_]+\b"),  # HA entity id
)

# Site or facility identifiers seen in device Name/DisplayName/Description.
_FACILITY = re.compile(r"observator|datacent|building|suite|rack|colo", re.I)
_NAME_KEYS = ("name", "displayname", "description")

# /profile/show is captured as an allowlist PROJECTION, not a redaction — its
# secret surface is too large to redact confidently. §8.3.
PROFILE_ALLOWLIST: tuple[str, ...] = (
    "TelescopeSettings.FocalLength",
    "FocuserSettings.AutoFocusTimeoutSeconds",
    "FocuserSettings.RSquaredThreshold",
    "MeridianFlipSettings",
    "CameraSettings.PixelSize",
)


def _digest(value: str, prefix: str, width: int, suffix: str = "") -> str:
    """A stable pseudonym derived from the value, not from arrival order.

    Order-derived numbering is wrong for Filename: frame identity is
    (Date, Filename) and the fold spans fixtures, so a per-file counter both
    collides distinct frames across files and splits identical ones.

    Already-pseudonymised input passes through. Without that, hashing is not
    idempotent — re-redacting `device-03` yields a different `device-NN` — and
    `scan()`, which is a diff against `redact()`, reports every committed
    fixture as dirty forever.
    """
    if re.fullmatch(rf"{re.escape(prefix)}\d{{{width}}}{re.escape(suffix)}", value):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"{prefix}{int(digest, 16) % 10 ** width:0{width}d}{suffix}"


def _typed_redaction(value: Any) -> Any:
    """Replace a value while preserving its JSON type, containers included."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return 0
    if isinstance(value, dict):
        return {k: _typed_redaction(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_typed_redaction(v) for v in value]
    return REDACTED


def _redact_scalar(key: str, value: Any) -> Any:
    low = key.lower()
    if low in _KEEP:
        return value
    if low in _RENAMED:
        return _RENAMED[low]
    if low == "filename" and isinstance(value, str):
        return _digest(value, "frame_", 4, ".fits")
    if any(p in low for p in _PSEUDONYM_KEYS) and isinstance(value, str):
        return _digest(value, "device-", 2)
    if any(p in low for p in (*_SECRET_KEYS, *_LOCATION_KEYS)):
        return _typed_redaction(value)
    if low in _NAME_KEYS and isinstance(value, str) and _FACILITY.search(value):
        return REDACTED
    if isinstance(value, str) and any(p.search(value) for p in _VALUE_PATTERNS):
        return REDACTED
    return value


def _walk(key: str, value: Any) -> Any:
    """Redact by key at every depth.

    The key travels with the recursion so a container is redacted as a
    container; applying _redact_scalar to a dict is what flattens a settings
    subtree into the string "REDACTED".
    """
    replaced = _redact_scalar(key, value)
    if replaced is not value:
        return replaced
    if isinstance(value, dict):
        return {k: _walk(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(key, item) for item in value]
    return value


def redact(value: Any) -> Any:
    """Recursively redact a decoded JSON document. Idempotent."""
    return _walk("", value)


def scan(value: Any) -> list[str]:
    """Dotted paths redact() would still change. Empty means clean.

    Expressed as a diff against redact() rather than as a second rule set: that
    is the documented contract, it needs no "already redacted" escape hatch, and
    the two can never disagree. It relies on redact() being idempotent, which
    every rule above is — a digest of a digest is stable because the digest
    forms are themselves kept by their key rules.
    """
    return _differing_paths(value, redact(value))


def _differing_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        return [path for key in before
                for path in _differing_paths(before[key], after.get(key),
                                             f"{prefix}.{key}" if prefix else key)]
    if isinstance(before, list) and isinstance(after, list):
        return [path for index, item in enumerate(before)
                for path in _differing_paths(item, after[index],
                                             f"{prefix}[{index}]")]
    return [] if before == after else [prefix]
```

**Note for the implementer.** `scan`'s idempotence assumption is load-bearing
and cheap to break — add a rule whose output re-matches a *different* rule and
the guard reports every fixture as dirty forever. This module was written once
without the pass-through in `_digest` and had exactly that bug.
`test_scan_is_clean_after_redaction_by_construction` is what catches it, so
never weaken it.

- [ ] **Step 4: Run the redaction tests**

```bash
uv run pytest tests/unit/test_redaction.py -v
```

Expected: all PASS.

- [ ] **Step 5: Write the capture script**

Two hard rules, both from `CLAUDE.md`: **read-only against a live rig**, and
**redact before committing**.

```python
#!/usr/bin/env python3
"""Capture N.I.N.A. Advanced API fixtures from a live rig, redacted.

    scripts/capture_fixtures.py --host H --port 1888 --state <slug> [--dry-run]
      → tests/fixtures/<state-slug>_<endpoint-slug>.json, the raw envelope
      → re-running against an unchanged rig produces a byte-identical file

READ-ONLY. Every endpoint below reports state. NEVER add one that commands
equipment — slew, capture, park, home, connect, disconnect, guider, filter
change, focuser move, flat light, dome, sequence start/stop, profile switch. A
rig may be imaging, and a wasted night is not recoverable. If you are unsure
whether a call mutates state, do not make it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from redaction import PROFILE_ALLOWLIST, redact, scan  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# (endpoint slug, path, params). Read-only, all of them.
ENDPOINTS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("version", "/version", {}),
    ("application_start", "/application-start", {}),
    ("equipment_info", "/equipment/info", {}),
    ("sequence_json", "/sequence/json", {}),
    ("image_history_count", "/image-history", {"count": "true"}),
    ("image_history_all", "/image-history", {"all": "true"}),
    ("image_history_latest", "/image-history", {}),
    ("event_history", "/event-history", {}),
    ("flats_status", "/flats/status", {}),
    ("livestack_status", "/livestack/status", {}),
    ("last_af", "/equipment/focuser/last-af", {}),
    ("profile", "/profile/show", {"active": "true"}),
)


def _project(document: object, allowlist: tuple[str, ...]) -> dict:
    """Keep only allowlisted dotted paths. Used for /profile/show only."""
    kept: dict = {}
    for dotted in allowlist:
        node, target = document, kept
        parts = dotted.split(".")
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
            target = target.setdefault(part, {})
        leaf = parts[-1]
        if isinstance(node, dict) and leaf in node:
            target[leaf] = node[leaf]
    return kept


async def capture(host: str, port: int, state: str, dry_run: bool) -> int:
    base = f"http://{host}:{port}/v2/api"
    written = 0
    async with aiohttp.ClientSession() as session:
        versions = {}
        for slug, path, params in ENDPOINTS:
            async with session.get(base + path, params=params,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                envelope = await resp.json(content_type=None)

            if slug == "version":
                versions["api_version"] = str(envelope.get("Response"))
            if slug == "profile":
                envelope["Response"] = _project(envelope.get("Response"),
                                                PROFILE_ALLOWLIST)

            envelope = redact(envelope)
            leaks = scan(envelope)
            if leaks:
                print(f"REFUSING to write {slug}: unredacted {leaks}", file=sys.stderr)
                return 1

            envelope["_meta"] = {
                "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "nina_version": versions.get("nina_version", "unknown"),
                "api_version": versions.get("api_version", "unknown"),
                "endpoint": path,
                "params": params,
            }
            target = FIXTURES / f"{state}_{slug}.json"
            body = json.dumps(envelope, indent=2, sort_keys=False) + "\n"
            if dry_run:
                print(f"would write {target} ({len(body)} B)")
            else:
                target.write_text(body, encoding="utf-8")
                written += 1
    print(f"wrote {written} fixture(s) for state {state!r}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=1888)
    parser.add_argument("--state", required=True, help="state slug, e.g. dawn_flats")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(capture(args.host, args.port, args.state, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
```

`_meta.captured_at` makes a re-run *not* byte-identical. Resolve it the way the
design intends by having a re-run preserve the existing `_meta.captured_at` when
the rest of the document is unchanged:

```python
            if target.exists():
                previous = json.loads(target.read_text(encoding="utf-8"))
                previous_meta = previous.pop("_meta", None)
                if previous == {k: v for k, v in envelope.items() if k != "_meta"}:
                    envelope["_meta"] = previous_meta
```

Insert that immediately before `body = json.dumps(...)`.

- [ ] **Step 6: Backfill `_meta` on the 20 existing fixtures**

Do **not** re-redact them in the same pass. They were written by an earlier
ad-hoc redactor and differ from what the current rules produce — zeroed
coordinates, a destroyed `SideOfPier`, positionally-numbered filenames. Leave
them as they are and let the next real capture supersede them; re-deriving
committed fixtures from a script is how a corpus stops being a record of the
wire.

Two of those differences are worth a re-capture when the rig is next idle:
`SideOfPier` (§11's already-flipped branch has no other input) and the site
coordinates (§11's LST). Neither blocks phase A.

They were captured before the script existed, so add `_meta` by hand once, with
the values recorded in `tests/fixtures/README.md`
(`nina_version: "3.2.0.9001"`, `api_version: "2.2.15.2"`,
`captured_at: "2026-09-04T00:00:00+00:00"`, plus each file's endpoint and
params). Write a throwaway script under the scratchpad; do not commit it.

Then verify no fixture leaks:

```bash
uv run python -c "
import json, sys
sys.path.insert(0, 'tests')
from pathlib import Path
from redaction import scan
bad = {p.name: scan(json.loads(p.read_text())) for p in Path('tests/fixtures').glob('*.json')}
bad = {k: v for k, v in bad.items() if v}
print(bad or 'clean')
"
```

Expected: `clean`. If not, fix `tests/redaction.py` — the fixture is ground
truth about the wire, and the rule is what was incomplete.

- [ ] **Step 7: Add the pre-commit guard**

CI fires after the push, by which time a leaked credential is permanent (§8.3).

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: fixture-redaction
        name: fixtures carry no unredacted secrets
        entry: uv run python scripts/check_fixtures.py
        language: system
        files: ^tests/fixtures/.*\.json$
        pass_filenames: true
```

`scripts/check_fixtures.py`:

```python
#!/usr/bin/env python3
"""Fail the commit if any staged fixture still holds sensitive data.

CI is the backstop, not the guard: it fires after the push, by which time a
leaked credential is permanent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from redaction import scan  # noqa: E402


def main(paths: list[str]) -> int:
    failures = 0
    for name in paths:
        findings = scan(json.loads(Path(name).read_text(encoding="utf-8")))
        if findings:
            print(f"{name}: unredacted {findings}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

Install and prove it fires:

```bash
uv run --with pre-commit pre-commit install
echo '{"ApiKey": "live-secret"}' > tests/fixtures/tmp_leak.json
git add tests/fixtures/tmp_leak.json && git commit -m "should fail"
```

Expected: the commit is rejected naming `ApiKey`. Then
`git reset && rm tests/fixtures/tmp_leak.json`.

- [ ] **Step 8: Add the CI backstop job**

Append to `.github/workflows/ci.yml`:

```yaml
  fixtures:
    name: Fixture redaction
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync
      - run: uv run python scripts/check_fixtures.py tests/fixtures/*.json
```

- [ ] **Step 9: Update `tests/fixtures/README.md`**

Replace the paragraph saying `/profile/show` "is excluded here" with the
projection rule: it is captured as an allowlist projection of
`TelescopeSettings.FocalLength`, `FocuserSettings.{AutoFocusTimeoutSeconds,
RSquaredThreshold}`, `MeridianFlipSettings.*` and `CameraSettings.PixelSize`,
because §4.4 and §11 both consume it and excluding it would leave a polled
endpoint with no fixture, no drift coverage and no mapper test (§8.3). Add a
line stating every fixture now carries `_meta`.

- [ ] **Step 10: Commit**

```bash
git add tests/redaction.py tests/unit/test_redaction.py tests/fixtures \
        scripts/capture_fixtures.py scripts/check_fixtures.py \
        .pre-commit-config.yaml .github/workflows/ci.yml
git commit -m "feat: capture fixtures reproducibly and guard redaction before commit"
```

---

## Task A7: The drift guard

**Files:**
- Create: `tests/spec_deviations.json`,
  `tests/unit/test_drift_guard.py`,
  `tests/unit/__snapshots__/test_drift_guard.ambr` (generated)
- Modify: `pyproject.toml` (add `syrupy==6.0.0` to the `test` group)

**Interfaces:**
- Consumes: `tests/fixtures/*.json` (Task A6), `api/v2/schema.py` (Task A5).
- Produces: two tests over the **whole corpus** (§8.5) — one comparing observed
  types against the generated ones with a committed waiver file, one snapshotting
  the observed wire shape per dotted path.

- [ ] **Step 1: Write `tests/spec_deviations.json`**

One entry per §3.2 row, each with the wire truth and a reason. **Keys are the
namespaced paths `_corpus()` produces** — `WeatherData.CloudCover`, not the
OpenAPI type name `WeatherInfo.CloudCover`. A waiver keyed on a type name can
never match an observed path, which is a guard that is green by construction. This file is the
honest record: generated types are known wrong in ~15 places, so a naive
comparison is red on its first run and gets muted.

```json
{
  "WeatherData.CloudCover":      {"spec": "integer", "wire": "str|null", "why": "\"NaN\" arrives as a JSON string"},
  "Dome.Azimuth":            {"spec": "integer", "wire": "str|null", "why": "\"NaN\" arrives as a JSON string"},
  "WeatherData.Humidity":        {"spec": "integer", "wire": "float",    "why": "59.3 observed"},
  "WeatherData.Pressure":        {"spec": "integer", "wire": "float",    "why": "958.5 observed"},
  "WeatherData.RainRate":        {"spec": "string",  "wire": "float",    "why": "numeric on the wire"},
  "WeatherData.SkyBrightness":   {"spec": "string",  "wire": "float",    "why": "numeric on the wire"},
  "WeatherData.SkyTemperature":  {"spec": "string",  "wire": "float",    "why": "numeric on the wire"},
  "WeatherData.WindGust":        {"spec": "string",  "wire": "float",    "why": "numeric on the wire"},
  "Rotator.Position":        {"spec": "integer", "wire": "float",    "why": "335.0736 observed"},
  "Rotator.MechanicalPosition": {"spec": "integer", "wire": "float", "why": "53.86 observed"},
  "Mount.TrackingRate":      {"spec": "object",  "wire": "dict",     "why": "always {} on this build"},
  "Camera.Gains":            {"spec": "array",   "wire": "list",     "why": "always [] on this build"},
  "Mount.TrackingMode":      {"spec": "enum",    "wire": "str",      "why": "'Sidereal', not the spec's 'Siderial'. NOT null when disconnected — the key is absent entirely, along with 13 others"},
  "Camera.HasBattery":       {"spec": "absent",  "wire": "bool",     "why": "field on the wire, missing from the spec"},
  "Mount.CanSlewAltAz":      {"spec": "absent",  "wire": "bool",     "why": "field on the wire, missing from the spec"},
  "ImageStatistics.Index":       {"spec": "integer", "wire": "absent",   "why": "documented on ImageStatistics, present on neither path"}
}
```

- [ ] **Step 2: Write the failing guard**

```python
"""The drift guard — two tests over the whole corpus.

Not one fixture, and the reason is key PRESENCE rather than nullability: a
disconnected device does not null its fields, it drops them. The connected Mount
carries 51 keys and the disconnected one 37 — Coordinates, DeviceId, Name,
DisplayName, TrackingMode, TrackingModes, PrimaryAxisRates and seven more simply
are not there. A single-fixture guard would record whichever half it happened to
read and call the other half drift.

Paths are namespaced by the endpoint each fixture came from, taken from
_meta.endpoint. Without that, the per-device captures contribute bare leaves —
`Connected`, `Name`, `Position` — that collide across devices, and no waiver key
could ever match an observed path.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures"
DEVIATIONS = json.loads((TESTS / "spec_deviations.json").read_text(encoding="utf-8"))

# "NaN" is pre-passed to a sentinel marker so nineteen fields do not register as
# type errors and drown the signal (§8.5).
NAN = "NaN"

# endpoint -> the namespace its Response occupies. /equipment/info is already
# namespaced by its own eleven device keys, so it contributes no prefix.
_NAMESPACE = {
    "/equipment/info": "",
    "/equipment/camera/info": "Camera",
    "/equipment/mount/info": "Mount",
    "/equipment/focuser/info": "Focuser",
    "/equipment/filterwheel/info": "FilterWheel",
    "/equipment/guider/info": "Guider",
    "/equipment/rotator/info": "Rotator",
    "/equipment/dome/info": "Dome",
    "/equipment/flatdevice/info": "FlatDevice",
    "/equipment/weather/info": "WeatherData",
    "/equipment/safetymonitor/info": "SafetyMonitor",
    "/image-history": "ImageStatistics",
    "/event-history": "Event",
    "/sequence/json": "Sequence",
    "/sequence/state": "SequenceState",
    "/flats/status": "FlatsStatus",
    "/livestack/status": "LivestackStatus",
    "/equipment/focuser/last-af": "AutoFocusRun",
    "/application-start": "ApplicationStart",
    "/version": "Version",
    "/profile/show": "Profile",
}


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if value == NAN:
        return "nan"
    return {bool: "bool", int: "int", float: "float", str: "str",
            dict: "dict", list: "list"}[type(value)]


def _collapse(path: str) -> str:
    """Fold repeated container segments.

    /sequence/json nests Items seven deep and the depth varies with the loaded
    sequence, so an uncollapsed snapshot churns on an unrelated sequence edit.
    Items.Items.Items.Status and Items.Status are the same wire fact.
    """
    parts: list[str] = []
    for segment in path.split("."):
        if not (parts and parts[-1] == segment):
            parts.append(segment)
    return ".".join(parts)


def _observe(document: object, prefix: str = "") -> dict[str, set[str]]:
    """Dotted path -> the set of JSON types seen at it."""
    seen: dict[str, set[str]] = defaultdict(set)
    if isinstance(document, dict):
        if not document and prefix:
            # An empty dict has no leaves, so without this the path vanishes and
            # a waiver naming it reads as stale. Mount.TrackingRate is always {}.
            seen[_collapse(prefix)].add("dict")
        for key, value in document.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                for sub, types_ in _observe(value, path).items():
                    seen[sub] |= types_
            else:
                seen[_collapse(path)].add(_type_name(value))
    elif isinstance(document, list):
        if not document and prefix:
            # Camera.Gains is always [] on this build — same trap.
            seen[_collapse(prefix)].add("list")
        for item in document:
            for sub, types_ in _observe(item, prefix).items():
                seen[sub] |= types_
    return seen


def _corpus() -> dict[str, set[str]]:
    merged: dict[str, set[str]] = defaultdict(set)
    for path in sorted(FIXTURES.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        # Not every fixture is an envelope: image_history_session.json is a bare
        # JSON list. Guard it, or the whole guard dies on an AttributeError.
        if not isinstance(document, dict):
            continue
        meta = document.pop("_meta", {})              # ours, not N.I.N.A.'s
        prefix = _NAMESPACE.get(meta.get("endpoint", ""), "")
        for dotted, types_ in _observe(document.get("Response"), prefix).items():
            merged[dotted] |= types_
    return merged


def test_a_disconnected_device_drops_keys_rather_than_nulling_them() -> None:
    """The wire fact that makes the whole-corpus rule necessary.

    It is also what makes first-sight device creation derivable: DeviceId and
    Name are present only while a device is connected, so "has ever carried a
    DeviceId" is the observation signal.
    """
    connected = json.loads(
        (FIXTURES / "dawn_equipment_info.json").read_text(encoding="utf-8"))
    disconnected = json.loads(
        (FIXTURES / "restart_equipment_partial_connect.json").read_text(encoding="utf-8"))
    absent = set(connected["Response"]["Mount"]) - set(disconnected["Response"]["Mount"])
    assert {"DeviceId", "Name", "TrackingMode", "TrackingModes"} <= absent


def test_the_corpus_is_actually_being_read() -> None:
    """A guard that collects nothing passes vacuously — every test below would."""
    observed = _corpus()
    assert len(observed) > 100
    assert "FlatDevice.MaxBrightness" in observed


def test_an_always_empty_container_is_still_observed() -> None:
    """Camera.Gains is always [] and Mount.TrackingRate always {} on this build.
    A container with no leaves contributes no path unless recorded explicitly,
    and its waiver then reads as stale."""
    observed = _corpus()
    assert observed["Camera.Gains"] == {"list"}
    assert observed["Mount.TrackingRate"] == {"dict"}


def test_observed_wire_shape_matches_snapshot(snapshot) -> None:
    """Fires when the WIRE changes — which the spec cannot tell you."""
    shape = {path: "|".join(sorted(types_)) for path, types_ in sorted(_corpus().items())}
    assert shape == snapshot


def test_no_waiver_is_stale() -> None:
    """A waiver naming a path the corpus no longer contains is a lie."""
    observed = set(_corpus())
    stale = [dotted for dotted, entry in DEVIATIONS.items()
             if entry["wire"] != "absent" and dotted not in observed]
    assert not stale, f"waivers that no longer describe the corpus: {stale}"


def test_no_field_waived_as_absent_is_present() -> None:
    """ImageStatistics.Index is documented by the spec and on neither path.
    If it ever appears, the waiver must go."""
    observed = set(_corpus())
    present = [dotted for dotted, entry in DEVIATIONS.items()
               if entry["wire"] == "absent" and dotted in observed]
    assert not present, f"fields waived as absent but present on the wire: {present}"
```

- [ ] **Step 3: Run and generate the snapshot**

```bash
uv sync
uv run pytest tests/unit/test_drift_guard.py -v --snapshot-update
uv run pytest tests/unit/test_drift_guard.py -v
```

Expected: FAIL then PASS. Review the generated `.ambr` by eye before committing
— it is the record of what the wire actually sends, and every line of it is a
claim.

- [ ] **Step 4: Prove the guard catches a new deviation**

```bash
python - <<'PY'
import json, pathlib
p = pathlib.Path("tests/fixtures/dawn_flatdevice_connected.json")
d = json.loads(p.read_text()); d["Response"]["MaxBrightness"] = "4096"
p.write_text(json.dumps(d, indent=2) + "\n")
PY
uv run pytest tests/unit/test_drift_guard.py -q
git checkout tests/fixtures/dawn_flatdevice_connected.json
```

Expected: FAIL on the snapshot, naming `MaxBrightness: int` → `str`.

- [ ] **Step 5: Commit**

```bash
git add tests/spec_deviations.json tests/unit/test_drift_guard.py \
        tests/unit/__snapshots__ pyproject.toml
git commit -m "test: guard the wire shape against drift, with the deviations recorded"
```

---

## Task A8: `api/errors.py`

**Files:**
- Create: `custom_components/nina_astrophotography/api/errors.py`
- Test: `tests/unit/test_api_errors.py`

**Interfaces:**
- Produces:
  - `NinaError(Exception)` — base.
  - `NinaConnectionError(NinaError)` — socket refused, DNS, timeout. Retryable.
  - `NinaUnavailableError(NinaError)` — envelope 5xx, or N.I.N.A. mid-boot. Retryable.
  - `NinaEndpointError(NinaError)` — capability not served by this build. **Not** retryable.
  - `NinaRequestError(NinaError)` — malformed request, pre-handler 4xx with an HTML body. **Not** retryable.
  - `NinaCommandError(NinaError)` — envelope `StatusCode` 4xx/5xx with a real `Error`.
    `NinaCommandError(message: str, *, status_code: int | None = None, api_error: str = "")`,
    exposing `.status_code` and `.api_error`.
  - `NinaError.retryable: bool` — a class attribute, read by `coordinator.py`.

- [ ] **Step 1: Write the failing test**

```python
"""The error taxonomy is semantic, not HTTP."""
import pytest

from nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaError,
    NinaRequestError,
    NinaUnavailableError,
)


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (NinaConnectionError("refused"), True),
        (NinaUnavailableError("booting"), True),
        (NinaEndpointError("no such capability"), False),
        (NinaRequestError("malformed"), False),
    ],
)
def test_retryability_is_a_property_of_the_type(error: NinaError, retryable: bool) -> None:
    assert error.retryable is retryable


def test_command_error_carries_the_envelope_status_not_the_http_one() -> None:
    error = NinaCommandError("refused", status_code=409, api_error="Camera not connected")
    assert (error.status_code, error.api_error) == (409, "Camera not connected")


def test_errors_subclass_builtins_only() -> None:
    """api/ must stay importable without Home Assistant (§7.1)."""
    for cls in (NinaConnectionError, NinaUnavailableError, NinaEndpointError,
                NinaRequestError, NinaCommandError):
        assert all(base.__module__ in ("builtins", "nina_astrophotography.api.errors")
                   for base in cls.__mro__)
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/unit/test_api_errors.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""The error taxonomy.

Subclasses builtins only — never HomeAssistantError — so the fast suite stays
HA-free. Mapping to Home Assistant happens in __init__.py and coordinator.py.

Definitions are semantic, not HTTP: the Advanced API answers HTTP 200 for
almost everything and carries the real outcome in the envelope's StatusCode.
"""
from __future__ import annotations


class NinaError(Exception):
    """Base for everything the client raises."""

    retryable: bool = False


class NinaConnectionError(NinaError):
    """Socket refused, DNS failure, or timeout."""

    retryable = True


class NinaUnavailableError(NinaError):
    """Envelope 5xx, or N.I.N.A. answering while still starting up."""

    retryable = True


class NinaEndpointError(NinaError):
    """This N.I.N.A. build does not serve the requested capability.

    A wrong path never becomes right, so failing the config entry beats
    retrying forever.
    """


class NinaRequestError(NinaError):
    """The request itself was malformed.

    Only routing and parameter-binding failures produce a real 4xx, and those
    return EmbedIO's HTML error page rather than an envelope.
    """


class NinaCommandError(NinaError):
    """The handler ran and refused.

    Retryability depends on the command: `status_code` and `api_error` are the
    envelope's, never HTTP's. Note that the envelope's code alone cannot
    classify a failure — "Sequence is not initialized" is raised with 409 on
    seven routes and 400 on two.
    """

    def __init__(self, message: str, *, status_code: int | None = None,
                 api_error: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_error = api_error
```

- [ ] **Step 4: Run**

```bash
uv run pytest tests/unit/test_api_errors.py tests/unit/test_seam.py -v
```

Expected: PASS. The seam guard now collects `api/errors.py` too.

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/api/errors.py \
        tests/unit/test_api_errors.py
git commit -m "feat: add the version-independent error taxonomy"
```

---

Tasks A9 through A15 continue in this file; see the sections below.

## Task A9: `api/models.py` — the contract

**Files:**
- Create: `custom_components/nina_astrophotography/api/models.py`
- Test: `tests/unit/test_api_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces the frozen dataclasses every layer above the seam speaks in. Field
  names below are the exact ones Tasks A11–A15 and all of phases B–D use:

  - `DeviceMeta(name: str | None, display_name: str | None, description: str | None, driver_version: str | None, device_id: str | None)`
  - `CameraModel(connected, meta, temperature, target_temperature, cooler_on, cooler_power, dew_heater_on, gain, offset, usb_limit, camera_state, is_exposing, pixel_size, has_battery, battery, can_set_temperature, gains, binning_modes)`
  - `MountModel(connected, meta, right_ascension, declination, altitude, azimuth, sidereal_time, tracking_enabled, tracking_mode, tracking_modes, at_park, at_home, side_of_pier, time_to_meridian_flip, can_slew_alt_az, epoch)`
  - `FocuserModel(connected, meta, position, temperature, is_moving, max_step, step_size, temp_comp_available, temp_comp)`
  - `FilterWheelModel(connected, meta, selected_filter, available_filters, is_moving)`
  - `GuiderModel(connected, meta, state, rms_total, rms_ra, rms_dec, pixel_scale)`
  - `RotatorModel(connected, meta, position, mechanical_position, is_moving, reverse, synced)`
  - `DomeModel(connected, meta, azimuth, shutter_status, at_park, at_home, driver_following, following, slewing)`
  - `FlatDeviceModel(connected, meta, cover_state, light_on, brightness, min_brightness, max_brightness, supports_on_off, supports_open_close)`
  - `WeatherModel(connected, meta, channels: Mapping[str, float | None])` — channel
    keys are the wire's own names, lowercased with underscores:
    `cloud_cover`, `dew_point`, `humidity`, `pressure`, `rain_rate`,
    `sky_brightness`, `sky_quality`, `sky_temperature`, `star_fwhm`,
    `temperature`, `wind_direction`, `wind_gust`, `wind_speed`.
  - `SafetyMonitorModel(connected, meta, is_safe)`
  - `SwitchChannelModel(index, name, description, value, minimum, maximum, step_size, writable)`
    with a `binary` property — `maximum - minimum == step_size` (§5.3.5).
  - `SwitchDeviceModel(connected, meta, channels: tuple[SwitchChannelModel, ...])`
  - `EquipmentSnapshot(camera, mount, focuser, filter_wheel, guider, rotator, dome, flat_device, weather, safety_monitor, switch_device)` — each `X | None`.
  - `Frame(date, filename, target_name, filter_name, image_type, exposure_time, hfr, stars, mean, median, std_dev, rms, temperature, gain, offset, focal_length, generation)`
  - `NinaEvent(name, time, payload, generation)`
  - `SessionStats(...)` — defined with `session.py` in Task A13.
  - `AutoFocusState(...)` — defined with `session.py` in Task A13.
  - `SequenceNode(name, status, iterations, children, attributes)`
  - `FlatsStatus(state, total_iterations, completed_iterations)`
  - `LivestackStatus(running, raw_state)`
  - `VersionInfo(api_version, nina_version)`
  - `ProfileSettings(focal_length, pixel_size, autofocus_timeout_seconds, r_squared_threshold, min_minutes_after_meridian, max_minutes_after_meridian, use_side_of_pier)`

- [ ] **Step 1: Write the failing test**

Test *our* rules, not `dataclasses`. Do not write a test asserting `frozen`
prevents assignment — that tests the standard library.

```python
"""models.py distinguishes 'never seen' from 'present but disconnected'."""
from nina_astrophotography.api.models import (
    DeviceMeta,
    EquipmentSnapshot,
    SwitchChannelModel,
    WeatherModel,
)


def test_absent_device_is_none_and_disconnected_device_is_a_model() -> None:
    """§5.2.2 and §7.3 both need this distinction from one snapshot."""
    snapshot = EquipmentSnapshot(
        camera=None,
        mount=None, focuser=None, filter_wheel=None, guider=None, rotator=None,
        dome=None, flat_device=None,
        weather=WeatherModel(connected=False, meta=DeviceMeta(None, None, None, None, None),
                             channels={}),
        safety_monitor=None, switch_device=None,
    )
    assert snapshot.camera is None                 # never seen
    assert snapshot.weather is not None            # seen, currently down
    assert snapshot.weather.connected is False


def test_a_switch_channel_is_binary_when_its_range_is_one_step() -> None:
    """§5.3.5: Max − Min == StepSize means the channel goes on the switch platform."""
    outlet = SwitchChannelModel(index=0, name="Outlet 1", description="", value=1.0,
                                minimum=0.0, maximum=1.0, step_size=1.0, writable=True)
    dew = SwitchChannelModel(index=1, name="Dew A", description="", value=40.0,
                             minimum=0.0, maximum=100.0, step_size=1.0, writable=True)
    assert outlet.binary is True
    assert dew.binary is False
```

- [ ] **Step 2: Run it**

```bash
uv run pytest tests/unit/test_api_models.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Write every dataclass listed in the Interfaces block, `@dataclass(frozen=True,
slots=True)`, with the module docstring carrying the two rules that will
otherwise be violated:

```python
"""Normalized models — THE CONTRACT.

Everything above api/ speaks in these and never in dicts. Two rules:

**"Observed" is defined by key presence, not by `Connected`.** `/equipment/info`
always emits all eleven device blocks, including a full `Dome` block on a rig
that has never had a dome — so a device key being present proves nothing. What
distinguishes them is that a disconnected device *drops* `DeviceId`, `Name` and
`DisplayName`, while one that has never existed never had them. A device is
observed once it has carried a `DeviceId`; the coordinator **latches** that,
because evaluating it per-poll would delete the device the moment it disconnects.

`None` means "no reading". Every sentinel the API uses in-band — "NaN", HFR 0 on
a calibration frame, -1 iterations, 24 hours to meridian flip on an untracked
mount — is already gone by the time a value lands here. If a sentinel reaches
derive.py, the seam is broken.

A device that is `None` has never been observed; a device present with
`connected=False` has been observed and is currently down. §5.2.2's first-sight
rule and §7.3's availability levels both need that distinction from one snapshot.

This module is closed to fields no entity, service, session.py or derive.py
consumes. A guideline, not a test — the enforcement needs an exemption list on
its first service-only field.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DeviceMeta:
    """Registry metadata. DriverVersion is the device's sw_version (§5.1).

    DriverInfo is deliberately absent: the rotator and flat panel both return
    the ASCOM template default, though the filter wheel returns real firmware.
    """

    name: str | None
    display_name: str | None
    description: str | None
    driver_version: str | None
    device_id: str | None


@dataclass(frozen=True, slots=True)
class SwitchChannelModel:
    index: int
    name: str
    description: str
    value: float | None
    minimum: float | None
    maximum: float | None
    step_size: float | None
    writable: bool

    @property
    def binary(self) -> bool:
        """A one-step range is an on/off channel, and belongs on `switch`."""
        if self.minimum is None or self.maximum is None or self.step_size is None:
            return False
        return self.maximum - self.minimum == self.step_size
```

…and so on for the remaining models, exactly as named in the Interfaces block.
`WeatherModel.channels` is a `Mapping[str, float | None]` so §5.2.2 can ask which
channels this source has ever produced without a field per channel.

- [ ] **Step 4: Run**

```bash
uv run pytest tests/unit/test_api_models.py tests/unit/test_seam.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/api/models.py \
        tests/unit/test_api_models.py
git commit -m "feat: define the normalized model contract"
```

---

## Task A10: `api/v2/client.py`

**Files:**
- Create: `custom_components/nina_astrophotography/api/v2/client.py`
- Test: `tests/unit/test_v2_client.py`

**Interfaces:**
- Consumes: `api/errors.py` (A8), `api/v2/schema.py` (A5), `tests/helpers.py`'s
  `FakeSession`, `ok()` and `failure()`.
- Produces `NinaClientV2(host: str, port: int, session: aiohttp.ClientSession)` with:
  - `async get_version() -> dict` / `async get_nina_version() -> dict`
  - `async get_application_start() -> str | None`
  - `async get_equipment() -> EquipmentSnapshot`
  - `async get_frames(*, include_all: bool = False, generation: str | None = None) -> list[Frame]`
  - `async get_image_history_count() -> int`
  - `async get_sequence_json() -> list[dict] | None`
  - `async get_event_history() -> list[dict]`
  - `async get_profile() -> dict`
  - `async get_last_autofocus() -> dict | None`
  - `async get_flats_status() -> dict`
  - `async get_livestack_status() -> dict`
  - `async get_livestack_available() -> list[dict]`
  - `async get_image_bytes(index: int, *, quality: int = 85, stretch: bool = True) -> bytes`
  - `async set_flat_light(on: bool) -> None`
  - `async set_flat_brightness(brightness: int) -> None`
  - `base_url: str` — for the Lovelace cards' image URLs.

  **The public getters return models, not wire data.** `_get()` and the
  `_raw_*` helpers stay private to `api/v2/`, so `api/v2/mapper.py` has exactly
  one consumer — the client itself — and the seam rule becomes enforceable
  rather than aspirational. Concretely:

  - `async get_equipment() -> EquipmentSnapshot`
  - `async get_frames(*, include_all: bool = False) -> list[Frame]`
  - `async get_events() -> list[NinaEvent]`
  - `async get_sequence() -> SequenceNode | None`
  - `async get_flats() -> FlatsStatus`
  - `async get_livestack() -> LivestackStatus`
  - `async get_profile() -> ProfileSettings`
  - `async get_versions() -> VersionInfo`

  The mapper needs the rig's UTC offset to stamp naive log-scraped timestamps,
  so the client caches it from each `/equipment/info`
  (`Mount.Coordinates.DateTime.{Now,UtcNow}`) and passes it down. That is the
  one piece of state the client holds.

- [ ] **Step 1: Write the failing tests**

These are the behaviours §3.5 and §7.1 name. Each is one behaviour.

```python
"""The envelope, not the HTTP status, carries the outcome."""
import pytest
from helpers import FakeResponse, FakeSession, failure, ok

from nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from nina_astrophotography.api.v2.client import NinaClientV2


def _client(session: FakeSession) -> NinaClientV2:
    return NinaClientV2(host="nina.local", port=1888, session=session)


async def test_empty_history_is_no_data_not_an_error() -> None:
    """`Index out of range` is what an idle rig answers, every HA start."""
    client = _client(FakeSession({"image-history": failure("Index out of range", 400)}))
    assert await client.get_frames() == []


async def test_uninitialised_sequencer_is_no_data_not_an_error() -> None:
    """A ~7.5 s window at N.I.N.A. startup, on the ordinary startup path."""
    client = _client(FakeSession({"sequence/json": failure("Sequence is not initialized", 409)}))
    assert await client.get_sequence_json() is None


async def test_uninitialised_sequencer_is_recognised_at_400_too() -> None:
    """Ten guards, two codes for one condition — match on the message (§7.1)."""
    client = _client(FakeSession({"sequence/json": failure("Sequence is not initialized", 400)}))
    assert await client.get_sequence_json() is None


async def test_a_real_envelope_failure_raises_a_command_error() -> None:
    client = _client(FakeSession({"equipment/info": failure("Camera not connected", 409)}))
    with pytest.raises(NinaCommandError) as caught:
        await client.get_equipment()
    assert caught.value.status_code == 409


async def test_success_false_with_no_error_and_200_is_success() -> None:
    """Seven handlers assign Success from a driver boolean (§3.5)."""
    body = {"Response": {"Camera": {"Connected": True}}, "Error": "",
            "StatusCode": 200, "Success": False, "Type": "API"}
    client = _client(FakeSession({"equipment/info": ok({"Camera": {"Connected": True}})}))
    assert (await client.get_equipment()).camera.connected is True


async def test_a_zero_length_200_is_unavailable_not_a_crash() -> None:
    """Sequence serialization failure: empty body, no envelope (§3.5)."""
    client = _client(FakeSession({"sequence/json": FakeResponse("", content_type="text/plain")}))
    with pytest.raises(NinaUnavailableError):
        await client.get_sequence_json()


async def test_pre_handler_html_404_is_an_endpoint_error() -> None:
    session = FakeSession({"livestack": FakeResponse("<html>404</html>", status=404,
                                                     content_type="text/html")})
    with pytest.raises(NinaEndpointError):
        await _client(session).get_livestack_status()


async def test_pre_handler_html_400_is_a_request_error_not_a_transient_one() -> None:
    """A pre-handler 400 is permanent; an envelope 400 may be transient (§7.1)."""
    session = FakeSession({"image-history": FakeResponse("<html>400</html>", status=400,
                                                         content_type="text/html")})
    with pytest.raises(NinaRequestError):
        await _client(session).get_frames()


async def test_envelope_5xx_is_unavailable_and_retryable() -> None:
    client = _client(FakeSession({"equipment/info": failure("Internal error", 500)}))
    with pytest.raises(NinaUnavailableError) as caught:
        await client.get_equipment()
    assert caught.value.retryable is True


async def test_a_dropped_connection_is_a_connection_error() -> None:
    import aiohttp
    session = FakeSession({"version": aiohttp.ClientError("boom")})
    with pytest.raises(NinaConnectionError):
        await _client(session).get_version()


async def test_image_history_count_returns_the_scalar() -> None:
    client = _client(FakeSession({"image-history": ok(122)}))
    assert await client.get_image_history_count() == 122


async def test_empty_history_count_is_zero_not_none() -> None:
    """?count=true answers 0 where bare /image-history says Index out of range."""
    client = _client(FakeSession({"image-history": ok(0)}))
    assert await client.get_image_history_count() == 0
```

And the request-parameter pins — §3.2 says a wrong name is a silent no-op, so
these are the highest-value tests in the file:

```python
"""Request parameter names are verified by live probe and pinned here.

The spec declares set-light's parameter as literally `True`; the wire reads
`on`. `set-light?True=true` answers Success: true and leaves the panel alone.
Never generate these from the spec.
"""


async def test_set_flat_light_sends_on_not_True() -> None:
    session = FakeSession()
    await _client(session).set_flat_light(True)
    url, params = session.requests[-1]
    assert "/equipment/flatdevice/set-light" in url
    assert params == {"on": "true"}


async def test_set_flat_brightness_sends_brightness() -> None:
    session = FakeSession()
    await _client(session).set_flat_brightness(2048)
    _, params = session.requests[-1]
    assert params == {"brightness": 2048}


async def test_image_history_all_sends_all_true() -> None:
    """?all=true is the only reseed source; bare /image-history returns one frame."""
    session = FakeSession({"image-history": ok([])})
    await _client(session).get_frames(include_all=True)
    _, params = session.requests[-1]
    assert params == {"all": "true"}


async def test_the_image_endpoint_sends_autoPrepare_not_useAutoStretch() -> None:
    """An unknown parameter binds nothing and is not rejected, so the request
    succeeds and quietly returns the linear frame."""
    session = FakeSession({"/image/": FakeResponse(b"\xff\xd8", content_type="image/jpeg")})
    await _client(session).get_image_bytes(0)
    _, params = session.requests[-1]
    assert params["autoPrepare"] == "true"
    assert "useAutoStretch" not in params
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_v2_client.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""ninaAPI v2 HTTP client.

Everything that knows a path, a parameter name or the envelope's shape lives
here. Above api/, nothing does.

The HTTP status is almost always 200: CoreUtility.WriteToResponse never assigns
context.Response.StatusCode, so refused commands, 409s and handler exceptions
all arrive as HTTP 200 with the real code in the body. Only routing and
parameter-binding failures produce a real 4xx, and those return EmbedIO HTML.

Classification is on the pair (StatusCode, Error), never the code alone:
"Sequence is not initialized" is raised by ten guards with 409 on
/sequence/{json,state,start,stop,reset,set-target,skip} and 400 on
/sequence/{edit,load}. The OpenAPI document calls it "Sequencer not
initialized"; the wire says "Sequence is not initialized". Match the wire.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from ..errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_IMAGE_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Pre-handler statuses meaning the path itself is not served.
_NOT_SERVED = (404, 405, 501)

# "No data yet" — ordinary states, normalized to None/[] rather than raised.
_NO_DATA_MESSAGES = ("index out of range", "is not initialized")


class NinaClientV2:
    """Async client for ninaAPI v2 (2.2.15.x)."""

    def __init__(self, host: str, port: int, session: aiohttp.ClientSession) -> None:
        self.base_url = f"http://{host}:{port}/v2/api"
        self._session = session

    # ── transport ────────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Return the unwrapped Response, or raise. `None` means no data yet."""
        url = self.base_url + path
        try:
            async with self._session.get(url, params=params, timeout=_TIMEOUT) as resp:
                status = resp.status
                content_type = resp.content_type or ""
                body = await resp.text()
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError(f"Timeout reaching N.I.N.A. at {url}") from exc
        except aiohttp.ClientError as exc:
            # ClientError, not ClientConnectorError: a crashed N.I.N.A. raises
            # ServerDisconnectedError and a truncated reply ClientPayloadError.
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

        if status != 200:
            raise self._pre_handler_error(path, status, body)
        if not body.strip():
            # Sequence serialization failure: empty body, no envelope.
            raise NinaUnavailableError(f"{path} returned an empty body")
        return self._unwrap(path, self._decode(path, body))

    @staticmethod
    def _pre_handler_error(path: str, status: int, body: str) -> Exception:
        summary = " ".join(body.split())[:120]
        message = f"GET {path} -> {status}: {summary}" if summary else f"GET {path} -> {status}"
        if status in _NOT_SERVED:
            return NinaEndpointError(message)
        if 400 <= status < 500:
            # EmbedIO routing/binding failure: permanent, unlike an envelope 400.
            return NinaRequestError(message)
        return NinaUnavailableError(message)

    @staticmethod
    def _decode(path: str, body: str) -> Any:
        import json

        try:
            return json.loads(body)
        except ValueError as exc:
            raise NinaUnavailableError(f"{path} returned a non-JSON body") from exc

    @staticmethod
    def _unwrap(path: str, payload: Any) -> Any:
        if not isinstance(payload, dict) or "Success" not in payload:
            raise NinaUnavailableError(f"{path} returned no envelope")

        error = str(payload.get("Error") or "")
        status = payload.get("StatusCode")

        if payload.get("Success") is False:
            # Seven handlers assign Success from a driver boolean and answer
            # Success: false, Error: "", StatusCode: 200 on a call that worked.
            if not error and status in (None, 200):
                return payload.get("Response")
            if any(message in error.lower() for message in _NO_DATA_MESSAGES):
                return None
            if isinstance(status, int) and status >= 500:
                raise NinaUnavailableError(f"{path}: {error} (StatusCode {status})")
            raise NinaCommandError(
                f"{path}: {error or 'unknown error'} (StatusCode {status})",
                status_code=status if isinstance(status, int) else None,
                api_error=error,
            )
        return payload.get("Response")

    # ── reads ────────────────────────────────────────────────────────────────

    async def get_version(self) -> Any:
        return await self._get("/version")

    async def get_nina_version(self) -> Any:
        return await self._get("/version/nina")

    async def get_application_start(self) -> str | None:
        value = await self._get("/application-start")
        return str(value) if value is not None else None

    async def get_equipment(self) -> EquipmentSnapshot:
        wire = await self._get("/equipment/info") or {}
        self._rig_offset = rig_offset(wire) or self._rig_offset
        return map_equipment_info(wire)

    async def get_frames(self, *, include_all: bool = False,
                         generation: str | None = None) -> list[Frame]:
        """`include_all`, not `all` — the builtin is shadowed in this module.

        The wire parameter stays `all`; only the keyword differs.
        """
        params = {"all": "true"} if include_all else None
        response = await self._get("/image-history", params)
        if response is None:
            return []
        wire = response if isinstance(response, list) else [response]
        return [map_frame(item, generation) for item in wire]

    async def get_image_history_count(self) -> int:
        return int(await self._get("/image-history", {"count": "true"}) or 0)

    async def get_sequence_json(self) -> list[dict] | None:
        return await self._get("/sequence/json")

    async def get_event_history(self) -> list[dict]:
        return await self._get("/event-history") or []

    async def get_profile(self) -> dict:
        return await self._get("/profile/show", {"active": "true"}) or {}

    async def get_last_autofocus(self) -> dict | None:
        return await self._get("/equipment/focuser/last-af")

    async def get_flats_status(self) -> dict:
        return await self._get("/flats/status") or {}

    async def get_livestack_status(self) -> dict:
        return await self._get("/livestack/status") or {}

    async def get_livestack_available(self) -> list[dict]:
        return await self._get("/livestack/image/available") or []

    async def get_image_bytes(self, index: int, *, quality: int = 85,
                              auto_prepare: bool = True) -> bytes:
        """Fetch a rendered frame.

        autoPrepare, not useAutoStretch: an unknown parameter binds nothing and
        is not rejected, so the request succeeds and returns the linear frame.
        """
        path = f"/image/{index}"
        params: dict[str, Any] = {"stream": "true", "quality": quality}
        if auto_prepare:
            params["autoPrepare"] = "true"
        url = self.base_url + path
        try:
            async with self._session.get(url, params=params,
                                         timeout=_IMAGE_TIMEOUT) as resp:
                if resp.status != 200:
                    raise self._pre_handler_error(path, resp.status, "")
                # With stream=true a real image is served as image/*; a refusal
                # arrives as 200 carrying the JSON envelope.
                if (resp.content_type or "").startswith("image/"):
                    return await resp.read()
                self._unwrap(path, await resp.json(content_type=None))
                raise NinaUnavailableError(f"{path} returned no image")
        except asyncio.TimeoutError as exc:
            raise NinaConnectionError("Timeout fetching image") from exc
        except aiohttp.ClientError as exc:
            raise NinaConnectionError(f"Cannot reach N.I.N.A. at {url}: {exc}") from exc

    # ── commands ─────────────────────────────────────────────────────────────
    #
    # Parameter names are verified by live probe and pinned by test. The spec
    # declares set-light's parameter as literally `True`; `set-light?True=true`
    # answers Success: true and leaves the panel alone. Never generate these.
    #
    # No command on this API can be confirmed from its own response: parameters
    # default silently, values are clamped silently, and the state changes
    # seconds later. Read state back from the poll.

    async def set_flat_light(self, on: bool) -> None:
        await self._get("/equipment/flatdevice/set-light",
                        {"on": "true" if on else "false"})

    async def set_flat_brightness(self, brightness: int) -> None:
        await self._get("/equipment/flatdevice/set-brightness",
                        {"brightness": brightness})
```

- [ ] **Step 4: Run**

```bash
uv run pytest tests/unit/test_v2_client.py tests/unit/test_seam.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/api/v2/client.py \
        custom_components/nina_astrophotography/api/v2/__init__.py \
        tests/unit/test_v2_client.py
git commit -m "feat: add the v2 client, keying on the envelope rather than HTTP"
```

---

## Task A11: `api/v2/mapper.py`

**Files:**
- Create: `custom_components/nina_astrophotography/api/v2/mapper.py`
- Test: `tests/unit/test_v2_mapper.py`

**Interfaces:**
- Consumes: `api/models.py` (A9), fixtures (A6).
- Produces:
  - `nan_to_none(value: Any) -> Any` — the blanket rule.
  - `map_equipment_info(wire: dict) -> EquipmentSnapshot`
  - `map_frame(wire: dict, generation: str | None) -> Frame`
  - `map_image_save(payload: dict, generation: str | None) -> Frame | None`
  - `map_event(wire: dict, generation: str | None) -> NinaEvent`
  - `map_sequence(wire: list[dict] | None) -> SequenceNode | None`
  - `map_flats_status(wire: dict) -> FlatsStatus`
  - `map_livestack_status(wire: dict) -> LivestackStatus`
  - `map_profile(wire: dict) -> ProfileSettings`
  - `EVENT_TIMEZONES: Mapping[str, str]` — event name → `"local" | "utc"`.

- [ ] **Step 1: Write the failing tests, driven from the fixtures**

Fixtures are ground truth. Load them; do not hand-write wire data.

```python
"""wire → models. Every sentinel, timezone and quirk dies in this module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nina_astrophotography.api.v2.mapper import (
    map_equipment_info,
    map_event,
    map_frame,
    map_flats_status,
    map_livestack_status,
    nan_to_none,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str):
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    document.pop("_meta", None)
    return document["Response"]


@pytest.mark.parametrize(
    ("value", "expected"),
    [("NaN", None), ("nan", None), (0.0, 0.0), (None, None), ("Sidereal", "Sidereal")],
)
def test_the_blanket_nan_rule(value, expected) -> None:
    """.NET serializes double.NaN as a JSON string. No allowlist."""
    assert nan_to_none(value) == expected


def test_disconnected_devices_are_present_but_not_connected() -> None:
    snapshot = map_equipment_info(load("restart_equipment_partial_connect.json"))
    assert snapshot.mount is not None
    assert snapshot.mount.connected is False


def test_nan_fields_map_to_none_not_zero() -> None:
    """Nineteen fields are "NaN" with weather, mount, focuser and dome down."""
    snapshot = map_equipment_info(load("restart_equipment_partial_connect.json"))
    assert snapshot.weather is not None
    assert all(v is None for v in snapshot.weather.channels.values())


def test_tracking_mode_is_the_wire_spelling_not_the_specs() -> None:
    """The spec says 'Siderial'; the wire says 'Sidereal'."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    # /equipment/info nests eleven device blocks under Camera, Dome, FilterWheel,
    # FlatDevice, Focuser, Guider, Mount, Rotator, SafetyMonitor, Switch and
    # WeatherData. The per-device /equipment/<x>/info captures are a BARE device
    # object — do not feed them to map_equipment_info.
    assert snapshot.mount.tracking_mode in {"Sidereal", "Lunar", "Solar", "King",
                                            "Stopped", None}


def test_the_meridian_24_sentinel_maps_to_none() -> None:
    """24 h to flip means tracking is off, not 'a day away' (§11)."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert snapshot.mount.tracking_enabled is False
    assert snapshot.mount.time_to_meridian_flip is None


def test_flat_panel_range_comes_from_the_driver() -> None:
    """MaxBrightness 4096 on this panel; 255 on an Alnitak. Never hardcode."""
    snapshot = map_equipment_info(load("dawn_equipment_info.json"))
    assert snapshot.flat_device.max_brightness == 4096


def test_the_per_device_endpoint_shape_maps_too() -> None:
    """dawn_flatdevice_connected.json is a bare FlatDeviceInfo, not a snapshot."""
    from nina_astrophotography.api.v2.mapper import map_flat_device

    panel = map_flat_device(load("dawn_flatdevice_connected.json"))
    assert panel.max_brightness == 4096


def test_calibration_frames_lose_their_hfr_but_keep_their_adu() -> None:
    """Keyed on ImageType, which is on both paths. HFR 0 is a reliable
    calibration signal but not a sufficient one — see the clouded-light test."""
    flats = [f for f in load("dawn_image_history_with_flats.json")
             if f["ImageType"] == "FLAT"]
    frame = map_frame(flats[0], generation="g1")
    assert frame.hfr is None
    assert frame.stars is None
    assert frame.mean is not None


def test_light_frames_keep_their_hfr() -> None:
    lights = [f for f in load("dawn_image_history_with_flats.json")
              if f["ImageType"] == "LIGHT"]
    assert map_frame(lights[0], generation="g1").hfr is not None


def test_a_clouded_light_keeps_its_zero_star_count() -> None:
    """A light through thick cloud reports HFR 0 with Stars 0, and "zero stars
    detected" is the most diagnostic reading a clouded-out sub has. Keying
    calibration on HFR == 0 alone would classify it as a flat and discard it.

    The corpus cannot show this: no captured LIGHT has HFR 0, and the minimum
    star count across the 55 lights is 3758. Constructed deliberately.
    """
    clouded = {"ImageType": "LIGHT", "HFR": 0.0, "Stars": 0, "Mean": 612.0,
               "Date": "2026-09-04T02:00:00.000-05:00",
               "Filename": "frame_9999.fits", "ExposureTime": 300.0}
    frame = map_frame(clouded, generation="g1")
    assert frame.stars == 0
    assert frame.hfr is None


def test_a_dark_is_calibration_even_though_its_star_count_is_positive() -> None:
    """The captured dark reports HFR 0.0 and Stars 1 — keying on Stars == -1
    would misclassify every dark."""
    push = load("live_image_save_push.json")["ImageStatistics"]
    frame = map_frame(push, generation="g1")
    assert frame.hfr is None and frame.stars is None


def test_mediator_event_times_are_offset_aware_local() -> None:
    event = map_event({"Event": "IMAGE-SAVE", "Time": "2026-09-03T23:26:19.36-05:00"},
                      generation="g1")
    assert event.time.utcoffset() is not None


def test_ts_event_times_are_naive_utc() -> None:
    """Two naive formats, indistinguishable by shape — key on the event name."""
    event = map_event({"Event": "TS-TARGETSTART", "Time": "2026-09-04T02:15:32.78"},
                      generation="g1")
    assert event.time.utcoffset().total_seconds() == 0


def test_log_scraped_event_times_are_local_and_still_offset_aware() -> None:
    """Left naive, the first ERROR-PLATESOLVE to land beside 600 offset-aware
    events crashes fold()'s sorted iteration with "can't compare offset-naive
    and offset-aware datetimes". Every NinaEvent.time is aware."""
    from datetime import timedelta

    event = map_event({"Event": "ERROR-PLATESOLVE", "Time": "2026-09-03T21:54:26.93"},
                      generation="g1", rig_offset=timedelta(hours=-5))
    assert event.time.utcoffset() == timedelta(hours=-5)


def test_every_event_class_sorts_together() -> None:
    """The property that matters: one comparable ordering across all three."""
    from datetime import timedelta

    offset = timedelta(hours=-5)
    events = [
        map_event({"Event": "IMAGE-SAVE", "Time": "2026-09-03T23:26:19.36-05:00"},
                  "g1", rig_offset=offset),
        map_event({"Event": "TS-TARGETSTART", "Time": "2026-09-04T02:15:32.78"},
                  "g1", rig_offset=offset),
        map_event({"Event": "ERROR-PLATESOLVE", "Time": "2026-09-03T21:54:26.93"},
                  "g1", rig_offset=offset),
    ]
    # TS-* is naive UTC, so 02:15:32.78 is 21:15 local and sorts FIRST — before
    # the 21:54 local ERROR-PLATESOLVE. Reading the three wall-clock strings and
    # assuming they order as written gets this backwards.
    assert [e.name for e in sorted(events, key=lambda e: e.time)] == [
        "TS-TARGETSTART", "ERROR-PLATESOLVE", "IMAGE-SAVE"]


def test_idle_flat_wizard_iterations_are_not_a_count() -> None:
    """-1 through a completed Target Scheduler flat run — confirmed."""
    status = map_flats_status(load("dawn_flats_status_idle.json"))
    assert status.total_iterations is None
    assert status.completed_iterations is None


@pytest.mark.parametrize("raw", ["running", "Running", "STOPPED", "stopped"])
def test_livestack_status_compares_case_insensitively(raw: str) -> None:
    """The OpenAPI enum is [running, stopped]; a live rig returned "Stopped"."""
    status = map_livestack_status({"Status": raw})
    assert status.running is (raw.lower() == "running")
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_v2_mapper.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""wire → models.

Every wire quirk lives here and nowhere else:

  - "NaN" → None across every numeric field, no allowlist. .NET serializes
    double.NaN as a JSON string, and the sentinel is overloaded — disconnected,
    momentarily unreadable, and not implemented by this driver all look alike.
  - HFR 0 → None. It is the reliable calibration marker: all 67 flats in one
    session reported HFR 0 and Stars -1, but a dark reported HFR 0 and Stars 1.
    Never key calibration on Stars.
  - TimeToMeridianFlip 24 → None when tracking is off. 12 h is legitimate — it
    means "just flipped" — so a "≥12 → unknown" rule would be wrong.
  - Three timestamp classes, two of them naive and indistinguishable by shape,
    keyed by EVENT NAME.
  - TS-* payloads carry "Coordinates": {"RA": [], …} — empty arrays where
    scalars belong.
  - A "Send WebSocket Event" instruction puts a bare string in Response.
  - Flat-panel brightness range is per-device; mount tracking modes come from
    TrackingModes. Never hardcode either.

If a sentinel reaches derive.py, models.py carries sentinel values and the seam
is broken.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import (  # the full model set from Task A9
    CameraModel, DeviceMeta, EquipmentSnapshot, FlatDeviceModel, FlatsStatus,
    Frame, LivestackStatus, MountModel, NinaEvent, WeatherModel,
)

_MERIDIAN_IDLE_SENTINEL = 24.0

# Event name → timezone assumption. Mediator events are offset-aware local and
# need no entry; TS-* are naive UTC; log-scraped ERROR-* are naive local.
EVENT_TIMEZONES: dict[str, str] = {}


def nan_to_none(value: Any) -> Any:
    """The blanket rule."""
    if isinstance(value, str) and value.strip().lower() == "nan":
        return None
    if isinstance(value, float) and value != value:
        return None
    return value


def _number(wire: dict, key: str) -> float | None:
    value = nan_to_none(wire.get(key))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _event_time(name: str, raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is not None:
        return parsed
    if name.startswith("TS-"):
        return parsed.replace(tzinfo=UTC)
    return parsed          # log-scraped: naive local, left naive deliberately
```

…plus one `map_*` function per Interfaces entry, each doing nothing but reading
the wire and constructing a model. Two rules for the implementer:

- **`map_frame` decides calibration on `HFR == 0`.** When it holds, both `hfr`
  and `stars` are `None`; `mean`, `median` and the ADU statistics survive,
  because they are real measurements of a real flat.
- **`map_equipment_info` returns `None` for a device that has never carried a
  `DeviceId`**, and a model with `connected=False` for one that has. It does
  **not** key on the device block's presence: all eleven blocks are always
  emitted. The latch lives in the coordinator, so a device that disconnects
  mid-session stays present with `connected=False`.

- [ ] **Step 4: Run, and check the floor**

```bash
uv run pytest tests/unit/test_v2_mapper.py -v
uv run coverage run -m pytest tests/unit -p no:homeassistant && uv run coverage json
uv run python scripts/coverage_floors.py
```

Expected: tests PASS; `api/v2/mapper.py` ≥ 90%.

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/api/v2/mapper.py \
        tests/unit/test_v2_mapper.py
git commit -m "feat: map the wire into models, normalizing every sentinel"
```

---

## Task A12: `derive.py`

**Files:**
- Create: `custom_components/nina_astrophotography/derive.py`
- Test: `tests/unit/test_derive.py`

**Interfaces:**
- Consumes: `api/models.py` (A9). **Never** a dict, never a sentinel.
- Produces:
  - `session_start(moment: datetime, rollover_hour: int = 12) -> datetime`
  - `image_scale_arcsec_per_px(pixel_size_um: float, focal_length_mm: float) -> float | None`
  - `hfr_arcsec(hfr_px: float, scale_arcsec_per_px: float) -> float | None`
  - `hours_to_meridian(right_ascension_hours: float, sidereal_time_hours: float) -> float`
  - `time_to_meridian_flip(hours_to_meridian: float, max_minutes_after_meridian: float, *, flipped: bool = False) -> float`
  - `flip_threshold_minutes(warning_minutes: float, min_minutes_after: float, max_minutes_after: float) -> float`

`sequence_progress` is deliberately **not** here: the `/sequence/json` walk is
not pure — the tree shape is partly a Target Scheduler fact — so the mapper
normalizes it into a `SequenceNode` first and the walk lives with the platform
that displays it.

- [ ] **Step 1: Write the failing test**

```python
"""Pure, version-independent maths. No wire vocabulary reaches this module."""
from datetime import datetime, timedelta

import pytest

from nina_astrophotography.derive import (
    flip_threshold_minutes,
    hfr_arcsec,
    hours_to_meridian,
    image_scale_arcsec_per_px,
    session_start,
    time_to_meridian_flip,
)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        # A real midnight-spanning night: both frames belong to one session.
        ("2026-09-03T21:39:10-05:00", "2026-09-03T12:00:00-05:00"),
        ("2026-09-04T02:35:12-05:00", "2026-09-03T12:00:00-05:00"),
        # Exactly noon starts the new session.
        ("2026-09-04T12:00:00-05:00", "2026-09-04T12:00:00-05:00"),
        ("2026-09-04T11:59:59-05:00", "2026-09-03T12:00:00-05:00"),
    ],
)
def test_the_session_boundary_is_the_most_recent_local_noon(moment, expected) -> None:
    assert session_start(datetime.fromisoformat(moment)) == datetime.fromisoformat(expected)


def test_the_rollover_hour_is_configurable() -> None:
    moment = datetime.fromisoformat("2026-09-04T10:00:00-05:00")
    assert session_start(moment, rollover_hour=8) == datetime.fromisoformat(
        "2026-09-04T08:00:00-05:00"
    )


def test_image_scale_is_the_standard_206_265_formula() -> None:
    """This rig: CameraInfo.PixelSize 3.76 um, every frame's FocalLength 500 mm."""
    assert image_scale_arcsec_per_px(3.76, 500.0) == pytest.approx(1.5511, abs=1e-4)


def test_image_scale_is_none_without_a_focal_length() -> None:
    """Absent, not zero: a missing reading must not become a division by zero."""
    assert image_scale_arcsec_per_px(3.76, 0.0) is None


def test_binning_multiplies_the_scale() -> None:
    """At bin 2 the true scale is 2x, so an unbinned formula halves every
    derived arcsecond figure."""
    assert image_scale_arcsec_per_px(3.76, 500.0, binning=2) == pytest.approx(
        3.1022, abs=1e-4)


def test_hfr_in_arcseconds_is_pixels_times_scale() -> None:
    """The last light frame of the captured night: HFR 1.4545 px at 1.5511."""
    assert hfr_arcsec(1.4545, 1.5511) == pytest.approx(2.2561, abs=1e-4)


def test_hours_to_meridian_matches_the_rig() -> None:
    """LST 21.021944, RA 22.071111 → 01:02:57, verified to the second (§11)."""
    assert hours_to_meridian(22.071111, 21.021944) * 3600 == pytest.approx(
        1 * 3600 + 2 * 60 + 57, abs=1
    )


def test_time_to_meridian_flip_adds_the_profile_offset() -> None:
    assert time_to_meridian_flip(1.0, max_minutes_after_meridian=15.0) == pytest.approx(1.25)


def test_an_already_flipped_mount_is_twelve_hours_out() -> None:
    assert time_to_meridian_flip(1.0, 15.0, flipped=True) == pytest.approx(13.25)


def test_the_flip_warning_threshold_is_not_a_bare_number() -> None:
    """The flip fires at (Max − Min), not zero, so `below: 10` warns AT the flip."""
    assert flip_threshold_minutes(warning_minutes=10, min_minutes_after=5,
                                  max_minutes_after=15) == 20
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_derive.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""Pure, version-independent maths.

Nothing here knows a wire format, and nothing here sees a sentinel: by the time
a value arrives, api/v2/mapper.py has already turned "NaN", HFR 0 and the
meridian 24 into None.

The /sequence/json walk is deliberately absent — the tree shape is partly a
Target Scheduler fact, so the mapper normalizes it into a SequenceNode first.
"""
from __future__ import annotations

from datetime import datetime, timedelta

_ARCSEC_PER_RADIAN_MICRON_MM = 206.265


def session_start(moment: datetime, rollover_hour: int = 12) -> datetime:
    """The most recent local noon at or before `moment`.

    This is what an astrophotographer means by a session, and what N.I.N.A.'s
    own image-history dockable and Target Scheduler mean. It needs no events,
    and it is correct both when N.I.N.A. restarts mid-day and when it runs for
    days across several nights.
    """
    boundary = moment.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
    return boundary if moment >= boundary else boundary - timedelta(days=1)


def image_scale_arcsec_per_px(pixel_size_um: float, focal_length_mm: float,
                              binning: int = 1) -> float | None:
    """206.265 × pixel size (µm) × binning ÷ focal length (mm).

    The focal length is the frame's own, not the active profile's — it is the
    value in force for that frame.

    Binning comes from CameraInfo.BinX on the fast tier, because /image-history
    frames do not carry it. So an arcsecond figure is only trustworthy for
    frames shot at the camera's current binning; a historical frame shot at a
    different bin is scaled wrongly and there is no wire field that would let us
    know. Say so wherever the derived value is surfaced.
    """
    if not focal_length_mm:
        return None
    return _ARCSEC_PER_RADIAN_MICRON_MM * pixel_size_um * binning / focal_length_mm


def hfr_arcsec(hfr_px: float | None, scale_arcsec_per_px: float | None) -> float | None:
    """HFR in arcseconds — the figure that is comparable between rigs."""
    if hfr_px is None or scale_arcsec_per_px is None:
        return None
    return hfr_px * scale_arcsec_per_px


def hours_to_meridian(right_ascension_hours: float, sidereal_time_hours: float) -> float:
    """(RA_JNOW − LST) mod 12.

    RA here is the mount's own epoch and in hours, as MountInfo reports it —
    never the J2000 degrees /equipment/mount/slew takes.
    """
    return (right_ascension_hours - sidereal_time_hours) % 12


def time_to_meridian_flip(hours_to_meridian: float, max_minutes_after_meridian: float,
                          *, flipped: bool = False) -> float:
    """Hours until the flip fires.

    `MountInfo.TimeToMeridianFlip` is AUTHORITATIVE — it is the number N.I.N.A.
    itself acts on, and publishing a derived value that disagrees with it is
    worse than not deriving one. This exists for the MeridianFlipSettings-aware
    secondary warning threshold only.

    Wrapped mod 12 because `hours_to_meridian` is itself mod 12: just after
    transit it reads ~11.99, and 11.99 + 0.25 + 12 = 24.24 would collide with
    the 24-hour "tracking off" sentinel the mapper nulls.
    """
    value = hours_to_meridian + max_minutes_after_meridian / 60
    return (value + 12 if flipped else value) % 24


def flip_threshold_minutes(warning_minutes: float, min_minutes_after: float,
                           max_minutes_after: float) -> float:
    """Minutes-to-flip at which a warning should fire.

    The flip fires when TimeToMeridianFlip reaches (Max − Min), not zero, so a
    bare `below: 10` warns exactly at the flip. Both bounds are per-profile, so
    a bare numeric threshold is not portable between rigs.
    """
    return warning_minutes + (max_minutes_after - min_minutes_after)
```

- [ ] **Step 4: Run and check the floor**

```bash
uv run pytest tests/unit/test_derive.py -v
uv run coverage run -m pytest tests/unit -p no:homeassistant && uv run coverage json
uv run python scripts/coverage_floors.py
```

Expected: tests PASS; `derive.py` ≥ 95%.

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/derive.py tests/unit/test_derive.py
git commit -m "feat: add the pure derivation maths"
```

---

## Task A13: `session.py` — the fold

**Files:**
- Create: `custom_components/nina_astrophotography/session.py`
- Modify: `custom_components/nina_astrophotography/api/models.py` (add
  `SessionStats`, `AutoFocusState`, `TargetBreakdown`)
- Test: `tests/unit/test_session.py`, `tests/unit/test_session_properties.py`

**Interfaces:**
- Consumes: `Frame`, `NinaEvent` (A9); `derive.session_start` (A12).
- Produces:
  - `fold(frames: Iterable[Frame], events: Iterable[NinaEvent], generation: str | None, *, autofocus_timeout_seconds: float = 300.0, now: datetime | None = None, rollover_hour: int = 12) -> SessionStats`
  - `SessionStats(session_start, image_count, light_count, integration_seconds,
    hfr_mean, hfr_best, hfr_worst, star_count_mean, last_frame, by_target,
    by_filter, autofocus)`
  - `AutoFocusState(last_success_at, running_since, failed)`
  - `TargetBreakdown(name, count, integration_seconds, hfr_mean)`

- [ ] **Step 1: Write the failing example tests**

```python
"""fold() is pure, idempotent, and order-independent."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nina_astrophotography.api.v2.mapper import map_frame
from nina_astrophotography.session import fold

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def night() -> list:
    document = json.loads(
        (FIXTURES / "dawn_image_history_with_flats.json").read_text(encoding="utf-8")
    )
    document.pop("_meta", None)
    return [map_frame(f, generation="g1") for f in document["Response"]]


def test_integration_time_sums_actual_exposures_of_lights_only(night) -> None:
    """Lights sum to 6.2000 h; all 122 frames sum to 6.2301 h.

    The tolerance is tight deliberately: at abs=0.02 an all-frames
    implementation passes, and integration time is light-frame time.
    """
    stats = fold(night, [], generation="g1")
    assert stats.integration_seconds / 3600 == pytest.approx(6.2000, abs=0.001)


def test_calibration_frames_do_not_drag_the_hfr_aggregate(night) -> None:
    """67 of 122 frames are flats reporting HFR 0."""
    stats = fold(night, [], generation="g1")
    assert stats.hfr_mean == pytest.approx(1.513, abs=0.01)


def test_the_last_frame_is_the_last_light_not_the_last_flat(night) -> None:
    """A dawn flat run left `Last Image Mean ADU` reading 33,139 on 1.4.4."""
    stats = fold(night, [], generation="g1")
    assert stats.last_frame.image_type == "LIGHT"
    assert stats.last_frame.mean == pytest.approx(548.6, rel=0.2)


def test_frames_from_a_previous_generation_are_filtered_not_cleared(night) -> None:
    """A restart is a generation change; clearing races a concurrent poll."""
    stats = fold(night, [], generation="g2")
    assert stats.image_count == 0


def test_the_breakdown_covers_every_target_imaged(night) -> None:
    assert len(fold(night, [], generation="g1").by_target) == 4


def test_the_filter_breakdown_excludes_filters_only_flats_used(night) -> None:
    """All 122 frames carry six filters; the 55 lights carry five — the flats
    add G. A per-filter row for a G flat with no G lights is noise."""
    assert len(fold(night, [], generation="g1").by_filter) == 5


def test_image_count_counts_calibration_frames_too(night) -> None:
    """image_count is every frame; the aggregates are lights only."""
    assert fold(night, [], generation="g1").image_count == 122
    assert fold(night, [], generation="g1").light_count == 55


def test_an_unmatched_autofocus_start_past_the_timeout_is_a_failure() -> None:
    """8 AUTOFOCUS-STARTING against 7 AUTOFOCUS-FINISHED on an ordinary night."""
    from nina_astrophotography.api.models import NinaEvent

    start = datetime.fromisoformat("2026-09-03T23:00:00-05:00")
    events = [NinaEvent("AUTOFOCUS-STARTING", start, {}, "g1")]
    stats = fold([], events, generation="g1",
                 autofocus_timeout_seconds=300,
                 now=start + timedelta(seconds=301))
    assert stats.autofocus.failed is True


def test_an_autofocus_still_inside_its_timeout_has_not_failed() -> None:
    from nina_astrophotography.api.models import NinaEvent

    start = datetime.fromisoformat("2026-09-03T23:00:00-05:00")
    stats = fold([], [NinaEvent("AUTOFOCUS-STARTING", start, {}, "g1")], generation="g1",
                 autofocus_timeout_seconds=300, now=start + timedelta(seconds=60))
    assert stats.autofocus.failed is False
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_session.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
"""The session fold — pure, stateless, idempotent.

The coordinator owns the accumulated frame and event set; this module receives
it as an argument and returns a value. That is what makes push, poll and
/event-history replay the same operation, so arrival order stops mattering.

Frame identity is (Date, Filename), confirmed present and identical on both the
push and poll paths. Date is the SAVE time — start + exposure + download — so
anything reasoning about when a frame was taken must subtract ExposureTime.

Aggregates are computed once from a deterministic sorted iteration, never
accumulated incrementally: order-independence over floats is false under
incremental accumulation, and frozen-dataclass equality is exact.

The process boundary is the generation tag, applied by FILTERING. Clearing races
a concurrent poll, produces a false positive on the first read when no baseline
exists, and loses events arriving during the refetch.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from statistics import fmean

from .api.models import AutoFocusState, Frame, NinaEvent, SessionStats, TargetBreakdown
from .derive import session_start


def _identity(frame: Frame) -> tuple[datetime, str]:
    return (frame.date, frame.filename)


def fold(frames: Iterable[Frame], events: Iterable[NinaEvent],
         generation: str | None, *, autofocus_timeout_seconds: float = 300.0,
         now: datetime | None = None, rollover_hour: int = 12) -> SessionStats:
    ...
```

The implementation is a set-union on `_identity`, a generation filter, a
`session_start` filter, then sorted aggregation. Two rules the tests above pin:

- **Scope, stated once and tested three ways.** `image_count` counts every
  frame. `light_count`, `integration_seconds`, `by_target`, `by_filter`,
  `hfr_mean`, `hfr_best`, `hfr_worst` and `star_count_mean` are over
  `image_type == "LIGHT"` only. Verified against the captured night: lights
  6.2000 h / 5 filters / HFR mean 1.51305, min 1.42873, max 1.89118 — matching
  §5.2.4's 1.513 / 1.429 / 1.891 to three decimals.
- **`last_frame` is the newest frame whose `image_type == "LIGHT"`**, not the
  newest frame. A dawn flat run is what produced `Last Image Mean ADU 33139.77`
  on 1.4.4 (§5.2.4). Note that an API-initiated capture sets `TargetName` to
  `"Snapshot"`, so a light captured through the API would still land here — the
  `by_target` breakdown will show it, which is the honest outcome.

- [ ] **Step 4: Write the three properties**

```python
"""Properties of the fold, sampled from the 122 real captured frames.

Every generated input is real wire data — hypothesis samples the corpus rather
than inventing frames, so a passing property says something about N.I.N.A.
"""
from __future__ import annotations

import json
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nina_astrophotography.api.v2.mapper import map_frame
from nina_astrophotography.session import fold

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_document = json.loads(
    (FIXTURES / "dawn_image_history_with_flats.json").read_text(encoding="utf-8")
)
_document.pop("_meta", None)
FRAMES = [map_frame(f, generation="g1") for f in _document["Response"]]

settings.register_profile("nina", max_examples=50, deadline=None, derandomize=True,
                          suppress_health_check=[HealthCheck.function_scoped_fixture])
settings.load_profile("nina")


@given(st.lists(st.sampled_from(FRAMES), min_size=1, max_size=30))
def test_fold_is_idempotent(sample) -> None:
    assert fold(sample + sample, [], "g1") == fold(sample, [], "g1")


@given(st.permutations(FRAMES[:20]))
def test_fold_is_order_independent(shuffled) -> None:
    assert fold(shuffled, [], "g1") == fold(FRAMES[:20], [], "g1")


@given(st.sampled_from(FRAMES))
def test_the_same_frame_by_any_path_folds_to_one_entry(frame) -> None:
    """Push, poll and replay are one idempotent operation."""
    assert fold([frame, frame, frame], [], "g1").image_count == 1
```

- [ ] **Step 5: Run everything and check the floor**

```bash
uv run pytest tests/unit/test_session.py tests/unit/test_session_properties.py -v
uv run coverage run -m pytest tests/unit -p no:homeassistant && uv run coverage json
uv run python scripts/coverage_floors.py
```

Expected: PASS; `session.py` ≥ 95%.

- [ ] **Step 6: Commit**

```bash
git add custom_components/nina_astrophotography/session.py \
        custom_components/nina_astrophotography/api/models.py \
        tests/unit/test_session.py tests/unit/test_session_properties.py
git commit -m "feat: fold frames and events into session statistics, purely"
```

---

## Task A14: Coordinator, runtime data and the entity base

**Files:**
- Create: `custom_components/nina_astrophotography/entity.py`
- Rewrite: `custom_components/nina_astrophotography/coordinator.py`
- Modify: `custom_components/nina_astrophotography/__init__.py`
- Test: `tests/ha/test_setup.py`

**Interfaces:**
- Consumes: `NinaClientV2` (A10), the mapper (A11), `fold` (A13), the errors (A8).
- Produces:
  - `NinaData(snapshot: EquipmentSnapshot, session: SessionStats, sequence: SequenceNode | None, flats: FlatsStatus, livestack: LivestackStatus, profile: ProfileSettings, generation: str | None, version: VersionInfo)` — frozen.
  - `NinaCoordinator(DataUpdateCoordinator[NinaData])` with
    `.client: NinaClientV2`, `.frames: dict[tuple[datetime, str], Frame]`,
    `.events: list[NinaEvent]`, `.generation: str | None`.
  - `NinaRuntimeData(client: NinaClientV2, coordinator: NinaCoordinator, service_client: NinaApiClient, instance_name: str)`;
    `type NinaConfigEntry = ConfigEntry[NinaRuntimeData]`.
  - `NinaEntity(CoordinatorEntity[NinaCoordinator])` with
    `_attr_has_entity_name = True` and
    `__init__(coordinator: NinaCoordinator, entry: NinaConfigEntry, key: str)`
    setting `_attr_unique_id = f"{entry.entry_id}_{key}"`. It takes the **entry**,
    not the entry id, because phase B needs `runtime_data.instance_name` from
    it; every call site in every phase passes `entry`.

- [ ] **Step 1: Write the failing HA test**

```python
"""Setup and unload, through public interfaces only."""
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import (
    NinaConnectionError,
    NinaEndpointError,
)

CLIENT = "custom_components.nina_astrophotography.api.v2.client.NinaClientV2"


async def test_setup_stores_state_on_runtime_data_not_hass_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    """Bronze runtime-data: a module-level dict keyed by entry_id leaks."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.runtime_data.coordinator is not None
    from custom_components.nina_astrophotography.const import DOMAIN
    assert DOMAIN not in hass.data


async def test_an_unreachable_rig_retries_rather_than_failing_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    with patch(f"{CLIENT}.get_version", side_effect=NinaConnectionError("refused")):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_a_build_that_does_not_serve_the_api_fails_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A wrong path never becomes right — ConfigEntryError, not NotReady."""
    config_entry.add_to_hass(hass)
    with patch(f"{CLIENT}.get_version", side_effect=NinaEndpointError("no /version")):
        await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_the_services_still_reach_a_client_after_the_move_to_runtime_data(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    """Moving off hass.data[DOMAIN] empties what _get_client iterates.

    Without this test the 19 services fail silently from phase A until phase C.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    with patch(
        "custom_components.nina_astrophotography.api.NinaApiClient.park_mount"
    ) as park:
        await hass.services.async_call(DOMAIN, "mount_park", {}, blocking=True)
    assert park.called


async def test_unload_leaves_no_state_behind(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses
) -> None:
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    # The claim is that nothing survives the unload — not that HA's own unload
    # machinery works, which is Home Assistant's test to write.
    from custom_components.nina_astrophotography.const import DOMAIN
    assert DOMAIN not in hass.data
```

Add the `nina_responses` fixture to `tests/ha/conftest.py` — a fixture-backed
transport stub, so the real client's envelope logic is exercised (§8.7):

```python
@pytest.fixture
def nina_responses(monkeypatch):
    """Serve captured fixtures through the real client's envelope handling."""
    import json
    from pathlib import Path

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"

    def _response(name: str):
        document = json.loads((fixtures / name).read_text(encoding="utf-8"))
        document.pop("_meta", None)
        return document["Response"]

    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    monkeypatch.setattr(NinaClientV2, "get_version", lambda self: _async("2.2.15.2"))
    monkeypatch.setattr(NinaClientV2, "get_equipment",
                        lambda self: _async(map_equipment_info(
                            _response("dawn_equipment_info.json"))))
    monkeypatch.setattr(NinaClientV2, "get_image_history_count", lambda self: _async(122))
    monkeypatch.setattr(NinaClientV2, "get_application_start",
                        lambda self: _async("2026-09-04T10:58:59"))
    return _response


async def _async(value):
    return value
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/ha/test_setup.py -v
```

Expected: FAIL — `runtime_data` is not set; the integration still uses
`hass.data[DOMAIN]`.

- [ ] **Step 3: Settle `NinaData`'s shape on paper first**

This is the riskiest decision in phase A. Every phase-C platform reads
`NinaData` through a one-line lambda, so a field the snapshot cannot supply
reopens the coordinator in a later PR. Before writing the dataclass, walk the
entity tables in phase C Tasks C1–C9 and confirm each one's `value` lambda is
expressible. The four that are easy to miss:

| Entity | Needs |
|---|---|
| weather channels (§5.2.2) | the `DeviceId` that last produced a non-`NaN` reading, **per channel** — not just the current source |
| `sensor.session_start` | `now`-derived, so `fold` needs the clock, not just frames |
| per-instruction sequence status | a normalized `SequenceNode` tree, not the raw list |
| `binary_sensor.sequence_running` | the activity heuristic's inputs, which span two tiers |

Write them into `NinaData` now or record explicitly why not.

- [ ] **Step 4: Rewrite `coordinator.py`**

```python
"""The single DataUpdateCoordinator.

It owns the accumulated frame and event set. session.py is stateless and
receives that set as an argument.

All mutation happens on the event loop, and NinaData is assembled from the live
set at the moment of publication with no `await` between reading the set and
freezing the dataclass. Four writers touch it — the poll, the WebSocket
callback, /event-history replay and the restart reseed — and without that rule a
poll awaiting /equipment/info while IMAGE-SAVE arrives publishes a snapshot
assembled from a pre-event read, so the frame appears, vanishes and reappears.

Phase A polls the fast tier only. Tiering, the push path and generation handling
land in phase B.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.errors import NinaEndpointError, NinaError, NinaRequestError
from .api.models import (
    EquipmentSnapshot, FlatsStatus, Frame, LivestackStatus, NinaEvent,
    ProfileSettings, SequenceNode, SessionStats, VersionInfo,
)
from .api.v2 import NinaClientV2
from .session import fold

_LOGGER = logging.getLogger(__name__)

FAST_INTERVAL = timedelta(seconds=10)


@dataclass(frozen=True, slots=True)
class NinaData:
    """One published snapshot. Frozen, and assembled without awaiting."""

    snapshot: EquipmentSnapshot
    session: SessionStats
    sequence: SequenceNode | None
    flats: FlatsStatus
    livestack: LivestackStatus
    profile: ProfileSettings
    generation: str | None
    version: VersionInfo


class NinaCoordinator(DataUpdateCoordinator[NinaData]):
    def __init__(self, hass: HomeAssistant, client: NinaClientV2) -> None:
        super().__init__(hass, _LOGGER, name="N.I.N.A. Astrophotography",
                         update_interval=FAST_INTERVAL)
        self.client = client
        self.frames: dict[tuple[datetime, str], Frame] = {}
        self.events: list[NinaEvent] = []
        self.generation: str | None = None

    async def _async_update_data(self) -> NinaData:
        try:
            snapshot = await self.client.get_equipment()
            generation = await self.client.get_application_start()
            count = await self.client.get_image_history_count()
        except (NinaRequestError, NinaEndpointError) as exc:
            # Neither becomes right by retrying. Log once and keep the previous
            # snapshot rather than making every entity unavailable.
            _LOGGER.error("N.I.N.A. rejected a request: %s", exc)
            if self.data is not None:
                return self.data
            raise UpdateFailed(str(exc)) from exc
        except NinaError as exc:
            raise UpdateFailed(str(exc)) from exc

        self.generation = generation
        return NinaData(
            snapshot=snapshot,
            session=fold(self.frames.values(), self.events, generation),
            sequence=None, flats=..., livestack=..., profile=...,
            generation=generation, version=...,
        )
```

The `...` placeholders above are filled by phase B, which adds the tiers that
fetch them; in phase A construct each from its module's documented empty value
(`FlatsStatus(None, None, None)`, `LivestackStatus(False, "")`, and so on) so
`NinaData` is always complete. `count` is unused in phase A — it becomes the
invariant check in phase B; assign it to `_` with a comment rather than dropping
the call, so the fast tier's byte cost is real from the start.

- [ ] **Step 5: Write `entity.py`**

```python
"""The shared entity base.

Bronze common-modules puts it here; Bronze has-entity-name means every entity
name derives from its device, so `_attr_name` is the channel, never the rig.
"""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NinaCoordinator


class NinaEntity(CoordinatorEntity[NinaCoordinator]):
    """Base for every N.I.N.A. entity."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: NinaCoordinator, entry: NinaConfigEntry,
                 key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
```

Device linking arrives in phase B with `device.py`; in phase A `light.py` sets
`_attr_device_info` itself so the slice is complete without pre-empting B.

- [ ] **Step 6: Rewire `__init__.py`**

Four changes, and only four:

1. `PLATFORMS = [Platform.LIGHT]`, with a comment naming the phase-C PR that
   re-adds each platform.
2. Construct `NinaClientV2` and use `client.get_version()` for the
   test-before-setup probe, mapping `NinaEndpointError` → `ConfigEntryError` and
   `NinaConnectionError`/`NinaUnavailableError` → `ConfigEntryNotReady`.
3. Replace `hass.data[DOMAIN][entry.entry_id] = {...}` with
   `entry.runtime_data = NinaRuntimeData(...)`, and delete the `hass.data`
   teardown in `async_unload_entry`.
4. **Rewrite `_get_client` in the same commit.** It currently iterates
   `hass.data.get(DOMAIN, {}).values()`, which this task makes permanently
   empty — so every one of the 19 `nina.*` services would raise
   `ValueError("No N.I.N.A. integration configured")` from phase A until phase
   C, and nothing tests a service before phase D. Keep the existing
   `NinaApiClient` as `runtime_data.service_client` and read it from the entry:

```python
def _get_client(hass: HomeAssistant) -> NinaApiClient:
    """Return the first loaded entry's service client.

    Still "first entry wins" — phase D replaces this with device targeting.
    What changes here is only where the client is stored.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        return entry.runtime_data.service_client
    raise ServiceValidationError("No N.I.N.A. instance is configured")
```

   Leave the websocket/frame-store block otherwise untouched — phase B replaces
   the socket.

- [ ] **Step 7: Run both suites**

```bash
uv run pytest tests/unit -p no:homeassistant -q
uv run pytest tests/ha -q
```

Expected: unit 101+ passed; `tests/ha` 6 passed.

- [ ] **Step 8: Commit**

```bash
git add custom_components/nina_astrophotography/coordinator.py \
        custom_components/nina_astrophotography/entity.py \
        custom_components/nina_astrophotography/__init__.py \
        tests/ha
git commit -m "feat: coordinate on NinaData and move state to runtime_data"
```

---

## Task A15: `light.py` end-to-end — the vertical slice

**Files:**
- Rewrite: `custom_components/nina_astrophotography/light.py`
- Test: `tests/ha/test_light.py`, `tests/unit/test_v2_client.py` (extend)

**Interfaces:**
- Consumes: `NinaEntity` (A14), `NinaData.snapshot.flat_device` (A9/A11),
  `NinaClientV2.set_flat_light` / `.set_flat_brightness` (A10).
- Produces: `light.nina_flat_panel_light`, gated on `SupportsOnOff`.

`light.py` closes phase A deliberately: it is the vertical slice **and** it
carries §5.3.4's three fixes, so per-device range scaling and
`action-exceptions` semantics are settled on one entity before the rest depend
on them.

- [ ] **Step 1: Write the failing tests**

```python
"""The flat panel light — §5.3.4's three fixes, on real hardware numbers."""
import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

ENTITY = "light.n_i_n_a_astrophotography_flat_panel_light"


async def test_brightness_scales_into_the_drivers_own_range(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    """This panel reports MaxBrightness 4096; an Alnitak reports 255."""
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY, ATTR_BRIGHTNESS: 255}, blocking=True,
    )
    assert sent.brightness == 4096


async def test_the_reported_brightness_is_scaled_back_into_ha_units(
    hass: HomeAssistant, flat_panel_entry
) -> None:
    """The raw driver value handed HA 4096 into a property defined as 0-255.

    The fixture panel sits at driver 2048 of 4096, so HA should read 128.
    """
    assert hass.states.get(ENTITY).attributes[ATTR_BRIGHTNESS] == 128


async def test_a_bare_turn_on_does_not_go_to_full_output(
    hass: HomeAssistant, idle_flat_panel_entry, sent
) -> None:
    """THE safety test on this entity.

    A bare set-light?on=true jumps to MaxBrightness — measured 0 to 4096 — and a
    light that comes on at full output is a hazard in a shared observatory. The
    panel's ordinary idle state is Brightness 0, which is exactly the state that
    tempts a falsy-fallback implementation into sending 255.
    """
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True,
    )
    assert sent.brightness <= 4096 // 4


async def test_a_bare_turn_on_restores_the_last_level_used(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: ENTITY, ATTR_BRIGHTNESS: 64}, blocking=True)
    await hass.services.async_call(
        LIGHT_DOMAIN, "turn_off", {ATTR_ENTITY_ID: ENTITY}, blocking=True)
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY}, blocking=True)
    assert sent.brightness == 1028   # round(64 / 255 * 4096)


# Client-side range validation is NOT tested here: Home Assistant's own light
# schema rejects a brightness outside 0-255 before our code runs, so such a test
# would be testing Home Assistant. The driver-range clamp that matters —
# set-brightness?brightness=99999 silently clamping and answering Success: true —
# is covered on number.flat_panel_brightness in phase C Task C2.


async def test_a_disconnected_panel_reporting_a_zero_range_is_unavailable(
    hass: HomeAssistant, disconnected_flat_panel_entry
) -> None:
    """Min 0, Max 0 is the ordinary startup state, not a division by zero."""
    assert hass.states.get(ENTITY).state == "unavailable"


async def test_turn_off_uses_set_light_not_brightness_zero(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    """Brightness 0 is not off."""
    await hass.services.async_call(
        LIGHT_DOMAIN, "turn_off", {ATTR_ENTITY_ID: ENTITY}, blocking=True,
    )
    assert sent.last_call == ("set_flat_light", False)


async def test_a_panel_that_cannot_switch_its_light_is_unavailable_not_absent(
    hass: HomeAssistant, cover_only_flat_panel_entry
) -> None:
    """A cover-only panel keeps the entity and reports unavailable, so it does
    not appear and disappear across restarts."""
    assert hass.states.get(ENTITY).state == "unavailable"
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/ha/test_light.py -v
```

Expected: FAIL — the entity still reads `coordinator.data["flatdevice"]`.

- [ ] **Step 3: Rewrite `light.py`**

```python
"""Flat panel light.

Brightness is per-device, not 0-255: this rig's panel reports MaxBrightness
4096, the owner's previous one 256, and Alnitak Flat-Man and Flip-Flat report
255 — which is why the 0-255 assumption survived. Scale between the driver's own
MinBrightness and MaxBrightness in both directions.

turn_on always sends a brightness. A bare set-light?on=true jumps to
MaxBrightness, and a light that turns on at full output is a hazard in a shared
observatory.

Do not verify by readback: the API's commands are asynchronous and answer
Success: true before the state changes. FLAT-LIGHT-TOGGLED carries an empty
payload and FLAT-BRIGHTNESS-CHANGED fires repeatedly through a ramp with
inconsistent Previous values — both are change hints, nothing more.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .coordinator import NinaCoordinator
from .entity import NinaEntity

# Silver parallel-updates: one in-flight command per command platform. This
# constrains entity calls only; the services are unaffected.
PARALLEL_UPDATES = 1

_HA_MAX = 255


class NinaFlatLight(NinaEntity, LightEntity):
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_translation_key = "flat_panel_light"

    # Remembered across turn_off/turn_on within one HA run. Restored from the
    # panel whenever it is observed lit, so a restart mid-session recovers it.
    _DEFAULT_ON_BRIGHTNESS = 1

    def __init__(self, coordinator, entry, key: str) -> None:
        super().__init__(coordinator, entry, key)
        self._remembered: int | None = None

    @property
    def _last_on_brightness(self) -> int:
        """The level to restore on a bare turn_on. Dim by default, never full."""
        if self._remembered is not None:
            return self._remembered
        current = self.brightness
        return current if current else self._DEFAULT_ON_BRIGHTNESS

    @property
    def _panel(self):
        return self.coordinator.data.snapshot.flat_device

    @property
    def available(self) -> bool:
        panel = self._panel
        return bool(super().available and panel and panel.connected
                    and (panel.max_brightness or 0) > 0)

    @property
    def is_on(self) -> bool | None:
        return None if self._panel is None else self._panel.light_on

    @property
    def brightness(self) -> int | None:
        """The driver's value, scaled into HA's 0-255."""
        panel = self._panel
        if panel is None or panel.brightness is None:
            return None
        span = (panel.max_brightness or 0) - (panel.min_brightness or 0)
        if span <= 0:
            return None
        fraction = (panel.brightness - (panel.min_brightness or 0)) / span
        return round(fraction * _HA_MAX)

    def _to_driver(self, ha_brightness: int) -> int:
        panel = self._panel
        if not 1 <= ha_brightness <= _HA_MAX:
            # Out-of-range input is silently clamped and answers Success: true.
            raise ServiceValidationError(
                f"Brightness must be between 1 and {_HA_MAX}, got {ha_brightness}"
            )
        low, high = panel.min_brightness or 0, panel.max_brightness or 0
        return round(low + (ha_brightness / _HA_MAX) * (high - low))

    async def async_turn_on(self, **kwargs: Any) -> None:
        # NEVER fall back to _HA_MAX. The panel's ordinary idle state is
        # Brightness 0 / LightOn false, which scales to 0 — falsy — so
        # `self.brightness or _HA_MAX` sends 255 -> 4096 and the panel comes on
        # at full output on any dashboard tap, scene or homeassistant.turn_on.
        # That is exactly the hazard this entity exists to prevent.
        requested = int(kwargs.get(ATTR_BRIGHTNESS, self._last_on_brightness))
        driver_value = self._to_driver(requested)
        try:
            # Brightness first, then the light: this ordering is what prevents
            # the flash even when the requested level is low.
            await self.coordinator.client.set_flat_brightness(driver_value)
            if not self.is_on:
                await self.coordinator.client.set_flat_light(True)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the flat panel: {exc}") from exc
        self._remembered = requested
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        try:
            # Brightness 0 is not off.
            await self.coordinator.client.set_flat_light(False)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the flat panel: {exc}") from exc
        await self.coordinator.async_request_refresh()


async def async_setup_entry(hass: HomeAssistant, entry, 
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator: NinaCoordinator = entry.runtime_data.coordinator
    panel = coordinator.data.snapshot.flat_device
    # Gate on the panel having been OBSERVED, not on SupportsOnOff being true
    # right now: a disconnected panel reports Min 0 / Max 0 and SupportsOnOff
    # false, which is the ordinary startup state. Gating on it would make the
    # light vanish on every restart that beat the panel's connection.
    # `available` carries the disconnected state instead. §5.2.2.
    if panel is not None:
        async_add_entities([NinaFlatLight(coordinator, entry, "flat_panel_light")])
```

Add `flat_panel_light` to `strings.json`'s `entity.light` block so
`_attr_translation_key` resolves.

- [ ] **Step 4: Delete the duplicate switch**

`light.…flat_panel_light` and `switch.…flat_panel_light` both exist today for
one device. The `light` survives — remove the switch entity from `switch.py`
(the module is unregistered in phase A, so this is a deletion, not a migration).

- [ ] **Step 5: Run both suites and the floors**

```bash
uv run pytest tests/unit -p no:homeassistant -q
uv run pytest tests/ha -q
uv run coverage combine && uv run coverage json && uv run python scripts/coverage_floors.py
```

Expected: both green; `derive.py`, `session.py` and `api/v2/mapper.py` above
their floors. `config_flow.py`'s 100% floor is phase B's — record it as an open
item in the PR, do not lower the floor.

- [ ] **Step 6: Commit**

```bash
git add custom_components/nina_astrophotography/light.py \
        custom_components/nina_astrophotography/switch.py \
        custom_components/nina_astrophotography/strings.json tests/ha/test_light.py
git commit -m "feat: rebuild the flat panel light on models, with per-device scaling"
```

---

## Phase A exit criteria

From §12, with the amendment this phase makes:

- [ ] `pytest tests/unit -p no:homeassistant` green (≥101).
- [ ] `pytest tests/ha` green, with the harness proven by the setup and light tests.
- [ ] Six CI jobs green: unit, ha, coverage floors, hassfest, HACS, fixtures.
- [ ] `api/v2/schema.py` regenerates byte-identically from the committed spec.
- [ ] `scripts/capture_fixtures.py` is **stable**: two runs against an unchanged
      rig state produce byte-identical files. It does **not** reproduce the
      committed corpus byte-for-byte, and must not be expected to — those files
      predate the redaction module and carry zeroed coordinates and a
      `SideOfPier` of `"REDACTED"`, both of which the current rules keep. Four
      of them also came from endpoints the script does not capture
      (`/equipment/{flatdevice,mount}/info`, `/sequence/state`), and the naming
      scheme differs (`dawn_image_history_all` vs
      `dawn_image_history_with_flats`). Stability is the property that matters;
      byte-equality with a superseded redactor is not.
- [ ] Drift guard green; `tests/spec_deviations.json` reviewed; the wire-shape
      snapshot reviewed by eye.
- [ ] `light.py` end-to-end on models with its three §5.3.4 fixes.
- [ ] **No platform module changed except `light.py`** (and the duplicate flat
      switch removed from `switch.py`).
- [ ] `docs/v2.0-design.md` amended with both amendments named at the top of
      this plan, and its rev bumped.

## Known gaps in this plan

| Task | What is prose-only | Weight |
|---|---|---|
| A9 `models.py` | ~20 dataclasses, ~130 fields; two are worked | **Largest gap in the phase.** Mechanical, but the field names are the contract every later phase codes against, so get the Interfaces block exactly right before typing |
| A11 `mapper.py` | 8 `map_*` functions; the two hard rules are stated as bullets | The 90% floor lands here; the rules that matter (calibration by `ImageType`, `None` vs disconnected, the rig offset) are written out |
| A13 `fold()` | the body | The scope contract and the three properties fully specify it |
| A14 `__init__.py` rewiring | four numbered changes, one with code | The `_get_client` fix is written; the rest is deletion |

## Self-review notes

Checked against the spec on 2026-09-04:

- **§3.2's request-parameter rule** is covered by Task A10's three pinning
  tests and by the comment block above `set_flat_light`.
- **Three of this plan's own defects were found by executing its code** against
  the captured corpus rather than by reading it: `_digest` was not idempotent so
  `scan()` could never come back clean; `_observe` dropped always-empty
  containers so the `Camera.Gains` and `Mount.TrackingRate` waivers read as
  stale; and the cross-class event sort asserted the wrong order because a naive
  **UTC** `TS-*` timestamp sorts earlier than its wall-clock string suggests. Run
  the code in a plan before trusting it.
- **§8.5's `test_generated_types_deviate_only_where_recorded`** is implemented
  in Task A7 as `test_every_waiver_still_fires` plus the snapshot test. The
  spec's name implies running a type checker over the fixtures; the plan uses
  observed-type extraction instead, because `datamodel-code-generator`'s
  `TypedDict` output is not checkable against runtime data without a third-party
  runtime validator, which would break the `requirements: []` rule for a dev-only
  gain. **This is an amendment to §8.5 and must be recorded in the Task A7 PR.**
- **§6's tiering, `/event-history` replay and generations** are phase B, matching
  §9. Phase A's coordinator polls the fast tier only, and `NinaData` carries the
  empty values for the fields B fills.
- **`config_flow.py`'s 100% floor** is not met in phase A — the config flow is
  not touched until phase B. The floor stays in `scripts/coverage_floors.py` and
  the phase-A PR carries it as a known-red item rather than lowering it.

# Phase D · Services, blueprints, docs, release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the services around device targeting, rebuild the five
blueprints and five cards on the new entity model, rewrite the documentation,
and ship `2.0.0`.

**Architecture:** Services stop guessing which rig they mean —
`_get_client()`'s "first entry wins" is replaced by device targeting, which is
what makes multi-rig actually work. Three services that never worked are
redesigned rather than repaired. Blueprints move onto the signals §3.4 proved
reliable: `MOUNT-BEFORE-FLIP` for the flip, and a two-trigger safety shape —
conditions going unsafe, and the monitor itself disappearing — rather than a
merged state set that fires on every Home Assistant restart.

**Tech Stack:** As phases A–C, plus Home Assistant's device-target selectors and
blueprint schema.

**Spec:** [`docs/v2.0-design.md`](../../v2.0-design.md) (Rev 4). §5.2.1, §6.4,
§10, §11 and §12 are the sections this phase implements.

**Prerequisite:** Phases A, B and C complete.

## Global Constraints

Phases A–C's constraints still bind. In addition:

- **`ServiceValidationError` for bad input, `HomeAssistantError` for genuine
  failure** (Silver `action-exceptions`), platform actions included.
- **A service must not confirm from a command's own response** (§3.5). It
  returns when the API accepts the command; no `Operation` handle exists under
  v2 (§4.5, D-09).
- **`PARALLEL_UPDATES` constrains entity calls only** — the services are
  unaffected, so a script calling three `nina.mount_*` services still fires
  concurrently (§6.4).
- **Weather channels are telemetry, not an abort authority** (§6.4). A
  forecast-backed source reads 0% cloud while you sit under a cloud. Abort
  belongs to `binary_sensor.<instance>_unsafe`. State this in the README *and*
  in the blueprint descriptions.
- **`binary_sensor.<instance>_unsafe` is `on` when conditions are UNSAFE.**
  Home Assistant's `SAFETY` device class is on = problem, the shipped 1.4.x code
  already stores `not IsSafe`, and `weather_abort.yaml` already triggers on
  `to: "on"`. Phase C renamed the entity to match. Every abort trigger in this
  phase is `to: "on"`, never `to: "off"`.
- **A bare numeric meridian threshold is not portable between rigs** (§11).
- **Open items are tracked as issues labelled `2.0-blocker` / `2.0-nice`**, not
  in the design document (§12).

## A count to reconcile

§6.4 says "the 37 services". `main` at 1.4.5 registers **19**. The 37 is a
`wip/v2.0` figure. Task D1 establishes the real number after the trim and
**amends §6.4 with it** — the sentence's point (that `PARALLEL_UPDATES` does not
constrain services) stands either way.

---

## Task D1: Trim and retarget the services

**Files:**
- Modify: `custom_components/nina_astrophotography/__init__.py`,
  `custom_components/nina_astrophotography/services.yaml`,
  `custom_components/nina_astrophotography/const.py`,
  `custom_components/nina_astrophotography/strings.json`
- Test: `tests/ha/test_services.py`

**Interfaces:**
- Consumes: `NinaClientV2`'s command methods (phase C), `runtime_data`.
- Produces:
  - `_client_for_target(hass, call) -> NinaClientV2` — resolves the config entry
    from the call's `device_id`, falling back to the sole entry when exactly one
    exists and raising `ServiceValidationError` when several do.
  - Every service schema gaining `device_id` as an optional target.
  - Three redesigned services: `camera_capture`, `sequence_load`, `mount_slew`.

**The three redesigns** (§3.1 carries them into 2.0):

| Service | 1.4.5 defect | 2.0 |
|---|---|---|
| `camera_capture` | sends `time`, the API reads `duration`; `binning` and `filter_index` bind nothing | takes `duration`, `gain`, `save`; drops `binning`/`filter_index` entirely rather than shipping parameters that do nothing |
| `sequence_load` | sends `path`, the API reads `sequenceName` | takes `sequence_name`, documented as the name N.I.N.A. lists, not a path |
| `mount_slew` | takes RA in decimal hours and converts | takes `ra_degrees` and `dec_degrees`, **J2000**, and refuses a value outside 0–360 / −90–90 |

- [ ] **Step 1: Write the failing tests**

```python
"""Services: device targeting, and the three redesigns."""
import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.nina_astrophotography.const import DOMAIN


async def test_a_service_targets_a_specific_rig(hass, two_rigs) -> None:
    """_get_client()'s "first entry wins" is what phase D removes."""
    first, second = two_rigs
    await hass.services.async_call(
        DOMAIN, "mount_park", {"device_id": second.hub_device_id}, blocking=True)
    assert second.client.calls == ["park_mount"]
    assert first.client.calls == []


async def test_a_service_with_no_target_and_two_rigs_is_refused(hass, two_rigs) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "mount_park", {}, blocking=True)


async def test_a_service_with_no_target_and_one_rig_works(hass, loaded_entry) -> None:
    await hass.services.async_call(DOMAIN, "mount_park", {}, blocking=True)


async def test_camera_capture_sends_duration_not_time(hass, loaded_entry, client):
    """1.4.5 sent `time`; the API reads `duration`, so exposure time was ignored."""
    await hass.services.async_call(
        DOMAIN, "camera_capture", {"duration": 30}, blocking=True)
    assert client.last_params["duration"] == 30


def test_camera_capture_no_longer_offers_parameters_that_bind_nothing() -> None:
    """binning and filter_index bound nothing on the wire. Shipping them is
    worse than dropping them: they look like they work.

    Asserted against services.yaml rather than by calling the service and
    catching vol.Invalid, which would be testing voluptuous.
    """
    import yaml
    from pathlib import Path

    services = yaml.safe_load(
        (Path("custom_components/nina_astrophotography/services.yaml")
         ).read_text(encoding="utf-8"))
    fields = services["camera_capture"]["fields"]
    assert set(fields) == {"device_id", "duration", "gain", "save"}


async def test_sequence_load_sends_sequence_name_not_path(hass, loaded_entry, client):
    await hass.services.async_call(
        DOMAIN, "sequence_load", {"sequence_name": "Autumn"}, blocking=True)
    assert client.last_params["sequenceName"] == "Autumn"


async def test_mount_slew_takes_j2000_degrees_and_never_pre_transforms(
    hass, loaded_entry, client
) -> None:
    """All three branches construct Epoch.J2000 and N.I.N.A. transforms to the
    mount's own EquatorialSystem internally."""
    await hass.services.async_call(
        DOMAIN, "mount_slew", {"ra_degrees": 331.07, "dec_degrees": 56.6}, blocking=True)
    assert client.last_params == {"ra": 331.07, "dec": 56.6}


@pytest.mark.parametrize(
    ("ra", "dec"), [(-1, 0), (361, 0), (0, -91), (0, 91)]
)
async def test_out_of_range_coordinates_are_refused_client_side(
    hass, loaded_entry, ra, dec
) -> None:
    """Out-of-range input is silently clamped and answers Success: true."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, "mount_slew", {"ra_degrees": ra, "dec_degrees": dec}, blocking=True)


async def test_a_refused_command_raises_a_home_assistant_error(hass, loaded_entry, client):
    client.refuse("park_mount", "Mount not connected", 409)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, "mount_park", {}, blocking=True)


async def test_the_dither_service_is_still_absent(hass, loaded_entry) -> None:
    """The API exposes no dither command; dithering is driven from inside a
    sequence and only reported back, over GUIDER-DITHER."""
    assert not hass.services.has_service(DOMAIN, "guider_dither")
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/ha/test_services.py -v
```

Expected: FAIL — `_get_client` still returns the first entry.

- [ ] **Step 3: Move registration to `async_setup` (Bronze `action-setup`)**

Services are registered inside `async_setup_entry` today, which is the pattern
the rule forbids — the actions disappear when the last entry unloads, so an
automation referencing one fails validation rather than failing at call time.
Register them once in `async_setup` and resolve the entry at call time, which
`_client_for_target` already does.

§10's register omits `action-setup` entirely while §12 requires every Bronze
rule in §10 to pass and D5 ships `quality_scale.yaml` declaring it `done`.
**Reconcile §10's table against the file D5 ships in this PR** — the same gap
exists for `brands`, `dependency-transparency`, `docs-*` and
`unique-config-entry`.

- [ ] **Step 4: Implement the targeting**

```python
def _client_for_target(hass: HomeAssistant, call: ServiceCall) -> NinaClientV2:
    """Resolve which rig a service call means.

    1.4.5 returned the first configured entry, so a second rig was unreachable
    from services no matter how it was targeted.
    """
    device_id = call.data.get("device_id")
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        for entry_id in device.config_entries if device else ():
            entry = hass.config_entries.async_get_entry(entry_id)
            if entry is not None and entry.domain == DOMAIN:
                return entry.runtime_data.client
        raise ServiceValidationError(f"{device_id} is not a N.I.N.A. device")
    if len(entries) == 1:
        return entries[0].runtime_data.client
    raise ServiceValidationError(
        "Several N.I.N.A. instances are configured — target one with device_id"
    )
```

Add `device_id` to every schema and to `services.yaml`'s selectors:

```yaml
mount_park:
  target:
    device:
      integration: nina_astrophotography
```

- [ ] **Step 5: Count the services and amend §6.4**

```bash
grep -c "async_register" custom_components/nina_astrophotography/__init__.py
```

Put the real number into §6.4 in this PR, and bump the design's rev.

- [ ] **Step 6: Commit**

```bash
git add custom_components/nina_astrophotography tests/ha/test_services.py \
        docs/v2.0-design.md
git commit -m "feat: target services at a specific rig and redesign the three broken ones"
```

---

## Task D2: Blueprints

**Files:**
- Rewrite: `blueprints/automation/nina_astrophotography/meridian_flip_warning.yaml`,
  `weather_abort.yaml`, `guiding_alert.yaml`, `session_startup.yaml`,
  `session_shutdown.yaml`
- Test: `tests/unit/test_blueprints.py` (extend)

**Interfaces:**
- Consumes: the 2.0 entity ids in `docs/2.0-renames.md`, the HA bus events fired
  by `api/v2/events.py`.
- Produces: five blueprints whose triggers survive a disconnected device.

**The three substantive changes:**

1. **`meridian_flip_warning.yaml` triggers on the `MOUNT-BEFORE-FLIP` bus
   event**, not on a numeric threshold. `MOUNT-BEFORE-FLIP` fired on the
   observed night, so the trigger is proven, not assumed. Keep a numeric input
   as a secondary warning, but compute the threshold as
   `warning_minutes + (Max − Min)` from the profile — the flip fires when
   `TimeToMeridianFlip` reaches `(Max − Min)`, 10 minutes on this rig, so
   1.4.5's `below: 10` warned *at* the flip.
2. **The safety and weather blueprints use two triggers, not a merged state
   set.** §5.2.1's `to: ['off', 'unavailable', 'unknown']` is wrong in two ways:
   `off` is the *safe* state (see the Global Constraints above), and triggering
   on `unavailable` fires on every Home Assistant restart and every N.I.N.A.
   reachability blip — which is precisely the conflation §5.2.1 identifies and
   then commits. The correct shape separates the two questions:

```yaml
triggers:
  # Conditions became unsafe. SAFETY device class: on = problem.
  - trigger: state
    entity_id: !input safety_entity
    to: "on"
    id: unsafe
  # The monitor itself went away. This is what binary_sensor.*_connected is
  # retained for — it distinguishes "the monitor says nothing" from
  # "Home Assistant is restarting".
  - trigger: state
    entity_id: !input safety_connected_entity
    to: "off"
    for: "00:00:30"
    id: monitor_lost
```

   **Amend §5.2.1's trigger set in this PR.**
3. **`weather_abort.yaml` no longer aborts on a weather channel.** Its
   description states that weather channels are telemetry: a forecast-backed
   `ObservingConditions` source reads 0% cloud while you sit under a cloud.
   Abort belongs to `safety_is_safe`; the weather channels become an optional
   *additional* condition.

- [ ] **Step 1: Extend the blueprint test**

`tests/unit/test_blueprints.py` already validates the YAML. Add:

```python
"""Blueprints reference entities that exist, and fail safe."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

BLUEPRINTS = Path(__file__).resolve().parents[2] / "blueprints" / "automation" / \
    "nina_astrophotography"
SNAPSHOT = Path(__file__).resolve().parents[1] / "ha" / "snapshots"


def _entity_ids() -> set[str]:
    """Every entity id the 2.0 registry snapshot records.

    Read from a plain committed artifact rather than scraped out of syrupy's
    .ambr format, which is a snapshot serialization and not a stable interface.
    Task C12 writes it.
    """
    return set(
        (SNAPSHOT / "entity_ids.txt").read_text(encoding="utf-8").split()
    )


ENTITY = re.compile(r"\b(?:sensor|binary_sensor|switch|light|number|select|button|"
                    r"image|event)\.[a-z0-9_]+\b")


@pytest.mark.parametrize("path", sorted(BLUEPRINTS.glob("*.yaml")), ids=lambda p: p.name)
def test_every_entity_named_anywhere_still_exists(path: Path) -> None:
    """The whole document, not just input defaults.

    The shipped blueprints hardcode entity ids in their triggers and conditions —
    binary_sensor.observatory_safe, binary_sensor.mount_tracking,
    binary_sensor.camera_connected, binary_sensor.dome_shutter_open — every one
    of which phase B or C renames or deletes. A test that reads only `input`
    defaults passes while all five blueprints are broken.
    """
    named = set(ENTITY.findall(path.read_text(encoding="utf-8")))
    known = {e.split(".", 1)[1] for e in _entity_ids()}
    unknown = {e for e in named if e.split(".", 1)[1] not in known}
    assert not unknown, f"{path.name} names removed entities: {sorted(unknown)}"


def test_the_abort_fires_on_unsafe_not_on_safe() -> None:
    """The polarity test. SAFETY device class is on = problem, so an abort
    triggering on `to: "off"` fires when the sky CLEARS.

    This is the single most consequential assertion in the blueprint suite: the
    failure it prevents is silent, and its cost is an open roof under cloud.
    """
    document = yaml.safe_load(
        (BLUEPRINTS / "weather_abort.yaml").read_text(encoding="utf-8"))
    unsafe = [t for t in document["triggers"] if t.get("id") == "unsafe"]
    assert unsafe and unsafe[0]["to"] == "on"


def test_the_abort_also_fires_when_the_monitor_itself_disappears() -> None:
    """A separate trigger, not a merged state set — `unavailable` on the safety
    entity fires on every HA restart."""
    document = yaml.safe_load(
        (BLUEPRINTS / "weather_abort.yaml").read_text(encoding="utf-8"))
    assert any(t.get("id") == "monitor_lost" for t in document["triggers"])


def test_the_meridian_blueprint_triggers_on_the_event_not_a_bare_number() -> None:
    """The flip fires at (Max − Min), not zero, and both bounds are per-profile."""
    document = yaml.safe_load(
        (BLUEPRINTS / "meridian_flip_warning.yaml").read_text(encoding="utf-8"))
    assert "MOUNT-BEFORE-FLIP" in json.dumps(document["triggers"])
```

- [ ] **Step 2: Run, rewrite, run**

```bash
uv run pytest tests/unit/test_blueprints.py -v
```

- [ ] **Step 3: Commit**

```bash
git add blueprints tests/unit/test_blueprints.py
git commit -m "feat: retrigger the blueprints on proven events and fail-safe states"
```

---

## Task D3: Lovelace cards

**Files:**
- Modify: `www/nina-frame-stats-card.js`, `www/nina-image-panel-card.js`,
  `www/nina-observatory-card.js`, `www/nina-sky-map-card.js`,
  `www/nina-weather-card.js`
- Test: `tests/unit/test_card_image_urls.py` (extend)

**Interfaces:**
- Consumes: the 2.0 entity ids.
- Produces: five cards that name no removed entity and handle a missing weather
  channel.

- [ ] **Step 1: Extend the card test**

```python
"""Cards name entities that exist, and tolerate an absent weather channel."""
import re
from pathlib import Path

import pytest

WWW = Path(__file__).resolve().parents[2] / "www"
ENTITY = re.compile(r"['\"]((?:sensor|binary_sensor|switch|light|number|select|"
                    r"button|image|event)\.[a-z0-9_]+)['\"]")


@pytest.mark.parametrize("path", sorted(WWW.glob("*.js")), ids=lambda p: p.name)
def test_cards_name_no_removed_entity(path: Path) -> None:
    from test_blueprints import _entity_ids          # the same snapshot source

    named = set(ENTITY.findall(path.read_text(encoding="utf-8")))
    # Cards template over an instance prefix, so compare on the suffix.
    suffixes = {e.split(".", 1)[1].split("_", 3)[-1] for e in _entity_ids()}
    unknown = {e for e in named if e.split(".", 1)[1] not in suffixes}
    assert not unknown, f"{path.name} names removed entities: {sorted(unknown)}"


def test_the_weather_card_handles_a_channel_the_source_cannot_provide() -> None:
    """Two sources on this rig are disjoint in both directions."""
    source = (WWW / "nina-weather-card.js").read_text(encoding="utf-8")
    assert "unavailable" in source
```

- [ ] **Step 2: Update the cards, run, commit**

```bash
uv run pytest tests/unit/test_card_image_urls.py -v
git add www tests/unit/test_card_image_urls.py
git commit -m "feat: update the Lovelace cards for the 2.0 entity model"
```

---

## Task D4 (PR D1): Documentation

**Files:**
- Rewrite: `README.md`, `info.md`
- Modify: `CHANGELOG.md`, `docs/2.0-renames.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: the entity registry snapshot (Task C12), `docs/2.0-renames.md`.
- Produces: documentation that is accurate about the shipped code.

**The README must state, plainly, each of these** — every one is a place a user
will otherwise be surprised:

- [ ] **Step 1: Write the README sections**

| Section | Must say |
|---|---|
| Device model | One hub, one child device per equipment type. Driver metadata is in the device registry, not entity attributes. Two rigs coexist. |
| Availability | A disconnected device makes its entities `unavailable`, not `off`. **The safety monitor keeps its connected sensor** so a roof-close automation still fires; automations should trigger on `to: ['off', 'unavailable', 'unknown']`. |
| Session semantics | A session is everything since the most recent local noon — which is what N.I.N.A.'s own image-history dockable and Target Scheduler mean. It spans targets, filters and exposure lengths, and integration time sums actual exposures. |
| Weather | Channels appear on their first real reading, so **configuring in daylight yields no weather entities until dusk**. A channel the active source cannot provide reads `unavailable`, not `unknown`. Weather is telemetry, **not an abort authority** — a forecast-backed source reads 0% cloud while you sit under a cloud. |
| Dome | **Spec-derived and untested against hardware.** A dome owner's findings are welcome — link the issue tracker. |
| Livestack | The switch works whether or not the plugin is installed; without it the switch reads stopped and does nothing. |
| Flats | `/flats/status` observes only flats started through the API, so a Target Scheduler flat run reads `Finished` with `-1` iterations. The entities ship disabled. |
| Errors | `event.nina_error` is best-effort and solver-specific: `ERROR-PLATESOLVE` matches ASTAP only. |
| Upgrading | Link `docs/2.0-renames.md`. There is **no migration** — entity ids change and automations must be updated. |

- [ ] **Step 2: Format `docs/2.0-renames.md`**

Phase D **formats** that file; it does not reconstruct it (§8.6). Sort by 1.4.5
entity id, group by platform, and verify every row against the registry
snapshot.

- [ ] **Step 3: Finish the CHANGELOG**

Under `## [2.0.0]`, list Breaking / Added / Changed / Fixed / Removed. Name the
measured wins: polling ~297 MB → ~37 MB a night; `Last Image HFR` no longer
reads `0` after a flat run; the flat panel no longer jumps to full output.

- [ ] **Step 4: Update `CLAUDE.md`**

Its "Layout (current)" section still describes 1.4.5. Replace it with the phase-C
tree, update the branch map (`wip/v2.0` is deleted in D2), and point the test
guidance at the two suites that now exist rather than the target layout.

- [ ] **Step 5: Commit**

```bash
git add README.md info.md CHANGELOG.md docs/2.0-renames.md CLAUDE.md
git commit -m "docs: rewrite the documentation around the 2.0 model"
```

---

## Task D5 (PR D2): Release

**Files:**
- Create: `custom_components/nina_astrophotography/quality_scale.yaml`
- Modify: `custom_components/nina_astrophotography/manifest.json`, `hacs.json`,
  `pyproject.toml`

**Interfaces:**
- Produces: a tagged `2.0.0`.

- [ ] **Step 1: Write `quality_scale.yaml`**

Record exemptions rather than leaving them looking unimplemented.

```yaml
rules:
  # Bronze
  action-setup: done
  appropriate-polling: done
  brands: done
  common-modules: done
  config-flow: done
  config-flow-test-coverage: done
  dependency-transparency: done
  docs-actions: done
  docs-high-level-description: done
  docs-installation-instructions: done
  docs-removal-instructions: done
  entity-event-setup: done
  entity-unique-id: done
  has-entity-name: done
  runtime-data: done
  test-before-configure: done
  test-before-setup: done
  unique-config-entry: done

  # Silver
  action-exceptions: done
  config-entry-unloading: done
  entity-unavailable: done
  log-when-unavailable: done
  parallel-updates: done
  reauthentication-flow:
    status: exempt
    comment: >-
      The N.I.N.A. Advanced API has no authentication of any kind, so there are
      no credentials to re-enter.
  test-coverage:
    status: todo
    comment: >-
      Coverage is deliberately uneven — 100% on the config flow, high on the
      mapper and the pure modules, no global gate.

  # Gold
  devices: done
  dynamic-devices: done
  entity-category: done
  entity-disabled-by-default: done
  stale-devices: done
  diagnostics:
    status: todo
  discovery:
    status: exempt
    comment: The Advanced API advertises no discovery protocol.
  repair-issues:
    status: todo

  # Platinum
  strict-typing:
    status: todo
```

- [ ] **Step 2: Bump the versions**

```bash
# manifest.json
"version": "2.0.0",
"quality_scale": "bronze",
# hacs.json
"homeassistant": "2026.9.0",
# pyproject.toml
version = "2.0.0"
```

- [ ] **Step 3: Run the full gate**

```bash
uv run pytest tests/unit -p no:homeassistant -q
uv run pytest tests/ha -q
uv run coverage combine && uv run coverage json && uv run python scripts/coverage_floors.py
uv run python scripts/check_fixtures.py tests/fixtures/*.json
```

Expected: all green. Confirm the hassfest and HACS jobs are green in CI.

- [ ] **Step 4: Soak on the rig for three consecutive imaging nights**

§12 requires it, and it is the only gate no test replaces. Watch specifically:

- `Last Image HFR` / `Mean ADU` after a dawn flat run — the bug §5.2.4 measured.
- The session sensors across local noon.
- A N.I.N.A. restart mid-day: entities must not double-count or vanish.
- The flat panel: it must not jump to full output on `turn_on`.
- Payload volume against §6.1's ~37 MB/night estimate.

Record each night in the release PR. A regression against 1.4.5 blocks the tag.

- [ ] **Step 5: Commit the version bump**

```bash
git add custom_components/nina_astrophotography/quality_scale.yaml \
        custom_components/nina_astrophotography/manifest.json hacs.json pyproject.toml
git commit -m "chore: release 2.0.0"
```

- [ ] **Step 6: Merge, tag, and clean up**

The tag must point at the commit that carries the version bump, so this step
comes after it.

```bash
git checkout main && git merge --no-ff v2
git tag -a v2.0.0 -m "2.0.0"
git push origin main --tags
git branch -D wip/v2.0 && git push origin --delete wip/v2.0
```

---

## Definition of done (§12)

- [ ] Every Bronze rule in §10 passes. `quality_scale.yaml` records
      `reauthentication-flow` exempt with the §3.5 reason.
- [ ] Both suites green in CI; hassfest and HACS validation green.
- [ ] Drift guard green with `spec_deviations.json` reviewed; the wire-shape
      snapshot current.
- [ ] The entity registry snapshot has been reviewed as the rename mapping and
      `docs/2.0-renames.md` matches it.
- [ ] README, `info.md` and CHANGELOG rewritten.
- [ ] Installed on the maintainer's rig for **three consecutive imaging nights**
      with no regression against 1.4.5.
- [ ] `wip/v2.0` deleted.
- [ ] Remaining open items filed as issues labelled `2.0-blocker` / `2.0-nice`.

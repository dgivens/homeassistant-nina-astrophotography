# Phase C · Platforms Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every remaining platform onto `models.py`, make the §5.2 cuts,
and delete `api.py`.

**Architecture:** Each platform becomes a table of entity descriptors over
`NinaData`, with the value extraction a lambda on the model — no dict access
anywhere. Platforms are migrated one PR at a time, each re-adding itself to
`PLATFORMS` and rewriting its own tests in the same PR. `binary_sensor.py` leads
because it loses the most and a mistake there is cheap; `sensor.py` is split
into three PRs because it absorbs the frame-statistics family.

**Order matters, and it is not the order the tasks are numbered in.** Run C0 →
C1 → **C7** → C2 → C3 → C4 → C5 → C6 → C8 → C9 → C10 → C11 → C12. C7 carries the
only genuinely uncertain work in the phase — the pushed/polled family collapse
and entity-registry-backed weather channels across an `async_reload`. Every
other platform migration is mechanical. §1.2's abort criterion is attached to
this phase, so the decision to abort has to be reachable two PRs in, not nine:
if weather-channel recovery cannot be made to work, that is what you want to
learn before migrating six platforms.

**Tech Stack:** As phases A–B, plus syrupy entity-registry snapshots.

**Spec:** [`docs/v2.0-design.md`](../../v2.0-design.md) (Rev 4). §5.2, §5.3, §5.4
and §8.6 are the sections this phase implements.

**Prerequisite:** Phases A and B complete.

**Size: XL.** This is the phase §1.2's abort criterion is about. If it stalls,
`v2` is parked and 1.4.x continues to ship.

## Global Constraints

Phase A's and B's constraints still bind. In addition:

- **The survivor's state is the actual value, not the last commanded one**
  (§5.2.3).
- **Every dome descriptor carries `verified: False`**, enforced by a test
  (§5.3.1). Dome logic stays conservative — no derived state, no sentinel
  interpretation beyond the blanket rule.
- **Ranges are per-device.** Flat panel brightness is `MinBrightness`–
  `MaxBrightness`; mount tracking modes come from `TrackingModes`. Never
  hardcode either.
- **Out-of-range input is silently clamped and answers `Success: true`.**
  Validate client-side and raise `ServiceValidationError` (Silver
  `action-exceptions`).
- **`PARALLEL_UPDATES = 0`** on `sensor`, `binary_sensor`, `image` and `event`;
  **`= 1`** on `number`, `select`, `switch`, `button` and `light`.
- **The long tail ships `DIAGNOSTIC` and disabled by default** (Gold
  `entity-category`, `entity-disabled-by-default`).
- **Each PR appends its renames to `docs/2.0-renames.md`.**
- **Snapshot regeneration is its own commit** (§8.6) — with ~172 entities the
  diff *is* the review. Its job is review, not regression: a changed `unique_id`
  is not a bug, it just has to be seen.

## The descriptor pattern

Every platform in this phase uses the same shape. It is defined here once, in
full; each task below supplies its own descriptor table.

```python
"""Shared across the platform modules in phase C."""
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import SensorEntityDescription

from .coordinator import NinaData


@dataclass(frozen=True, kw_only=True)
class NinaSensorDescription(SensorEntityDescription):
    """A sensor, plus how to read it out of the snapshot.

    `kind` names the child device the entity hangs off (§5.1). `verified` is
    False only for the dome, which cannot be validated against hardware — a test
    asserts every dome descriptor carries the marker.
    """

    value: Callable[[NinaData], float | str | None]
    kind: str
    verified: bool = True
```

`binary_sensor`, `number`, `select` and `switch` each define the equivalent
against their own `*EntityDescription` base. An entity is created only when its
`kind`'s model is not `None` in the snapshot — first-sight creation (§5.2.2),
with persistence from the device registry.

---

## Task C0: The command methods

**Files:**
- Modify: `custom_components/nina_astrophotography/api/v2/client.py`
- Test: `tests/unit/test_v2_client.py` (extend)

**Interfaces:**
- Produces on `NinaClientV2`: `cool_camera`, `warm_camera`, `capture_image`,
  `abort_capture`, `slew_mount`, `park_mount`, `unpark_mount`, `find_home`,
  `set_tracking_mode`, `move_focuser`, `auto_focus`, `change_filter`,
  `start_guiding`, `stop_guiding`, `clear_guider_calibration`, `move_rotator`,
  `set_rotator_reverse`, `open_dome`, `close_dome`, `park_dome`, `home_dome`,
  `set_dome_follow`, `set_cooler`, `set_dew_heater`, `set_usb_limit`,
  `set_target_temperature`, `open_flat_cover`, `close_flat_cover`,
  `start_sequence`, `stop_sequence`, `load_sequence`, `start_livestack`,
  `stop_livestack`, `set_switch_value`.

**This must land before C1.** Tasks C2–C5 build platforms that call these:
`number`/`select` need `move_focuser`, `set_tracking_mode`, `change_filter`,
`move_rotator`; `switch` needs `start_livestack`/`stop_livestack` and the cooler
and dew-heater setters; `button` needs `auto_focus`, `park_mount` and
`clear_guider_calibration`. Phase A shipped only `set_flat_light` and
`set_flat_brightness`.

- [ ] **Step 1: Carry 1.4.5's parameter corrections across verbatim**

These were bought with a live rig and a near-miss; do not retype them from the
spec, which is wrong about request parameter names (§3.2).

```python
    async def slew_mount(self, ra_degrees: float, dec_degrees: float) -> None:
        """Slew to J2000 coordinates, in DEGREES.

        All three branches construct
        `new Coordinates(Angle.ByDegree(ra), Angle.ByDegree(dec), Epoch.J2000)`
        and N.I.N.A. transforms to the mount's own EquatorialSystem internally.
        Never pre-transform.

        The round trip is asymmetric: MountInfo.Coordinates / RightAscension are
        reported in the MOUNT's epoch (JNOW here) and in HOURS. Feeding a
        reported RA back into slew is wrong twice — a 15x unit error and a
        precession error — and 22.07 is a valid RA read either way, so nothing
        catches it.
        """
        await self._get("/equipment/mount/slew", {"ra": ra_degrees, "dec": dec_degrees})

    async def change_filter(self, index: int) -> None:
        """The parameter is `filterId`, not `filter` or `index`."""
        await self._get("/equipment/filterwheel/change-filter", {"filterId": index})

    async def capture_image(self, duration: float, *, gain: int | None = None,
                            save: bool = False) -> None:
        """The parameter is `duration`. 1.4.5 sent `time`, so exposure time was
        silently ignored — the API defaulted it and answered Success: true.

        `binning` and `filter_index` are deliberately absent: they bind nothing,
        and a parameter that looks like it works is worse than no parameter.
        """
        params: dict[str, Any] = {"duration": duration, "save": str(save).lower()}
        if gain is not None:
            params["gain"] = gain
        await self._get("/equipment/camera/capture", params)

    async def load_sequence(self, sequence_name: str) -> None:
        """The parameter is `sequenceName`, and it is a NAME, not a path.
        1.4.5 sent `path`, so the sequence never loaded."""
        await self._get("/sequence/load", {"sequenceName": sequence_name})
```

- [ ] **Step 2: Pin every parameter name by test**

A wrong name is a silent no-op that answers `Success: true`, so a table over
every command is the only thing standing between the integration and a service
that appears to work. One row per method:

```python
@pytest.mark.parametrize(
    ("call", "path", "params"),
    [
        (lambda c: c.slew_mount(331.07, 56.6), "/equipment/mount/slew",
         {"ra": 331.07, "dec": 56.6}),
        (lambda c: c.change_filter(3), "/equipment/filterwheel/change-filter",
         {"filterId": 3}),
        (lambda c: c.capture_image(30), "/equipment/camera/capture",
         {"duration": 30, "save": "false"}),
        (lambda c: c.load_sequence("Autumn"), "/sequence/load",
         {"sequenceName": "Autumn"}),
        (lambda c: c.move_focuser(12000), "/equipment/focuser/move",
         {"position": 12000}),
        (lambda c: c.set_tracking_mode(0), "/equipment/mount/tracking",
         {"mode": 0}),
        (lambda c: c.start_guiding(force_calibration=False),
         "/equipment/guider/start", {"calibrate": "false"}),
        (lambda c: c.move_rotator(90.0), "/equipment/rotator/move",
         {"position": 90.0}),
        # …one row per command method in the Interfaces block.
    ],
)
async def test_command_parameter_names_are_pinned(call, path, params) -> None:
    session = FakeSession()
    await call(NinaClientV2(host="h", port=1888, session=session))
    url, sent = session.requests[-1]
    assert path in url
    assert sent == params
```

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/test_v2_client.py -v
git add custom_components/nina_astrophotography/api/v2/client.py \
        tests/unit/test_v2_client.py
git commit -m "feat: add the command methods the platforms call"
```

---

## Task C1: `binary_sensor.py` — the lead platform

**Files:**
- Rewrite: `custom_components/nina_astrophotography/binary_sensor.py`
- Modify: `custom_components/nina_astrophotography/__init__.py` (`PLATFORMS`)
- Delete: `tests/unit/test_entity_api_usage.py` (superseded)
- Test: `tests/ha/test_binary_sensor.py`

**Interfaces:**
- Consumes: `NinaData.snapshot`, `NinaData.session` (phases A–B).
- Produces: `NinaBinarySensorDescription(BinarySensorEntityDescription)` with
  `value: Callable[[NinaData], bool | None]`, `kind: str`, `verified: bool = True`.

`binary_sensor.py` leads phase C: it loses 10 `*_connected` plus ~9 mirrors out
of 44 — the cleanest demonstration that the snapshot diff is the rename mapping,
on a platform where a mistake is cheap.

**Cut (19):**

| Removed | Replaced by |
|---|---|
| `camera_connected`, `mount_connected`, `focuser_connected`, `filterwheel_connected`, `guider_connected`, `rotator_connected`, `dome_connected`, `flatdevice_connected`, `weather_connected`, `switch_connected` | availability (§5.2.1) |
| `camera_cooling_enabled`, `camera_dew_heater_on` | the two `switch`es |
| `dome_following`, `rotator_reversed` | matching `switch`es |
| `guider_is_guiding` | `switch.guider` — safe only because `sensor.guider_status` is retained |
| `dome_shutter_open` | `sensor.dome_shutter_status` |
| `flatdevice_cover_open`, `flatdevice_light_on` | the cover switch / the `light` |
| `mount_tracking` | `select.mount_tracking_rate` |
| `livestack_running` | `switch.livestack` — its state *is* the status |

**The safety entity's polarity, stated once because it is a trap.**

Home Assistant's `SAFETY` device class means **`on` = problem**, and the shipped
1.4.x code already stores `not IsSafe` accordingly (`binary_sensor.py:209`), with
`weather_abort.yaml` correctly triggering on `to: "on"`. But §5.2.1's rationale
in the design is written as though `on` meant safe — *"a roof-close automation on
`to: "off"` does not fire"* — and that reading, carried into a blueprint, ships
an abort that fires when conditions become **safe** and stays silent when the
clouds arrive.

So: **the entity is `safety_unsafe`, `on` means unsafe**, and its translated name
is "Unsafe". Naming it `safety_is_safe` while it reads `on` for unsafe is a trap
every user hits exactly once, at the worst possible moment. **Amend §5.2.1 and
§7.3 in this PR** — their rationale, not their conclusion, is what is wrong.

**Kept and added:**

| Entity | Device class | Category | Notes |
|---|---|---|---|
| `safety_monitor_connected` | `connectivity` | `DIAGNOSTIC` | **The exception.** Kept so a roof-close automation still fires when the monitor itself drops out |
| `safety_unsafe` | `safety` | — | Abort authority. **`on` means UNSAFE** — see below. Never a weather channel (§6.4) |
| `mount_at_park`, `mount_at_home` | — | — | |
| `camera_is_exposing` | — | — | |
| `focuser_is_moving`, `filterwheel_is_moving`, `rotator_is_moving` | `moving` | `DIAGNOSTIC` | |
| `rotator_synced` | — | `DIAGNOSTIC` | **Retained.** Sky-PA `Position` is meaningful only when synced |
| `dome_at_park`, `dome_at_home`, `dome_slewing` | — | `DIAGNOSTIC` | `verified: False` |
| `autofocus_failed` | `problem` | — | **New** (§5.4). From the fold, not a timer |
| `sequence_running` | `running` | — | From the activity heuristic, never node status |

- [ ] **Step 1: Write the failing tests**

```python
"""binary_sensor: the cuts, and the two entities whose absence would be unsafe."""
import pytest


@pytest.mark.parametrize(
    "entity_id",
    [
        "binary_sensor.n_i_n_a_camera_connected",
        "binary_sensor.n_i_n_a_mount_tracking",
        "binary_sensor.n_i_n_a_guider_is_guiding",
        "binary_sensor.n_i_n_a_flat_panel_light_on",
        "binary_sensor.n_i_n_a_livestack_running",
    ],
)
def test_mirrors_and_connected_sensors_are_gone(hass, loaded_entry, entity_id) -> None:
    assert hass.states.get(entity_id) is None


async def test_safety_is_on_when_conditions_are_unsafe(hass, loaded_entry, advance):
    """HA's SAFETY device class is on = problem, and the shipped blueprint
    triggers on `to: "on"`. Getting this backwards ships an abort that fires
    when the sky clears and stays silent under cloud."""
    await advance("imaging")                      # IsSafe true
    assert hass.states.get("binary_sensor.n_i_n_a_unsafe").state == "off"


async def test_the_safety_monitor_keeps_its_connected_sensor(hass, loaded_entry) -> None:
    """The only asymmetric-risk entity in the set.

    Availability alone cannot carry this: `unavailable` conflates
    device-disconnected, N.I.N.A.-unreachable, HA-restarting and
    coordinator-failed, and an abort automation must distinguish them.
    """
    assert hass.states.get("binary_sensor.n_i_n_a_safety_monitor_connected") is not None


async def test_the_rotator_synced_sensor_is_retained(hass, loaded_entry) -> None:
    """Unsynced, sky-PA Position degenerates toward MechanicalPosition."""
    assert hass.states.get("binary_sensor.n_i_n_a_rotator_synced") is not None


async def test_an_unmatched_autofocus_start_raises_the_problem_sensor(
    hass, loaded_entry, advance
) -> None:
    """8 AUTOFOCUS-STARTING against 7 AUTOFOCUS-FINISHED, on an ordinary night."""
    await advance("autofocus_timed_out")
    assert hass.states.get("binary_sensor.n_i_n_a_autofocus_failed").state == "on"


async def test_sequence_running_is_off_on_an_idle_rig_with_running_nodes(
    hass, loaded_entry, advance
) -> None:
    """Verified on the idle rig: three nodes read RUNNING with zero frames
    captured. The meridian blueprint uses this as a condition."""
    await advance("idle_with_stale_running_nodes")
    assert hass.states.get("binary_sensor.n_i_n_a_sequence_running").state == "off"


async def test_every_dome_descriptor_is_marked_unverified(hass) -> None:
    """Dome ships untested; the marker is enforced, not documented (§5.3.1)."""
    from custom_components.nina_astrophotography.binary_sensor import DESCRIPTIONS
    assert all(d.verified is False for d in DESCRIPTIONS if d.kind == "dome")
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/ha/test_binary_sensor.py -v
```

Expected: FAIL — the platform still reads dicts.

- [ ] **Step 3: Rewrite the platform**

```python
"""Binary sensors.

Ten *_connected sensors are gone: a disconnected device makes its entities
unavailable, which is observable in automations. The safety monitor is the
exception — a disconnected safety monitor would make safety_unsafe unavailable,
so a roof-close automation on `to: "off"` never fires, and `to: "unavailable"`
cannot substitute because it conflates device-disconnected,
N.I.N.A.-unreachable, HA-restarting and coordinator-failed.

Read-only mirrors of a switch, number or select are gone too; the survivor's
state is the ACTUAL value, not the last commanded one. rotator_synced stays
because sky-PA Position is meaningful only when synced.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .coordinator import NinaData
from .entity import NinaEntity

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NinaBinarySensorDescription(BinarySensorEntityDescription):
    value: Callable[[NinaData], bool | None]
    kind: str
    verified: bool = True


DESCRIPTIONS: tuple[NinaBinarySensorDescription, ...] = (
    NinaBinarySensorDescription(
        key="safety_unsafe",
        translation_key="safety_unsafe",
        device_class=BinarySensorDeviceClass.SAFETY,
        kind="safety_monitor",
        # HA's SAFETY device class is on = problem. IsSafe true therefore maps
        # to off. Automations trigger on `to: "on"`.
        value=lambda data: None if data.snapshot.safety_monitor is None
        else _not_none(data.snapshot.safety_monitor.is_safe, invert=True),
    ),
    NinaBinarySensorDescription(
        key="safety_monitor_connected",
        translation_key="safety_monitor_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="safety_monitor",
        value=lambda data: None if data.snapshot.safety_monitor is None
        else data.snapshot.safety_monitor.connected,
    ),
    NinaBinarySensorDescription(
        key="autofocus_failed",
        translation_key="autofocus_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        kind="focuser",
        # Derived from the folded event set on read — there is no timer to leak.
        value=lambda data: data.session.autofocus.failed,
    ),
    # …one entry per row of the "Kept and added" table above.
)
```

- [ ] **Step 4: Re-add the platform and run**

```python
PLATFORMS = [Platform.LIGHT, Platform.BINARY_SENSOR]
```

```bash
uv run pytest tests/ha/test_binary_sensor.py -v
uv run pytest tests/unit -p no:homeassistant -q
```

- [ ] **Step 5: Append the renames and commit**

```bash
git add custom_components/nina_astrophotography/binary_sensor.py \
        custom_components/nina_astrophotography/__init__.py \
        custom_components/nina_astrophotography/strings.json \
        docs/2.0-renames.md tests/ha/test_binary_sensor.py
git rm tests/unit/test_entity_api_usage.py
git commit -m "feat: rebuild binary sensors on models, cutting mirrors and connected flags"
```

---

## Task C2: `number.py` and `select.py`

**Files:**
- Rewrite: `custom_components/nina_astrophotography/number.py`,
  `custom_components/nina_astrophotography/select.py`
- Test: `tests/ha/test_number.py`, `tests/ha/test_select.py`

**Interfaces:**
- Produces the `number` entities that inherit the mirrors §5.2.3 cut:
  `rotator_position`, `rotator_mechanical_position`, `dome_azimuth`,
  `camera_usb_limit`, `focuser_position`, `camera_target_temperature`,
  `flat_panel_brightness`; and `select.mount_tracking_rate`,
  `select.filter`.

- [ ] **Step 1: Write the failing tests**

```python
"""number and select: per-device ranges, and client-side validation."""
import pytest
from homeassistant.exceptions import ServiceValidationError


async def test_number_ranges_come_from_the_driver_not_a_constant(
    hass, loaded_entry
) -> None:
    """MinBrightness/MaxBrightness vary by hardware — 4096 here, 255 on an
    Alnitak. Never hardcode."""
    state = hass.states.get("number.n_i_n_a_flat_panel_brightness")
    assert state.attributes["max"] == 4096


async def test_out_of_range_input_is_refused_rather_than_silently_clamped(
    hass, loaded_entry
) -> None:
    """set-brightness?brightness=99999 answers Success: true and clamps."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "number", "set_value",
            {"entity_id": "number.n_i_n_a_flat_panel_brightness", "value": 99999},
            blocking=True,
        )


async def test_tracking_modes_come_from_the_mount(hass, loaded_entry) -> None:
    """TrackingModes differs by mount; a hardcoded list offers rates this mount
    does not have."""
    options = hass.states.get("select.n_i_n_a_mount_tracking_rate").attributes["options"]
    assert options == ["Sidereal", "Lunar", "Solar", "King", "Stopped"]


async def test_the_tracking_select_uses_the_wire_spelling(hass, loaded_entry) -> None:
    """The spec's enum says 'Siderial'; the wire says 'Sidereal'."""
    assert hass.states.get("select.n_i_n_a_mount_tracking_rate").state == "Sidereal"


async def test_a_filter_not_in_this_wheel_is_refused(hass, loaded_entry) -> None:
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "select", "select_option",
            {"entity_id": "select.n_i_n_a_filter", "option": "Ha"}, blocking=True,
        )


async def test_the_focuser_position_number_and_sensor_both_exist(
    hass, loaded_entry, entity_registry
) -> None:
    """sensor.focuser_position is reinstated, disabled by default, with
    state_class measurement: NumberEntity has no state_class, so dropping the
    sensor loses long-term statistics — and focuser position against temperature
    is the standard temp-comp-slope diagnostic."""
    assert hass.states.get("number.n_i_n_a_focuser_position") is not None
    entry = entity_registry.async_get("sensor.n_i_n_a_focuser_position")
    assert entry.disabled_by is not None
```

- [ ] **Step 2: Run, implement, run**

The `select` platform is **not enumerated** in §5.5's baseline — the arithmetic
there is a floor, not an exact count. Do not try to reconcile it; the
authoritative count is the registry snapshot (Task C10).

- [ ] **Step 3: Commit**

```bash
git add custom_components/nina_astrophotography/number.py \
        custom_components/nina_astrophotography/select.py \
        custom_components/nina_astrophotography/__init__.py \
        docs/2.0-renames.md tests/ha/test_number.py tests/ha/test_select.py
git commit -m "feat: rebuild number and select on models, with per-device ranges"
```

---

## Task C3: `switch.py`, including livestack

**Files:**
- Rewrite: `custom_components/nina_astrophotography/switch.py`
- Test: `tests/ha/test_switch.py`

**Interfaces:**
- Produces: `switch.guider`, `switch.camera_cooler`, `switch.camera_dew_heater`,
  `switch.dome_following`, `switch.rotator_reverse`,
  `switch.flat_panel_cover`, `switch.livestack`, and one switch per **binary**
  channel of the N.I.N.A. switch device (Task C8 adds the non-binary ones as
  numbers and sensors).

- [ ] **Step 1: Write the failing tests**

```python
"""switch: state is the actual value, read back from the poll."""


async def test_the_guider_switch_is_on_whenever_the_guider_is_running(
    hass, loaded_entry, advance
) -> None:
    """GuiderInfo.State is Looping | LostLock | Guiding | Stopped | Calibrating.

    `is_on = State == "Guiding"` reads OFF during LostLock and Calibrating, so
    any automation or dashboard tap calling switch.turn_on then sends
    /equipment/guider/start and forces a re-settle mid-exposure. Retaining
    sensor.guider_status makes that diagnosable but does not prevent it —
    "the guider is running" is the honest predicate for a switch.
    """
    await advance("guider_lost_lock")
    assert hass.states.get("switch.n_i_n_a_guider").state == "on"


async def test_the_guider_status_sensor_is_retained_alongside_it(hass, loaded_entry):
    """During LostLock the switch reads off, so "restart guiding when it stops"
    would fire mid-exposure. The status sensor is what makes the cut safe."""
    assert hass.states.get("sensor.n_i_n_a_guider_status") is not None


async def test_the_livestack_switch_reads_its_state_from_the_status_endpoint(
    hass, loaded_entry
) -> None:
    """/livestack/start and /stop "cannot fail", so neither confirms anything."""
    assert hass.states.get("switch.n_i_n_a_livestack").state in ("on", "off")


async def test_the_livestack_switch_exists_without_the_plugin(hass, loaded_entry):
    """The endpoint "cannot fail, even if the livestack plugin is not
    installed" — a rig without it sees a switch that reads stopped."""
    assert hass.states.get("switch.n_i_n_a_livestack") is not None


async def test_a_commands_own_response_never_sets_the_state(
    hass, loaded_entry, client
) -> None:
    """Measured: set-light?on=true returned success while an immediate re-read
    still showed LightOn: false; it changed seconds later."""
    client.livestack_running = False
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.n_i_n_a_livestack"}, blocking=True)
    assert hass.states.get("switch.n_i_n_a_livestack").state == "off"


async def test_only_binary_switch_channels_land_on_this_platform(
    hass, loaded_entry
) -> None:
    """Max − Min == StepSize is binary; a dew heater at 0–100 is not."""
    assert hass.states.get("switch.n_i_n_a_outlet_1") is not None
    assert hass.states.get("switch.n_i_n_a_dew_heater_a") is None


async def test_switch_channels_read_value_not_target_value(hass, loaded_entry) -> None:
    assert hass.states.get("switch.n_i_n_a_outlet_1").state == "on"
```

- [ ] **Step 2: Implement**

Livestack specifics (§5.3.2): state from `/livestack/status`, `turn_on` →
`/livestack/start`, `turn_off` → `/livestack/stop`; **compare the status string
case-insensitively** — the OpenAPI enum is `[running, stopped]` and a live rig
returned `"Stopped"`; refetch on `STACK-STATUS` with the floor tier as backstop.

- [ ] **Step 3: Commit**

```bash
git add custom_components/nina_astrophotography/switch.py \
        custom_components/nina_astrophotography/__init__.py \
        docs/2.0-renames.md tests/ha/test_switch.py
git commit -m "feat: rebuild switches on models and keep the livestack switch"
```

---

## Task C4: `button.py`

**Files:**
- Rewrite: `custom_components/nina_astrophotography/button.py`
- Test: `tests/ha/test_button.py`

**Interfaces:**
- Produces: `button.mount_park`, `button.mount_unpark`, `button.mount_find_home`,
  `button.camera_abort_exposure`, `button.focuser_auto_focus`,
  `button.sequence_start`, `button.sequence_stop`, `button.dome_open`,
  `button.dome_close`, `button.dome_park`, `button.dome_home`,
  `button.guider_clear_calibration`.

- [ ] **Step 1: Write the failing tests**

```python
"""button: fire-and-forget, with a real error surfaced as a real error."""
import pytest
from homeassistant.exceptions import HomeAssistantError


async def test_a_button_returns_when_the_api_accepts_the_command(
    hass, loaded_entry, client
) -> None:
    """Long-running commands are fire-and-forget: there is no request id under
    v2, so a completion event cannot be attributed to a caller."""
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.n_i_n_a_focuser_auto_focus"},
        blocking=True)
    assert "auto_focus" in client.calls


async def test_a_refused_command_raises(hass, loaded_entry, client) -> None:
    client.refuse("auto_focus", "Focuser not connected", 409)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button", "press", {"entity_id": "button.n_i_n_a_focuser_auto_focus"},
            blocking=True)


async def test_success_false_from_clear_calibration_is_not_an_error(
    hass, loaded_entry, client
) -> None:
    """guider/clear-calibration is one of seven handlers that assign Success
    from a driver boolean, answering Success: false, Error: "", StatusCode: 200."""
    client.respond_success_false("clear_calibration")
    await hass.services.async_call(
        "button", "press",
        {"entity_id": "button.n_i_n_a_guider_clear_calibration"}, blocking=True)
```

- [ ] **Step 2: Implement, run, commit**

```bash
git add custom_components/nina_astrophotography/button.py \
        custom_components/nina_astrophotography/__init__.py \
        docs/2.0-renames.md tests/ha/test_button.py
git commit -m "feat: rebuild buttons on the v2 client"
```

---

## Task C5: `image.py` and `image.livestack`

**Files:**
- Rewrite: `custom_components/nina_astrophotography/image.py`
- Test: `tests/ha/test_image.py`

**Interfaces:**
- Consumes: `NinaClientV2.get_image_bytes`, `.get_livestack_available()`.
- Produces: `image.last_frame` and `image.livestack` (§5.3.2 — the accumulating
  stack is a better dashboard image than the last raw sub).

- [ ] **Step 1: Write the failing tests**

```python
"""image: the last frame, and the accumulating stack."""


async def test_the_last_frame_image_updates_on_image_save(
    hass, loaded_entry, push
) -> None:
    before = hass.states.get("image.n_i_n_a_last_frame").state
    push(_image_save_event())
    await hass.async_block_till_done()
    assert hass.states.get("image.n_i_n_a_last_frame").state != before


async def test_a_livestack_image_exists_per_target_and_filter(hass, loaded_entry):
    """/livestack/image/available supplies the target/filter pairs."""
    assert hass.states.get("image.n_i_n_a_livestack") is not None


async def test_the_image_is_stretched(hass, loaded_entry, client) -> None:
    """autoPrepare, not useAutoStretch: an unknown parameter binds nothing and
    is not rejected, so the request succeeds and returns the linear frame."""
    await hass.services.async_call(
        "image", "snapshot",
        {"entity_id": "image.n_i_n_a_last_frame", "filename": "/tmp/x.jpg"},
        blocking=True)
    assert client.last_image_params["autoPrepare"] == "true"


async def test_a_refusal_arriving_as_a_200_envelope_is_not_served_as_an_image(
    hass, loaded_entry, client
) -> None:
    """With stream=true a real image is image/jpeg or image/png; a refusal
    arrives as 200 carrying the JSON envelope."""
    client.image_returns_envelope = True
    assert hass.states.get("image.n_i_n_a_last_frame").state == "unavailable"
```

- [ ] **Step 2: Implement, run, commit**

```bash
git add custom_components/nina_astrophotography/image.py \
        custom_components/nina_astrophotography/__init__.py \
        docs/2.0-renames.md tests/ha/test_image.py
git commit -m "feat: rebuild the image platform and add the livestack image"
```

---

## Task C6 (PR C1): `sensor.py` onto models

**Files:**
- Rewrite: `custom_components/nina_astrophotography/sensor.py`
- Test: `tests/ha/test_sensor.py`

**Interfaces:**
- Produces `NinaSensorDescription` (the shared pattern above) and every
  equipment sensor: camera temperature/cooler power/gain/offset, mount
  RA/Dec/Alt/Az/sidereal time/side of pier/time to meridian flip, focuser
  position (disabled by default, `state_class: measurement`) and temperature,
  filter wheel selected filter, guider status and RMS, rotator position, dome
  azimuth and shutter status, flat panel cover state, safety monitor.

- [ ] **Step 1: Write the failing tests**

```python
"""sensor: sentinels are unknown, never a number."""


async def test_a_nan_reading_is_unknown(hass, loaded_entry, advance) -> None:
    """Nineteen fields are "NaN" with weather, mount, focuser and dome down."""
    await advance("partial_equipment_connection")
    assert hass.states.get("sensor.n_i_n_a_camera_cooler_power").state == "unknown"


async def test_the_meridian_24_sentinel_is_unknown_but_twelve_hours_is_a_value(
    hass, loaded_entry, advance
) -> None:
    """24 is returned when TrackingEnabled is false; 12 h is legitimate — a
    mount inside the pier-side window that adds 12 h reads it — so a
    "≥12 → unknown" rule would be wrong."""
    await advance("sequence_complete_tracking_off")
    assert hass.states.get("sensor.n_i_n_a_mount_time_to_meridian_flip").state == "unknown"


async def test_the_focuser_position_sensor_carries_a_state_class(
    hass, loaded_entry, entity_registry
) -> None:
    """Long-term statistics: focuser position against temperature is the
    standard temp-comp-slope diagnostic, and this rig has TempCompAvailable false."""
    entity_registry.async_update_entity(
        "sensor.n_i_n_a_focuser_position", disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(
        "sensor.n_i_n_a_focuser_position").attributes["state_class"] == "measurement"


async def test_the_rotator_position_sensors_are_gone(hass, loaded_entry) -> None:
    """Read-only mirrors of the two numbers."""
    assert hass.states.get("sensor.n_i_n_a_rotator_position") is None
    assert hass.states.get("sensor.n_i_n_a_rotator_mechanical_position") is None
```

- [ ] **Step 2: Implement, run, commit**

```bash
git add custom_components/nina_astrophotography/sensor.py \
        custom_components/nina_astrophotography/__init__.py \
        docs/2.0-renames.md tests/ha/test_sensor.py
git commit -m "feat: rebuild equipment sensors on models"
```

---

## Task C7 (PR C2): The session family and weather channels

**Files:**
- Modify: `custom_components/nina_astrophotography/sensor.py`
- Delete: `custom_components/nina_astrophotography/frame_stats_sensor.py`,
  `tests/unit/test_frame_statistics.py`, `tests/unit/test_frame_store_listeners.py`,
  `tests/unit/test_image_stat_fields.py`
- Test: `tests/ha/test_session_sensors.py`, `tests/ha/test_weather_channels.py`

**Interfaces:**
- Produces: `sensor.session_image_count`, `sensor.session_integration_time`,
  `sensor.session_avg_hfr`, `sensor.session_best_hfr`, `sensor.session_worst_hfr`,
  `sensor.session_start`, `sensor.last_image_hfr`, `sensor.last_image_star_count`,
  `sensor.last_image_mean_adu`, `sensor.last_image_target`,
  `sensor.last_image_filter`, `sensor.weather_source`, and one sensor per
  observed weather channel.

- [ ] **Step 1: Write the failing tests**

```python
"""The session family: one family, fed by both paths."""


async def test_the_last_image_sensors_ignore_calibration_frames(
    hass, loaded_entry, advance
) -> None:
    """On 1.4.4 after a dawn flat run: Last Image HFR 0 (correct 1.454), Mean
    ADU 33,139.77 (correct 548.6) — exactly the last flat's Mean ADU."""
    await advance("dawn_flats")
    assert float(hass.states.get("sensor.n_i_n_a_last_image_hfr").state) > 0
    assert float(hass.states.get("sensor.n_i_n_a_last_image_mean_adu").state) < 2000


async def test_integration_time_sums_actual_exposures(hass, loaded_entry, advance):
    """6.20 h on the observed night; count x shortest exposure gives 2.75 h."""
    await advance("dawn_flats")
    assert float(hass.states.get(
        "sensor.n_i_n_a_session_integration_time").state) == pytest.approx(6.20, abs=0.02)


async def test_the_per_target_breakdown_is_an_attribute_not_an_entity(
    hass, loaded_entry, advance
) -> None:
    """Per-target HFR means ranged 1.429–1.667 against a session-wide 1.513."""
    await advance("dawn_flats")
    state = hass.states.get("sensor.n_i_n_a_session_avg_hfr")
    assert set(state.attributes["by_target"]) == {
        "Dark Shark Nebula", "Lobster & Bubble", "NGC 281", "Wizard Nebula"}


async def test_the_session_start_sensor_is_the_most_recent_local_noon(
    hass, loaded_entry, advance
) -> None:
    """Frames at 2026-09-03T21:39 and 2026-09-04T02:35 are one session."""
    await advance("dawn_flats")
    assert hass.states.get(
        "sensor.n_i_n_a_session_start").state.startswith("2026-09-03T12:00")
```

```python
"""Weather channels: first-sight creation at the channel granularity."""


async def test_a_channel_appears_on_its_first_non_nan_reading(
    hass, loaded_entry, advance
) -> None:
    assert hass.states.get("sensor.n_i_n_a_sky_brightness") is None
    await advance("weather_physical_station")
    assert hass.states.get("sensor.n_i_n_a_sky_brightness") is not None


async def test_a_channel_survives_a_home_assistant_restart(
    hass, loaded_entry, advance
) -> None:
    """async_setup_entry runs before any data arrives. Without recovery from the
    entity registry, every weather entity disappears on every HA restart and
    reappears minutes later, breaking automations and fragmenting history."""
    await advance("weather_physical_station")
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.n_i_n_a_sky_brightness") is not None


async def test_a_channel_the_active_source_cannot_provide_is_unavailable(
    hass, loaded_entry, advance
) -> None:
    """The two sources here are disjoint in both directions: the physical
    station provides SkyBrightness/SkyTemperature but not CloudCover; OpenMeteo
    the reverse. Accumulating the union would leave channels at `unknown`
    forever, which is a lie — the source CANNOT report them."""
    await advance("weather_physical_station")
    await advance("weather_openmeteo")
    assert hass.states.get("sensor.n_i_n_a_sky_brightness").state == "unavailable"
    assert hass.states.get("sensor.n_i_n_a_cloud_cover").state != "unavailable"


async def test_the_unique_id_does_not_change_with_the_source(
    hass, loaded_entry, advance, entity_registry
) -> None:
    """Keying unique_id on DeviceId would change entity ids on a source swap,
    breaking automations permanently to avoid a rare event."""
    await advance("weather_physical_station")
    before = entity_registry.async_get("sensor.n_i_n_a_sky_temperature").unique_id
    await advance("weather_openmeteo")
    assert entity_registry.async_get(
        "sensor.n_i_n_a_sky_temperature").unique_id == before


async def test_transiently_nan_fields_are_not_dynamic_channels(
    hass, loaded_entry, advance
) -> None:
    """The rule applies only where absence is a permanent driver property. A rig
    whose camera is warm at setup must not lose its cooler-power entity."""
    await advance("camera_warm_at_setup")
    assert hass.states.get("sensor.n_i_n_a_camera_cooler_power") is not None


async def test_the_active_weather_source_is_inspectable(hass, loaded_entry, advance):
    await advance("weather_openmeteo")
    assert hass.states.get("sensor.n_i_n_a_weather_source").state != "unknown"
```

- [ ] **Step 2: Implement the weather channel lifecycle**

This is the least mechanical code in the phase. Two granularities, one shared
helper (§5.2.2): devices persist through the **device** registry, weather
channels through the **entity** registry.

```python
# The thirteen ObservingConditions channels, by their wire names. A channel
# exists for this entry once it has produced one non-"NaN" reading, and is kept
# thereafter — but it reads `unavailable` whenever the ACTIVE source is not the
# one that established it.
WEATHER_CHANNELS: tuple[NinaSensorDescription, ...] = (
    NinaSensorDescription(
        key="cloud_cover", translation_key="cloud_cover",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, kind="weather",
        value=lambda data: data.snapshot.weather.channels.get("cloud_cover"),
    ),
    NinaSensorDescription(
        key="sky_brightness", translation_key="sky_brightness",
        # LUX, not mag/arcsec2. SkyBrightness and SkyQuality are two distinct
        # ASCOM ObservingConditions properties and the glossary conflates them:
        # the rig reports SkyBrightness 5692 (lux, at dawn) alongside
        # SkyQuality "NaN". Labelling this mag/arcsec2 makes it nonsense.
        device_class=SensorDeviceClass.ILLUMINANCE,
        native_unit_of_measurement=LIGHT_LUX,
        state_class=SensorStateClass.MEASUREMENT, kind="weather",
        value=lambda data: data.snapshot.weather.channels.get("sky_brightness"),
    ),
    NinaSensorDescription(
        key="sky_quality", translation_key="sky_quality",
        # No device class: HA has none for mag/arcsec2.
        native_unit_of_measurement="mag/arcsec²",
        state_class=SensorStateClass.MEASUREMENT, kind="weather",
        value=lambda data: data.snapshot.weather.channels.get("sky_quality"),
    ),
    # …one per channel: dew_point, humidity, pressure, rain_rate,
    # sky_temperature, star_fwhm, temperature, wind_direction, wind_gust,
    # wind_speed. Each is the same four lines with its own unit and device class.
)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    coordinator = entry.runtime_data.coordinator
    registry = er.async_get(hass)

    # async_setup_entry runs BEFORE any data arrives. Without recovering from
    # the registry, every weather entity disappears on every Home Assistant
    # restart and reappears minutes later — breaking automations and
    # fragmenting recorder history. The registry, not the poll, is the truth.
    known: set[str] = {
        entity.unique_id.removeprefix(f"{entry.entry_id}_")
        for entity in er.async_entries_for_config_entry(registry, entry.entry_id)
        if entity.domain == "sensor"
    }
    established = {d.key for d in WEATHER_CHANNELS if d.key in known}
    added = set(established)
    async_add_entities(NinaWeatherSensor(coordinator, entry, d)
                       for d in WEATHER_CHANNELS if d.key in established)

    def _add_newly_seen() -> None:
        """First-sight at the channel granularity: a channel appears the first
        time it reads non-NaN, and is never removed."""
        weather = coordinator.data.snapshot.weather
        if weather is None:
            return
        fresh = [d for d in WEATHER_CHANNELS
                 if d.key not in added and weather.channels.get(d.key) is not None]
        if fresh:
            added.update(d.key for d in fresh)
            async_add_entities(NinaWeatherSensor(coordinator, entry, d) for d in fresh)

    _add_newly_seen()
    entry.async_on_unload(coordinator.async_add_listener(_add_newly_seen))
```

and the entity, whose whole subtlety is one property:

```python
class NinaWeatherSensor(NinaEntity, SensorEntity):
    """One ObservingConditions channel.

    unique_id is deliberately source-INDEPENDENT. Keying it on DeviceId would
    change entity ids whenever the active source swapped, breaking automations
    permanently to avoid a rare event.
    """

    @property
    def available(self) -> bool:
        weather = self.coordinator.data.snapshot.weather
        if not super().available or weather is None or not weather.connected:
            return False
        # The two sources on this rig are disjoint in BOTH directions: the
        # physical station provides SkyBrightness/SkyTemperature but not
        # CloudCover; OpenMeteo the reverse. Accumulating the union would leave
        # channels at `unknown` forever, which is a lie — the active source
        # CANNOT report them. `unavailable` is the honest state.
        return weather.channels.get(self.entity_description.key) is not None \
            or self._established_by == weather.meta.device_id
```

**Do not generalise this to every `"NaN"` field.** The rule applies only where
absence is a permanent driver property. `CameraInfo.CoolerPower` and
`MountInfo.TimeToMeridianFlip` are transiently `NaN`, and a rig whose camera is
warm at setup must not lose its cooler-power entity.

Document the cold start in the README (D1): configuring in daylight yields no
weather entities until dusk.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/ha -q
git rm custom_components/nina_astrophotography/frame_stats_sensor.py \
       tests/unit/test_frame_statistics.py tests/unit/test_frame_store_listeners.py \
       tests/unit/test_image_stat_fields.py
git add -A custom_components/nina_astrophotography tests docs/2.0-renames.md
git commit -m "feat: collapse the frame-statistics family and create weather channels on sight"
```

---

## Task C8 (PR C3): The N.I.N.A. switch device channels

**Files:**
- Modify: `custom_components/nina_astrophotography/sensor.py`,
  `custom_components/nina_astrophotography/number.py`,
  `custom_components/nina_astrophotography/switch.py`
- Test: `tests/ha/test_switch_device.py`

**Interfaces:**
- Consumes: `SwitchDeviceModel.channels` and `SwitchChannelModel.binary` (phase A).
- Produces: one entity per channel — `switch` for binary, `number` for a
  writable range, `sensor` for a read-only gauge.

**Enabled by default** (§5.3.5). On this rig the switch device is an
HA→N.I.N.A. bridge exposing two Kasa outlets, so the entities duplicate ones that
exist natively — accepted, the same entity through two integrations is ordinary.
The normal case is a real ASCOM switch (a Pegasus Powerbox and its outlets, dew
heaters and voltage/current channels), which the default should serve.

- [ ] **Step 1: Write the failing tests**

```python
"""Switch-device channels split across three platforms by shape."""


async def test_a_binary_channel_becomes_a_switch(hass, loaded_entry) -> None:
    assert hass.states.get("switch.n_i_n_a_outlet_1") is not None


async def test_a_writable_range_becomes_a_number(hass, loaded_entry) -> None:
    assert hass.states.get("number.n_i_n_a_dew_heater_a") is not None


async def test_a_read_only_gauge_becomes_a_sensor(hass, loaded_entry) -> None:
    assert hass.states.get("sensor.n_i_n_a_input_voltage") is not None


async def test_channels_report_value_not_target_value(hass, loaded_entry, client):
    """TargetValue is where it is going; Value is where it is."""
    client.switch_channel_value("Dew A", value=40.0, target_value=80.0)
    assert float(hass.states.get("number.n_i_n_a_dew_heater_a").state) == 40.0


async def test_channels_are_enabled_by_default(hass, loaded_entry, entity_registry):
    assert entity_registry.async_get("switch.n_i_n_a_outlet_1").disabled_by is None
```

- [ ] **Step 2: Implement, run, commit**

```bash
git add -A custom_components/nina_astrophotography tests/ha/test_switch_device.py \
        docs/2.0-renames.md
git commit -m "feat: expose the N.I.N.A. switch device's channels by shape"
```

---

## Task C9: `event.nina_error` and the flats entities

**Files:**
- Create: `custom_components/nina_astrophotography/event.py`
- Modify: `custom_components/nina_astrophotography/sensor.py` (flats)
- Test: `tests/ha/test_event.py`, `tests/ha/test_flats.py`

**Interfaces:**
- Produces: `event.nina_error` with event types
  `platesolve_failed`, `camera_download_timeout`, `autofocus_timeout`;
  and `sensor.flats_state`, `sensor.flats_total_iterations`,
  `sensor.flats_completed_iterations` — all `DIAGNOSTIC` and **disabled by
  default**.

- [ ] **Step 1: Write the failing tests**

```python
"""event.nina_error: discrete occurrences with no state to hold."""


async def test_a_platesolve_error_fires_the_event_entity(hass, loaded_entry, push):
    push(_event("ERROR-PLATESOLVE"))
    await hass.async_block_till_done()
    assert hass.states.get("event.n_i_n_a_error").attributes[
        "event_type"] == "platesolve_failed"


async def test_an_autofocus_timeout_fires_it_too(hass, loaded_entry, advance):
    await advance("autofocus_timed_out")
    assert hass.states.get("event.n_i_n_a_error").attributes[
        "event_type"] == "autofocus_timeout"
```

```python
"""Flats: disabled by default, because /flats/status observes only API-started runs."""


async def test_flats_entities_are_disabled_by_default(hass, loaded_entry, entity_registry):
    """This rig runs Target Scheduler Flats, so /flats/status reads
    {State: "Finished", TotalIterations: -1, CompletedIterations: -1} straight
    through a completed dawn run — confirmed."""
    entry = entity_registry.async_get("sensor.n_i_n_a_flats_state")
    assert entry.disabled_by is not None
    assert entry.entity_category == "diagnostic"


async def test_the_idle_iteration_sentinel_is_unknown(hass, loaded_entry, entity_registry):
    entity_registry.async_update_entity(
        "sensor.n_i_n_a_flats_total_iterations", disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.n_i_n_a_flats_total_iterations").state == "unknown"
```

`event.nina_error` is best-effort and solver-specific: `ERROR-PLATESOLVE` matches
ASTAP only and `ERROR-AF` appears dead (§3.4). Document that in the README (D1).

- [ ] **Step 2: Implement, run, commit**

```bash
git add custom_components/nina_astrophotography/event.py \
        custom_components/nina_astrophotography/sensor.py \
        custom_components/nina_astrophotography/__init__.py \
        docs/2.0-renames.md tests/ha/test_event.py tests/ha/test_flats.py
git commit -m "feat: surface N.I.N.A. errors as an event entity and ship flats disabled"
```

---

## Task C10: The dome marker and its synthetic fixture

**Files:**
- Create: `tests/synthetic/dome_connected.json`,
  `tests/ha/test_dome_marker.py`, `tests/unit/test_dome_mapping.py`
- Test: both of the above

The descriptor half lives in **`tests/ha/`**: it imports the platform modules,
every one of which imports `homeassistant`, so it cannot run under
`pytest tests/unit -p no:homeassistant`. Only the mapper test — which touches
`api/v2/mapper.py` and nothing else — belongs in `tests/unit`.

**Interfaces:**
- Consumes: every platform's `DESCRIPTIONS` tuple.
- Produces: a test asserting **every** dome descriptor across every platform
  carries `verified: False`.

- [ ] **Step 1: Write the test**

```python
"""Dome ships untested — the marker is enforced, not merely documented.

There is no dome available and no prospect of one, so DomeInfo cannot be
validated, and it is the one subsystem where the spec is known wrong (five
missing fields, Azimuth typed integer while sending "NaN"). The drift guard
cannot see dome fields at all; this synthetic fixture exercises the mapper path
and asserts BRANCH REACHABILITY ONLY, never values.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

PLATFORMS = ("binary_sensor", "sensor", "number", "switch", "button")


@pytest.mark.parametrize("module_name", PLATFORMS)
def test_every_dome_descriptor_is_marked_unverified(module_name: str) -> None:
    """tests/ha only — these modules import Home Assistant."""
    module = importlib.import_module(
        f"custom_components.nina_astrophotography.{module_name}")
    dome = [d for d in getattr(module, "DESCRIPTIONS", ()) if d.kind == "dome"]
    assert dome, f"{module_name} declares no dome entities — remove it from PLATFORMS"
    assert all(d.verified is False for d in dome)


def test_a_synthetic_connected_dome_maps_without_raising() -> None:
    """Derived from a real DISCONNECTED capture. Asserts reachability, not values."""
    from nina_astrophotography.api.v2.mapper import map_equipment_info

    path = Path(__file__).resolve().parents[1] / "synthetic" / "dome_connected.json"
    wire = json.loads(path.read_text(encoding="utf-8"))["Response"]
    snapshot = map_equipment_info(wire)
    assert snapshot.dome is not None
    assert snapshot.dome.connected is True
```

- [ ] **Step 2: Build the synthetic fixture**

Take `restart_equipment_partial_connect.json`'s `DomeInfo` block — a real
*disconnected* capture — and flip `Connected` to `true`, replacing `"NaN"`
azimuth with a plausible number. Add a header comment in
`tests/synthetic/README.md`:

```markdown
# Synthetic fixtures

Constructed, not captured. **Authoritative about nothing but our own branches.**
Never add a synthetic file for a subsystem real hardware can produce — a
captured fixture encodes reality, a hand-written one encodes the spec's
mistakes.

| File | Why it cannot be captured |
|---|---|
| `dome_connected.json` | No dome is available and none is in prospect (§5.3.1) |
```

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/test_dome_marker.py -v
git add tests/synthetic tests/unit/test_dome_marker.py
git commit -m "test: enforce the unverified marker on every dome descriptor"
```

---

## Task C11: Delete `api.py`

**Files:**
- Delete: `custom_components/nina_astrophotography/api.py`
- Modify: `custom_components/nina_astrophotography/__init__.py` (services),
  `custom_components/nina_astrophotography/const.py` (53 dead `ENDPOINT_*`)
- Merge: `tests/unit/test_api_{connection,endpoint,envelope,image_fetch,image_history,tracking,paths,guiding,slew}.py`
  and `test_poll_all.py` into `tests/unit/test_v2_client.py`
- Test: `tests/unit/test_v2_client.py`

**Interfaces:**
- Produces: `NinaClientV2` gaining the command methods the services call —
  `cool_camera`, `warm_camera`, `capture_image`, `abort_capture`, `slew_mount`,
  `park_mount`, `unpark_mount`, `find_home`, `set_tracking_mode`, `move_focuser`,
  `auto_focus`, `change_filter`, `start_guiding`, `stop_guiding`, `move_rotator`,
  `open_dome`, `close_dome`, `park_dome`, `home_dome`, `start_sequence`,
  `stop_sequence`, `load_sequence`, `start_livestack`, `stop_livestack`.

This PR **ports the service call sites mechanically** — same behaviour, new
client. Phase D redesigns and trims them. Do the two separately: a port and a
redesign in one PR makes the diff unreviewable.

- [ ] **Step 1: Move the command methods onto `NinaClientV2`**

Carry across 1.4.5's hard-won parameter corrections verbatim, with their
docstrings:

```python
    async def slew_mount(self, ra_degrees: float, dec_degrees: float) -> None:
        """Slew to J2000 coordinates, in DEGREES.

        All three branches construct
        `new Coordinates(Angle.ByDegree(ra), Angle.ByDegree(dec), Epoch.J2000)`
        and N.I.N.A. transforms to the mount's own EquatorialSystem internally.
        Never pre-transform.

        The round trip is asymmetric: MountInfo.Coordinates / RightAscension are
        reported in the MOUNT's epoch (JNOW here) and in HOURS. Feeding a
        reported RA back into slew is wrong twice — a 15x unit error and a
        precession error.
        """
        await self._get("/equipment/mount/slew", {"ra": ra_degrees, "dec": dec_degrees})
```

- [ ] **Step 2: Merge the API tests**

Move every assertion from the nine `test_api_*.py` files plus `test_poll_all.py`
into `tests/unit/test_v2_client.py`, adapting the client name and dropping any
that tested `poll_all`'s failure-aggregation — the tiers replaced it. Keep
`test_no_dither_command.py`, `test_card_image_urls.py` and `test_blueprints.py`
as they are (§8.0).

- [ ] **Step 3: Delete**

```bash
git rm custom_components/nina_astrophotography/api.py
git rm tests/unit/test_api_connection.py tests/unit/test_api_endpoint.py \
       tests/unit/test_api_envelope.py tests/unit/test_api_image_fetch.py \
       tests/unit/test_api_image_history.py tests/unit/test_api_tracking.py \
       tests/unit/test_api_paths.py tests/unit/test_api_guiding.py \
       tests/unit/test_api_slew.py tests/unit/test_poll_all.py
```

Then strip the 53 dead `ENDPOINT_*` constants from `const.py` — the paths live
in `api/v2/client.py` now — and delete `CONF_API_VERSION` / `DEFAULT_API_VERSION`
with them.

- [ ] **Step 4: Prove nothing references it**

```bash
grep -rn "from .api import\|from \.api import NinaApiClient\|ENDPOINT_" \
     custom_components/ tests/ | grep -v "api/v2\|api\.errors\|api\.models"
```

Expected: no output.

- [ ] **Step 5: Run everything**

```bash
uv run pytest tests/unit -p no:homeassistant -q
uv run pytest tests/ha -q
uv run coverage combine && uv run coverage json && uv run python scripts/coverage_floors.py
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "refactor: delete api.py and move the services onto the v2 client"
```

---

## Task C12: The entity registry snapshots

**Files:**
- Create: `tests/ha/test_snapshots.py`, `tests/ha/snapshots/*.ambr` (one per platform)
- Test: as above

**Interfaces:**
- Produces: the authoritative entity count (§5.5) and the rename mapping (§8.6).

The **entity registry** is the rename artifact — `unique_id`, `entity_id`,
`original_name`, `entity_category`, `entity_registry_enabled_default`. Not
`hass.states`: the disabled long tail has no state, so a state snapshot omits
exactly the entities most likely to be misconfigured.

- [ ] **Step 1: Write the snapshot test**

```python
"""One .ambr per platform, sorted by unique_id.

Snapshot regeneration is its own commit: with ~172 entities the diff IS the
review. Its job here is review, not regression — a changed unique_id is not a
bug, it just has to be seen.
"""
import pytest
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from syrupy.assertion import SnapshotAssertion


@pytest.mark.parametrize(
    "platform",
    [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT,
     Platform.SWITCH, Platform.BUTTON, Platform.LIGHT, Platform.IMAGE, Platform.EVENT],
)
async def test_registry_snapshot(hass, loaded_entry, snapshot: SnapshotAssertion,
                                 platform: Platform) -> None:
    registry = er.async_get(hass)
    entries = sorted(
        (e for e in er.async_entries_for_config_entry(registry, loaded_entry.entry_id)
         if e.domain == platform),
        key=lambda e: e.unique_id,
    )
    assert [
        {
            "unique_id": e.unique_id,
            "entity_id": e.entity_id,
            "original_name": e.original_name,
            "entity_category": e.entity_category,
            "enabled_default": not e.disabled_by,
        }
        for e in entries
    ] == snapshot


async def test_a_small_state_snapshot_pins_the_value_contracts(
    hass, loaded_entry, snapshot: SnapshotAssertion
) -> None:
    """Separate and deliberately small — the registry snapshot covers naming."""
    watched = ["sensor.n_i_n_a_session_avg_hfr",
               "sensor.n_i_n_a_session_integration_time",
               "binary_sensor.n_i_n_a_unsafe"]
    assert {e: hass.states.get(e).state for e in watched} == snapshot
```

- [ ] **Step 2: Emit `entity_ids.txt` alongside the snapshots**

The blueprint and card tests in phase D need the entity list, and scraping it
out of syrupy's `.ambr` format couples them to a snapshot serialization. Write a
plain artifact instead:

```python
async def test_entity_id_inventory_is_current(hass, loaded_entry) -> None:
    """A committed, plain-text list of every 2.0 entity id.

    Phase D's blueprint and card tests read this. Regenerating it is part of
    the snapshot commit.
    """
    registry = er.async_get(hass)
    ids = sorted(e.entity_id for e in
                 er.async_entries_for_config_entry(registry, loaded_entry.entry_id))
    path = Path(__file__).parent / "snapshots" / "entity_ids.txt"
    if path.read_text(encoding="utf-8").split() != ids:
        path.write_text("\n".join(ids) + "\n", encoding="utf-8")
        pytest.fail("entity_ids.txt regenerated — review and commit it")
```

- [ ] **Step 3: Generate, and review the diff by eye**

```bash
uv run pytest tests/ha/test_snapshots.py --snapshot-update
git diff --stat tests/ha/snapshots
```

Read every line. Count the entities:

```bash
grep -c "unique_id" tests/ha/snapshots/*.ambr
```

Compare against §5.5's ≈172. **The snapshot is authoritative**, not the table —
but a large divergence means a platform was missed. If the count settles far
from 172, amend §5.5's arithmetic in this PR with the real number.

- [ ] **Step 4: Reconcile `docs/2.0-renames.md` against the snapshot**

Every renamed entity in the snapshot must appear in the file, and vice versa.

- [ ] **Step 5: Commit the snapshots on their own**

```bash
git add tests/ha/test_snapshots.py
git commit -m "test: snapshot the entity registry as the rename artifact"
git add tests/ha/snapshots
git commit -m "test: record the 2.0 entity registry snapshot"
```

---

## Known gaps in this plan

Every task below is specified by its tests and its descriptor table but has no
worked implementation body. They are listed so the gap is a decision rather than
a surprise. All are mechanical — the same descriptor pattern with a different
table — which is why they are acceptable here and C7 above is not.

| Task | What is prose-only | Why it is safe |
|---|---|---|
| C2 `number` / `select` | the two descriptor tables | ranges and options come from the model; the tests pin both |
| C4 `button` | 12 one-line press handlers | each is one `await client.<method>()` from C0 |
| C5 `image` | two entities | `get_image_bytes` is written and pinned in A10 |
| C6 `sensor` C1 | ~40 equipment descriptors | identical shape to C1's, which is worked in full |
| C8 switch-device channels | the three-way split by shape | `SwitchChannelModel.binary` (A9) is the whole rule |
| C9 `event` / flats | one event entity, three flats sensors | the mapper already normalizes the `-1` sentinels |

If any of these turns out to need a design decision rather than a table, stop
and amend the plan — that is the signal that it was mis-classified here.

## Phase C exit criteria

- [ ] Every platform is on `models.py`; no dict access above `api/`.
- [ ] `api.py`, `frame_statistics.py`, `frame_stats_sensor.py` and
      `websocket.py` are all deleted, and the 53 dead `ENDPOINT_*` are gone.
- [ ] Both suites green; six CI jobs green; every coverage floor met.
- [ ] The entity registry snapshot exists, has been read line by line, and
      matches `docs/2.0-renames.md`.
- [ ] Every dome descriptor carries `verified: False`, enforced by test.
- [ ] `grep -rn "hass.data\[DOMAIN\]" custom_components/` returns nothing.
- [ ] The entity count is recorded; §5.5 amended if it diverged materially.

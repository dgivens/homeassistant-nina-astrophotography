# Phase B · Devices + push-first Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the WebSocket from a hint into a data source, make N.I.N.A.
restarts a first-class concept, cut polling from ~297 MB to ~37 MB a night, and
give every piece of equipment its own Home Assistant device.

**Architecture:** The socket moves inside the seam as `api/v2/events.py` and
delivers `NinaEvent` models, never dicts. The coordinator gains six tiers behind
one 10-second tick with per-tier due-time checks, an `/application-start`
generation tag applied by **filtering** rather than clearing, and a push path
that calls `async_set_updated_data`. Above it, `device.py` builds a hub service
device with one `via_device` child per equipment type, and `entity.py` grows
availability levels 2 and 3.

**Tech Stack:** As phase A, plus `aiohttp`'s WebSocket client and Home
Assistant's device and entity registries.

**Spec:** [`docs/v2.0-design.md`](../../v2.0-design.md) (Rev 4). §3.4, §3.6, §5.1,
§5.2.2, §6 and §7.3 are the sections this phase implements.

**Prerequisite:** Phase A complete, its exit criteria met.

## Global Constraints

Every task's requirements implicitly include this section, in addition to phase
A's (which still bind — the seam, the blanket `"NaN"` rule, coverage floors,
`requirements: []`, no `-n auto`, every PR green).

- **Entity ids change in this phase.** Every PR that renames appends to
  `docs/2.0-renames.md`.
- **The push path calls `async_set_updated_data`, not `async_request_refresh`**
  (§6.3). That single line is what makes the design push-first.
- **The process boundary is derived by filtering on the generation tag, never by
  clearing the set** (§3.6). Clearing races a concurrent poll, produces a false
  positive on the first read when no baseline exists, and loses events arriving
  during the refetch.
- **`/image-history?all=true` is the only reseed source** (§6.1). Bare
  `/image-history` returns the newest frame only, so seeding from it leaves
  `Session Image Count` reading 1 for the rest of the night.
- **The `/event-history` high-water mark is per-generation** (§6.3). A restart
  produces fresh timestamps that can be *earlier* than a retained mark.
- **Do not refetch on `TS-TARGETSTART`** (§6.1). Debounce any sequence refetch to
  ≤1 per 30 s.
- **Nothing safety-related is on the floor tier** (§6.4).
- **`unique_id` stays source-independent** for weather channels (§5.2.2).
  Keying it on `DeviceId` would change entity ids on a source swap.
- **Anything driven by the push path needs `await hass.async_block_till_done()`
  after firing** (§8.8).
- **`PARALLEL_UPDATES = 0`** on read-only platforms, `1` on command platforms.

## File structure

| File | Responsibility |
|---|---|
| `…/api/v2/events.py` | WebSocket client + `/event-history` replay. Emits `NinaEvent`, never dicts. |
| `…/device.py` | Hub device, one `via_device` child per equipment type, registry metadata sync. |
| `…/coordinator.py` | Grows the six tiers, the generation, the accumulated sets and the push entry point. |
| `…/entity.py` | Grows device linking and availability levels 2 and 3. |
| `…/config_flow.py` | Instance name; the `vol.In(["v2"])` dropdown removed; 100% branch coverage. |
| `…/__init__.py` | Wires `events.py`, drops `websocket.py` and `frame_statistics.py`. |
| **Deleted** `…/websocket.py` | Superseded by `api/v2/events.py`. |
| `docs/2.0-renames.md` | Started here, appended by every renaming PR, formatted in D1. |
| `tests/scenarios/` | Ordered multi-step states; `FakeNinaClient` advances on demand. |

---

## Task B0: The scenario catalogue and the shared fixtures

**Files:**
- Create: `tests/scenarios/__init__.py`, `tests/scenarios/states.py`,
  `tests/scenarios/README.md`, `tests/ha/conftest.py` (extend)
- Test: `tests/unit/test_scenarios.py`

**Interfaces:**
- Produces the `advance(state)` fixture and the named states every later test in
  phases B and C depends on. **Write this first.** Around twenty-five tests
  across the two phases call `advance("…")`, and three of the states need wire
  data the corpus does not yet contain — which `CLAUDE.md` says must be
  *captured from the rig*, never hand-written. Discovering that in the middle of
  phase C stalls the phase.

Most of this design's behaviour is a **transition**, not a state (§8.4).

| State | Source | Status |
|---|---|---|
| `imaging` | `dawn_equipment_info` + `dawn_image_history_with_flats` | captured |
| `dawn_flats` | `dawn_image_history_with_flats` (67 flats) | captured |
| `sequence_complete_tracking_off` | `dawn_mount_tracking_off`, `dawn_sequence_complete` | captured |
| `partial_equipment_connection` | `restart_equipment_partial_connect` | captured |
| `nina_restarted` | `restart_*` (five files) | captured |
| `sequencer_not_initialized` | `startup_sequence_not_initialized` | captured |
| `weather_openmeteo` | `weather_source_openmeteo` | captured |
| `camera_disconnected` | derived from `partial_equipment_connection` | derived |
| `safety_monitor_disconnected` | derived, same way | derived |
| `equipment_disconnected` | derived, same way | derived |
| `nina_unreachable` | the client raises `NinaConnectionError` | synthetic |
| `autofocus_timed_out` | `dawn_event_history`, truncated after the 8th `AUTOFOCUS-STARTING` | captured |
| **`weather_physical_station`** | — | **must be captured** |
| **`camera_warm_at_setup`** | — | **must be captured** |
| **`idle_with_stale_running_nodes`** | — | **must be captured** |

The last three block the tests that need them. Capture them opportunistically
before starting phase C:

- `weather_physical_station` — the physical station active, so `SkyBrightness`
  and `SkyTemperature` are real and `CloudCover` is `"NaN"`. Required by
  §5.2.2's disjoint-source tests; the corpus only has the OpenMeteo side.
- `camera_warm_at_setup` — `CoolerPower "NaN"` with the camera connected, to
  prove a transiently-`NaN` field does **not** become a dynamic channel.
- `idle_with_stale_running_nodes` — `/sequence/json` with nodes reading
  `RUNNING` and no frames captured. §6.2's whole rationale rests on this and no
  fixture holds it.

Until they exist, mark the tests that need them `@pytest.mark.skip(reason="awaiting capture: <state>")` — **skipped and named**, never quietly
deleted or faked from a hand-written file.

- [ ] **Step 1: Write the state table as code**

```python
"""Ordered rig states, assembled from captured fixtures.

A state is a dict of endpoint -> Response, exactly as the wire sent it.
FakeNinaClient serves one state at a time and advance() moves between them.
"""
from __future__ import annotations

from helpers import load_fixture

# Endpoint keys match NinaClientV2's private _get paths.
STATES: dict[str, dict[str, object]] = {
    "imaging": {
        "/equipment/info": load_fixture("dawn_equipment_info.json"),
        "/image-history": load_fixture("dawn_image_history_with_flats.json"),
        "/application-start": "2026-09-03T18:22:11",
    },
    "nina_restarted": {
        "/equipment/info": load_fixture("restart_equipment_partial_connect.json"),
        "/image-history": load_fixture("restart_image_history_empty_list.json"),
        "/application-start": "2026-09-04T13:54:50.907",
    },
    # …one entry per row of the table above.
}

AWAITING_CAPTURE = frozenset(
    {"weather_physical_station", "camera_warm_at_setup",
     "idle_with_stale_running_nodes"}
)


def disconnect(state: dict, device: str) -> dict:
    """Derive a disconnected-device state from a connected one.

    A disconnected device does not null its fields — it DROPS them, along with
    DeviceId, Name and DisplayName. Deriving by setting Connected=False would
    produce a shape the wire never sends.
    """
    reference = load_fixture("restart_equipment_partial_connect.json")
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in state.items()}
    info = dict(out["/equipment/info"])
    info[device] = reference[device]
    out["/equipment/info"] = info
    return out
```

- [ ] **Step 2: Write the guard test**

```python
"""Every named state resolves, and the awaiting-capture list is honest."""
import pytest

from scenarios.states import AWAITING_CAPTURE, STATES


def test_every_state_named_by_a_test_exists() -> None:
    """A typo in advance("…") must fail here, not as a confusing KeyError."""
    assert AWAITING_CAPTURE.isdisjoint(STATES)


@pytest.mark.parametrize("name", sorted(STATES))
def test_each_state_carries_the_fast_tier_endpoints(name: str) -> None:
    assert {"/equipment/info", "/application-start"} <= set(STATES[name])
```

- [ ] **Step 3: Add `load_fixture` to `tests/helpers.py`**

Six places across phases A–C load a fixture with the same four lines, including
the `_meta` rule. Define it once, where `_meta` is introduced:

```python
def load_fixture(name: str):
    """A captured fixture's Response, with our own _meta stripped."""
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent / "fixtures" / name
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return document                  # image_history_session.json is a list
    document.pop("_meta", None)
    return document.get("Response", document)
```

- [ ] **Step 4: Add the `advance` fixture**

```python
@pytest.fixture
def advance(hass, loaded_entry):
    """Move the fake rig to a named state and let Home Assistant settle."""
    async def _advance(name: str):
        if name in AWAITING_CAPTURE:
            pytest.skip(f"awaiting capture: {name}")
        loaded_entry.runtime_data.client.goto(name)
        await loaded_entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()
    return _advance
```

Define `loaded_entry`, `client`, `push`, `sent` and `two_rigs` in the same
`tests/ha/conftest.py` — every later task in phases B, C and D uses them and
none of them redefines one.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/unit/test_scenarios.py -v
git add tests/scenarios tests/helpers.py tests/ha/conftest.py         tests/unit/test_scenarios.py
git commit -m "test: name the rig states the transition tests advance through"
```

---

## Task B1: `api/v2/events.py` — the socket in the seam

**Files:**
- Create: `custom_components/nina_astrophotography/api/v2/events.py`
- Delete: `custom_components/nina_astrophotography/websocket.py`
- Test: `tests/unit/test_v2_events.py`

**Interfaces:**
- Consumes: `api/errors.py`, `api/v2/mapper.py::map_event` (phase A).
- Produces:
  - `NinaEventStream(host: str, port: int, session: aiohttp.ClientSession)`
  - `.subscribe(callback: Callable[[NinaEvent], None]) -> Callable[[], None]` —
    returns the unsubscribe. **No topic parameter** until there are channels to
    map it to (§4.5).
  - `NinaEvent` gains `frame: Frame | None` and `data: Mapping[str, str | float | bool | None]`,
    and **loses `payload`**. `IMAGE-SAVE`'s `ImageStatistics` is mapped inside
    `events.py`, so the coordinator, `event.nina_error` and the blueprints never
    see a wire dict. A raw dict on the model is a wire format crossing the seam
    in the one place §0's glossary calls the contract.
  - `async .start() -> None` / `async .stop() -> None`
  - `.connected: bool`
  - `async .replay(client: NinaClientV2, generation: str | None) -> list[NinaEvent]`

- [ ] **Step 1: Write the failing test**

```python
"""The socket is a data source, not a hint — and it lives inside the seam."""
from __future__ import annotations

from datetime import datetime

from nina_astrophotography.api.models import NinaEvent
from nina_astrophotography.api.v2.events import NinaEventStream


def test_subscribe_returns_an_unsubscribe() -> None:
    stream = NinaEventStream(host="nina.local", port=1888, session=None)
    seen: list[NinaEvent] = []
    unsubscribe = stream.subscribe(seen.append)
    stream._dispatch({"Event": "IMAGE-SAVE", "Time": "2026-09-03T23:26:19.36-05:00"}, "g1")
    unsubscribe()
    stream._dispatch({"Event": "IMAGE-SAVE", "Time": "2026-09-03T23:27:19.36-05:00"}, "g1")
    assert len(seen) == 1


def test_subscribers_receive_models_not_dicts() -> None:
    """No dict crosses the api/ boundary."""
    stream = NinaEventStream(host="nina.local", port=1888, session=None)
    seen: list[NinaEvent] = []
    stream.subscribe(seen.append)
    stream._dispatch({"Event": "MOUNT-BEFORE-FLIP", "Time": "2026-09-03T23:26:19.36-05:00"}, "g1")
    assert isinstance(seen[0], NinaEvent)
    assert isinstance(seen[0].time, datetime)


def test_one_failing_subscriber_does_not_starve_the_others() -> None:
    stream = NinaEventStream(host="nina.local", port=1888, session=None)
    seen: list[NinaEvent] = []
    stream.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("boom")))
    stream.subscribe(seen.append)
    stream._dispatch({"Event": "SAFETY-CHANGED", "Time": "2026-09-03T23:26:19.36-05:00"}, "g1")
    assert len(seen) == 1


def test_a_bare_string_response_does_not_crash_the_stream() -> None:
    """The "Send WebSocket Event" instruction puts a bare string in Response."""
    stream = NinaEventStream(host="nina.local", port=1888, session=None)
    seen: list[NinaEvent] = []
    stream.subscribe(seen.append)
    stream._dispatch({"Response": "hello from the sequence"}, "g1")
    assert seen == []


def test_image_save_from_the_socket_carries_statistics() -> None:
    """The live socket carries ImageStatistics and no Time; /event-history the
    reverse — all 28 stored copies are exactly {Event, Time}."""
    stream = NinaEventStream(host="nina.local", port=1888, session=None)
    seen: list[NinaEvent] = []
    stream.subscribe(seen.append)
    stream._dispatch({"Event": "IMAGE-SAVE",
                      "ImageStatistics": load_fixture(
                          "live_image_save_push.json")["ImageStatistics"]}, "g1")
    assert seen[0].frame is not None
    assert seen[0].frame.filename == "frame_0000.fits"
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_v2_events.py -v
```

Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Lift the connection and reconnect logic from `websocket.py` — it works — but
change three things: it emits `NinaEvent` models, it takes a generation tag, and
`subscribe` has no topic parameter.

```python
"""The N.I.N.A. event socket, inside the seam.

Subscribers receive NinaEvent models. No dict crosses api/.

Two shapes of IMAGE-SAVE exist: the live socket carries ImageStatistics and no
Time, while /event-history carries Time and no statistics — all 28 stored copies
are exactly {Event, Time}. Replay therefore fixes only the timestamp; it can
never reconstruct a frame's measurements.

WebSocketV2.Events on the N.I.N.A. side is an unbounded static list with no cap,
eviction or pagination; it grows for the life of the process. Replay caps what
it folds.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import aiohttp

from ..models import NinaEvent
from .mapper import map_event

_LOGGER = logging.getLogger(__name__)

REPLAY_CAP = 2000            # a full night emitted 628; a long-lived process, more


class NinaEventStream:
    def __init__(self, host: str, port: int, session: aiohttp.ClientSession) -> None:
        self._url = f"ws://{host}:{port}/v2/socket"
        self._session = session
        self._subscribers: list[Callable[[NinaEvent], None]] = []
        self._task: asyncio.Task | None = None
        self.connected = False
        self.generation: str | None = None

    def subscribe(self, callback: Callable[[NinaEvent], None]) -> Callable[[], None]:
        """Subscribe to every event. No topic parameter — there are no channels."""
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def _dispatch(self, payload: dict, generation: str | None) -> None:
        if not isinstance(payload, dict) or "Event" not in payload:
            # A "Send WebSocket Event" instruction puts a bare string in
            # Response, and {DEVICE}-INFO-UPDATED is dead code upstream.
            return
        event = map_event(payload, generation)
        for callback in list(self._subscribers):
            try:
                callback(event)
            except Exception:                       # noqa: BLE001
                _LOGGER.exception("A N.I.N.A. event subscriber raised")

    async def replay(self, client, generation: str | None) -> list[NinaEvent]:
        """Fold /event-history at setup and on reconnect.

        An empty /event-history at setup is a normal state, not a failure — a
        N.I.N.A. restart resets it to as few as 13 events, or none.
        """
        wire = await client.get_event_history()
        return [
            map_event(item, generation)
            for item in wire[-REPLAY_CAP:]
            if isinstance(item, dict) and "Event" in item
        ]
```

…plus `start`/`stop` and the receive loop, lifted from `websocket.py` with its
reconnect backoff intact.

- [ ] **Step 4: Rewire `__init__.py` in this same commit, then delete `websocket.py`**

Deleting the module while `__init__.py` still imports `NinaWebSocketClient`
makes the package fail to import, so `tests/ha/test_smoke.py`, `test_setup.py`
and `test_light.py` all go red. §9 permits an **unbootable** branch; it requires
**green tests**. The two are not the same invariant.

Swap the construction over before removing the file:

```python
    events = NinaEventStream(host=host, port=port, session=session)
    events.subscribe(coordinator.handle_event)
    await events.start()
    entry.async_on_unload(events.stop)
```

`coordinator.handle_event` is a no-op stub in this commit — Task B4 gives it the
fold. That keeps this PR green and self-contained.

```bash
uv run pytest tests/unit/test_v2_events.py -v
uv run pytest tests/ha -q
git rm custom_components/nina_astrophotography/websocket.py
```

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/api/v2/events.py \
        tests/unit/test_v2_events.py
git commit -m "feat: move the event socket into the seam, emitting models"
```

---

## Task B2: Generations and restart detection

**Files:**
- Modify: `custom_components/nina_astrophotography/coordinator.py`
- Create: `tests/scenarios/__init__.py`, `tests/scenarios/fake_client.py`,
  `tests/unit/test_generations.py`

> **The frame set is unbounded for the N.I.N.A. process lifetime.**
> `?count=true` is process-scoped, not session-scoped, so the invariant above
> forces the coordinator to retain every frame of every night a long-running
> N.I.N.A. has produced — prune it and the reseed fires forever. The design caps
> the *event* fold (§6.3) but says nothing about this one. At Target Scheduler
> volumes a week is a few thousand `Frame` dataclasses, which is acceptable;
> record the reasoning rather than discovering it as a leak.

**Interfaces:**
- Consumes: `NinaClientV2.get_application_start`, `.get_image_history_count`,
  `.get_frames(include_all=True)`.
- Produces:
  - `NinaCoordinator.generation: str | None`
  - `NinaCoordinator._detect_restart(application_start: str | None, count: int) -> bool`
  - `FakeNinaClient(states: list[dict])` in `tests/scenarios/fake_client.py`,
    with `.advance()` and the same method signatures as `NinaClientV2`.

- [ ] **Step 1: Write the failing test**

Three independent restart signals, all observed across two restarts in one day
(§3.6).

```python
"""A N.I.N.A. restart wipes the history the design replays."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("before", "after", "restarted"),
    [
        # /application-start is authoritative.
        (("2026-09-04T10:58:59", 122), ("2026-09-04T13:54:50.907", 0), True),
        # A monotonic counter going backwards corroborates on the same tier.
        (("2026-09-04T10:58:59", 122), ("2026-09-04T10:58:59", 3), True),
        # Steady state.
        (("2026-09-04T10:58:59", 122), ("2026-09-04T10:58:59", 123), False),
        # First read: no baseline exists, so this is not a restart.
        ((None, 0), ("2026-09-04T10:58:59", 122), False),
    ],
)
def test_restart_detection(coordinator, before, after, restarted) -> None:
    coordinator.generation, coordinator._last_count = before
    assert coordinator._detect_restart(*after) is restarted


async def test_a_restart_filters_the_old_generation_rather_than_clearing_it(
    coordinator, night_frames
) -> None:
    """Clearing races a concurrent poll and loses events arriving mid-refetch."""
    coordinator.frames = {(f.date, f.filename): f for f in night_frames}
    coordinator.generation = "2026-09-04T13:54:50.907"
    data = await coordinator._async_update_data()
    assert data.session.image_count == 0
    assert coordinator.frames                      # the set is intact


async def test_a_fold_smaller_than_the_count_triggers_a_reseed(coordinator, client) -> None:
    """?count=true's job is the invariant check: fold size != count => refetch."""
    client.image_history_count = 122
    await coordinator._async_update_data()
    assert client.calls.count("get_frames(include_all=True)") == 1


async def test_an_empty_history_is_not_a_failure(coordinator, client) -> None:
    """Bare /image-history says `Index out of range`; ?all=true says []; ?count=true
    says 0. Only the first looks like a failure."""
    client.image_history_count = 0
    client.image_history = []
    data = await coordinator._async_update_data()
    assert data.session.image_count == 0
```

- [ ] **Step 2: Write `tests/scenarios/fake_client.py`**

```python
"""A scriptable stand-in for NinaClientV2.

Most of this design's behaviour is a TRANSITION, not a state — first-sight
creation, restart generation change, availability on *-DISCONNECTED, the
push-then-poll double count. A corpus of independent files cannot express any of
them, so this advances through ordered steps on demand.

Its signatures are checked against NinaClientV2's by a conformance test.
"""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def response(name: str):
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    document.pop("_meta", None)
    return document["Response"]


class FakeNinaClient:
    """Advances through ordered states; every state is captured wire data."""

    def __init__(self, states: list[dict]) -> None:
        self._states = states
        self._index = 0
        self.calls: list[str] = []

    def advance(self) -> None:
        self._index = min(self._index + 1, len(self._states) - 1)

    @property
    def state(self) -> dict:
        return self._states[self._index]

    async def get_equipment(self) -> EquipmentSnapshot:
        self.calls.append("get_equipment")
        return map_equipment_info(self.state["/equipment/info"])

    async def get_application_start(self) -> str | None:
        self.calls.append("get_application_start")
        return self.state["/application-start"]

    async def get_image_history_count(self) -> int:
        self.calls.append("get_image_history_count")
        return len(self.state["/image-history"])

    async def get_frames(self, *, include_all: bool = False,
                         generation: str | None = None) -> list[Frame]:
        self.calls.append(f"get_frames(include_all={include_all})")
        wire = self.state["/image-history"]
        return [map_frame(f, generation)
                for f in (wire if include_all else wire[-1:])]
```

…with one method per `NinaClientV2` getter, plus the conformance test (§8.7):

```python
"""FakeNinaClient must not drift from the real client's signatures."""
import inspect

from nina_astrophotography.api.v2.client import NinaClientV2
from scenarios.fake_client import FakeNinaClient


def test_the_fake_matches_the_real_clients_signatures() -> None:
    real = {n: inspect.signature(m) for n, m in inspect.getmembers(NinaClientV2,
                                                                  inspect.isfunction)
            if n.startswith("get_") or n.startswith("set_")}
    fake = {n: inspect.signature(m) for n, m in inspect.getmembers(FakeNinaClient,
                                                                  inspect.isfunction)
            if n.startswith("get_") or n.startswith("set_")}
    assert set(real) - set(fake) == set(), "the fake is missing methods"
    for name, signature in real.items():
        assert fake[name] == signature, f"{name} drifted"
```

Add `tests/scenarios` to `pythonpath` in `pyproject.toml` so `from scenarios…`
resolves:

```toml
pythonpath = ["tests"]
```

is already sufficient — `scenarios` is a package under `tests/`.

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/test_generations.py -v
```

Expected: FAIL — `_detect_restart` does not exist.

- [ ] **Step 4: Implement in `coordinator.py`**

```python
    def _detect_restart(self, application_start: str | None, count: int) -> bool:
        """Three independent signals, all observed across two restarts in a day.

        /application-start is authoritative; a monotonic counter going backwards
        is a free corroboration at the same resolution. A first read has no
        baseline, so it is never a restart.
        """
        if self.generation is None:
            return False
        if application_start and application_start != self.generation:
            return True
        return count < self._last_count
```

and in `_async_update_data`, after the fast-tier reads:

```python
        if self._detect_restart(application_start, count):
            _LOGGER.info("N.I.N.A. restarted; reseeding from /image-history?all=true")
            self.generation = application_start
            await self._reseed()
        elif len(self._frames_in(self.generation)) != count:
            # The invariant check: a fold smaller than the count means frames
            # arrived while the socket was down.
            #
            # Require the mismatch on two consecutive ticks. A frame saved
            # between the ?count=true read and the history read makes the
            # invariant fail transiently, and an immediate reseed answers that
            # with a 62 KB refetch every time it happens.
            self._mismatches += 1
            if self._mismatches >= 2:
                await self._reseed()
        else:
            self._mismatches = 0
        self._last_count = count
```

`_reseed` fetches `/image-history?all=true`, maps each frame with the **current**
generation, and unions into `self.frames`. It never clears.

- [ ] **Step 5: Run**

```bash
uv run pytest tests/unit -p no:homeassistant -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add custom_components/nina_astrophotography/coordinator.py tests/scenarios \
        tests/unit/test_generations.py
git commit -m "feat: tag every frame and event with the N.I.N.A. generation"
```

---

## Task B3: The six tiers

**Files:**
- Modify: `custom_components/nina_astrophotography/coordinator.py`
- Test: `tests/unit/test_tiers.py`

**Interfaces:**
- Produces: `NinaCoordinator._tier_due(name: str, now: float) -> bool` and the
  tier table below, driving one 10-second tick.

| Tier | When | Calls |
|---|---|---|
| Fast | 10 s | `/equipment/info` 7,245 B, `/image-history?count=true` 71 B, `/application-start` 126 B |
| Sequence | 30 s while imaging, else 5 min | `/sequence/json` 8.4 KB |
| Event-driven | on `PROFILE-*`, `AUTOFOCUS-FINISHED`, `IMAGE-SAVE`, `STACK-STATUS`, **`SAFETY-CHANGED`**, **`*-CONNECTED` / `*-DISCONNECTED`** | `/profile/show`, `/last-af`, `/image-history`, `/livestack/status`, **`/equipment/info`** |
| Floor | 5 min | the event-driven set, `/flats/status` |
| One-shot | setup, detected restart, socket reconnect | `/image-history?all=true` |
| Setup only | — | `/version`, `/version/nina` |

- [ ] **Step 1: Write the failing test**

```python
"""Six tiers, one coordinator. Not three coordinators."""
from __future__ import annotations

import pytest


async def test_the_fast_tier_runs_every_tick(coordinator, client) -> None:
    for _ in range(3):
        await coordinator._async_update_data()
    assert client.calls.count("get_equipment") == 3


async def test_the_sequence_tier_is_thirty_seconds_while_imaging(coordinator, client) -> None:
    """Imaging is inferred from activity, never from node status."""
    client.image_history_count = 10
    await coordinator._async_update_data()
    client.image_history_count = 11              # a rising count means imaging
    coordinator._advance_clock(30)
    await coordinator._async_update_data()
    assert client.calls.count("get_sequence_json") == 2


async def test_the_sequence_tier_falls_to_five_minutes_when_idle(coordinator, client) -> None:
    """Three nodes read RUNNING on an idle rig with zero frames captured.
    Gating on tree status would poll at 30 s indefinitely — ~24 MB/day."""
    await coordinator._async_update_data()
    coordinator._advance_clock(60)
    await coordinator._async_update_data()
    assert client.calls.count("get_sequence_json") == 1


async def test_sequence_finished_drops_the_tier_immediately(coordinator, client) -> None:
    """A valid signal to stop polling fast, without waiting for the heuristic."""
    coordinator._on_event(_event("SEQUENCE-FINISHED"))
    coordinator._advance_clock(60)
    await coordinator._async_update_data()
    assert client.calls.count("get_sequence_json") == 1


async def test_ts_targetstart_does_not_refetch_the_sequence(coordinator, client) -> None:
    """It fires once per exposure — 27 in 3.8 h — and its payload already
    carries TargetName, ProjectName, Rotation and TargetEndTime."""
    before = client.calls.count("get_sequence_json")
    for _ in range(10):
        coordinator._on_event(_event("TS-TARGETSTART"))
    assert client.calls.count("get_sequence_json") == before


async def test_stack_status_refetches_the_livestack_status(coordinator, client) -> None:
    """STACK-STATUS is a bare {Event, Time} — it signals THAT the status changed,
    never what to."""
    coordinator._on_event(_event("STACK-STATUS"))
    await coordinator._async_update_data()
    assert "get_livestack_status" in client.calls


async def test_the_floor_backstops_the_event_driven_set(coordinator, client) -> None:
    """/flats/status has no event at all — FLAT-* events are panel hardware."""
    coordinator._advance_clock(300)
    await coordinator._async_update_data()
    assert "get_flats_status" in client.calls


async def test_a_sequence_refetch_is_debounced_to_one_per_thirty_seconds(
    coordinator, client
) -> None:
    before = client.calls.count("get_sequence_json")
    for _ in range(5):
        coordinator._request_sequence_refetch()
    await coordinator._async_update_data()
    assert client.calls.count("get_sequence_json") == before + 1
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/test_tiers.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# Six tiers, one DataUpdateCoordinator ticking at 10 s with per-tier due-time
# checks inside _async_update_data. Not three coordinators.
#
#   fast       7,442 B @ 10 s  =  44,652 B/min
#   sequence   8,429 B @ 30 s  =  16,858 B/min
#                                 ──────────
#                                 61,510 B/min ~ 3.7 MB/h ~ 37 MB / 10 h night
#   before                        82,606 B x 6/min ~ 297 MB / night
FAST_INTERVAL = timedelta(seconds=10)
SEQUENCE_IMAGING = 30.0
SEQUENCE_IDLE = 300.0
FLOOR = 300.0
SEQUENCE_DEBOUNCE = 30.0
```

Imaging is inferred from activity, all of it already on the fast tier (§6.2):

```python
    def _imaging(self, snapshot: EquipmentSnapshot, count: int) -> bool:
        """Infer imaging from activity, never from /sequence/json node status.

        Node Status persists from the loaded sequence file and from prior runs:
        on the idle rig three nodes read RUNNING with nothing happening and zero
        frames captured. Tree status drives only the displayed per-instruction
        state.
        """
        if count > self._last_count:
            return True
        camera = snapshot.camera
        if camera is not None and camera.is_exposing:
            return True
        return self._seconds_since_last_image_save() < 300
```

- [ ] **Step 4: Re-measure**

```bash
scripts/measure_payloads.sh "$NINA_HOST"
```

Compare against §3.3. If any endpoint has grown more than ~20%, amend §3.3 with
the new numbers in this PR — the design is never permitted to be wrong about the
rig it describes.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/unit -p no:homeassistant -q
git add custom_components/nina_astrophotography/coordinator.py tests/unit/test_tiers.py
git commit -m "perf: poll in six tiers behind one coordinator tick"
```

---

## Task B4: The push path

**Files:**
- Modify: `custom_components/nina_astrophotography/coordinator.py`,
  `custom_components/nina_astrophotography/__init__.py`
- Delete: `custom_components/nina_astrophotography/frame_statistics.py`
- Test: `tests/ha/test_push.py`, `tests/unit/test_push_fold.py`

**Interfaces:**
- Consumes: `NinaEventStream.subscribe` (B1), `fold` (phase A).
- Produces: `NinaCoordinator._on_event(event: NinaEvent) -> None`, calling
  `async_set_updated_data` synchronously on the event loop.

- [ ] **Step 1: Write the failing test**

```python
"""Push, poll and replay are one idempotent operation."""
from __future__ import annotations


async def test_a_pushed_frame_appears_without_waiting_for_the_poll(
    hass, entry_with_socket, image_save_event
) -> None:
    """async_set_updated_data, not async_request_refresh — the line that makes
    this design push-first rather than socket-as-a-hint."""
    before = hass.states.get("sensor.n_i_n_a_astrophotography_session_image_count").state
    entry_with_socket.push(image_save_event)
    await hass.async_block_till_done()
    after = hass.states.get("sensor.n_i_n_a_astrophotography_session_image_count").state
    assert int(after) == int(before) + 1


async def test_the_same_frame_pushed_then_polled_is_counted_once(
    hass, entry_with_socket, image_save_event
) -> None:
    """Frame identity is (Date, Filename), identical on both paths — confirmed
    field-for-field from a live 1 s dark."""
    entry_with_socket.push(image_save_event)
    await hass.async_block_till_done()
    await entry_with_socket.poll()
    await hass.async_block_till_done()
    assert hass.states.get(
        "sensor.n_i_n_a_astrophotography_session_image_count"
    ).state == "1"


async def test_replayed_events_are_deduped_per_generation(coordinator) -> None:
    """A restart produces fresh timestamps that can be EARLIER than a retained
    mark — a next-evening restart gives 21:00 events against an 05:30 mark."""
    coordinator.generation = "g1"
    coordinator._mark_seen(_event("IMAGE-SAVE", "2026-09-04T05:30:00-05:00"))
    coordinator.generation = "g2"
    assert coordinator._already_seen(_event("IMAGE-SAVE", "2026-09-03T21:00:00-05:00")) is False


async def test_a_disconnect_event_makes_that_devices_entities_unavailable(
    hass, entry_with_socket
) -> None:
    entry_with_socket.push(_event("CAMERA-DISCONNECTED"))
    await hass.async_block_till_done()
    assert hass.states.get("sensor.n_i_n_a_camera_temperature").state == "unavailable"
```

- [ ] **Step 2: Run**

Expected: FAIL — `_on_event` does not exist.

- [ ] **Step 3: Implement**

```python
    def _on_event(self, event: NinaEvent) -> None:
        """Fold a pushed event and publish, on the event loop.

        NinaData is assembled from the live set with no `await` between reading
        the set and freezing the dataclass: four writers touch it, and without
        that rule a poll awaiting /equipment/info while IMAGE-SAVE arrives
        publishes a pre-event snapshot, so the frame appears, vanishes and
        reappears.
        """
        if self._already_seen(event):
            return
        self._mark_seen(event)
        self.events.append(event)

        if event.name == "IMAGE-SAVE":
            # events.py already mapped it — no wire dict reaches this module.
            if event.frame is not None:
                self.frames[(event.frame.date, event.frame.filename)] = event.frame
        elif event.name == "SAFETY-CHANGED" or _CONNECTION_EVENT.match(event.name):
            # §6.4: nothing safety-related waits for a tier. A safety transition
            # or a device dropping out must not sit until the next 10 s poll —
            # latency is the entire point on the one entity that closes a roof.
            self._pending_refetch.add("/equipment/info")
            self.hass.async_create_task(self.async_refresh())
        elif event.name in _REFETCH_ON:
            self._pending_refetch.add(_REFETCH_ON[event.name])

        if self.data is not None:
            self.async_set_updated_data(self._assemble())
```

Then delete `frame_statistics.py` and its `__init__.py` wiring; `session.py`
replaced it in phase A and the coordinator now owns the set.

- [ ] **Step 4: Run both suites**

```bash
uv run pytest tests/unit -p no:homeassistant -q
uv run pytest tests/ha -q
```

- [ ] **Step 5: Commit**

```bash
git add -A custom_components/nina_astrophotography tests
git commit -m "feat: publish pushed events directly instead of re-polling"
```

---

## Task B5: `device.py` — the device model

**Files:**
- Create: `custom_components/nina_astrophotography/device.py`
- Modify: `custom_components/nina_astrophotography/entity.py`,
  `custom_components/nina_astrophotography/__init__.py`
- Test: `tests/ha/test_devices.py`

**Interfaces:**
- Consumes: `EquipmentSnapshot`, `DeviceMeta` (phase A).
- Produces:
  - `hub_device_info(entry_id: str, instance_name: str, version: VersionInfo) -> DeviceInfo`
  - `child_device_info(entry_id: str, instance_name: str, kind: str, meta: DeviceMeta) -> DeviceInfo`
  - `async_sync_devices(hass, entry, snapshot) -> None` — first-sight creation.
  - `async_remove_config_entry_device(hass, entry, device) -> bool` in `__init__.py`.
  - `NinaEntity.__init__(coordinator, entry, key, kind: str | None = None)` —
    `kind` selects the child device; `None` puts the entity on the hub.

Lift `device.py` from `wip/v2.0`, **with `_INSTANCE_NAMES` moved to
`runtime_data`**: a module-level dict keyed by `entry_id` is exactly the pattern
Bronze `runtime-data` removes, and it leaks on failed unload (§4.0).

- [ ] **Step 1: Write the failing test**

```python
"""One hub, one child per equipment type, linked by via_device."""
from homeassistant.helpers import device_registry as dr


async def test_each_equipment_type_is_its_own_device(hass, loaded_entry) -> None:
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    names = {d.name for d in devices}
    assert {"Camera", "Mount", "Focuser", "Filter Wheel", "Guider"} <= names


async def test_children_hang_off_the_hub(hass, loaded_entry) -> None:
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    hub = next(d for d in devices if d.via_device_id is None)
    assert all(d.via_device_id == hub.id for d in devices if d is not hub)


async def test_driver_metadata_lands_in_the_registry_not_entity_attributes(
    hass, loaded_entry
) -> None:
    """DriverVersion is the sw_version (§5.1)."""
    registry = dr.async_get(hass)
    camera = registry.async_get_device({(DOMAIN, f"{loaded_entry.entry_id}_camera")})
    assert camera.sw_version is not None


async def test_a_device_never_observed_is_not_created(hass, loaded_entry) -> None:
    """First-sight: create on first observation of the equipment, keep after."""
    registry = dr.async_get(hass)
    assert registry.async_get_device({(DOMAIN, f"{loaded_entry.entry_id}_dome")}) is None


async def test_a_device_seen_once_survives_a_disconnection(hass, loaded_entry, advance):
    """Persistence comes from the device registry, not from the poll."""
    await advance("equipment_disconnected")
    registry = dr.async_get(hass)
    assert registry.async_get_device({(DOMAIN, f"{loaded_entry.entry_id}_camera")})


async def test_a_sold_dome_can_be_deleted(hass, loaded_entry) -> None:
    """Gold stale-devices: pair dynamic creation with removal."""
    from custom_components.nina_astrophotography import async_remove_config_entry_device
    registry = dr.async_get(hass)
    camera = registry.async_get_device({(DOMAIN, f"{loaded_entry.entry_id}_camera")})
    assert await async_remove_config_entry_device(hass, loaded_entry, camera) is False
```

The last assertion is `False` because the camera is currently present —
`async_remove_config_entry_device` returns `True` only for a device the snapshot
no longer reports.

- [ ] **Step 2: Run, implement, run**

```bash
uv run pytest tests/ha/test_devices.py -v      # FAIL
# implement device.py
uv run pytest tests/ha/test_devices.py -v      # PASS
```

- [ ] **Step 3: Commit**

```bash
git add custom_components/nina_astrophotography/device.py \
        custom_components/nina_astrophotography/entity.py \
        custom_components/nina_astrophotography/__init__.py tests/ha/test_devices.py
git commit -m "feat: give each piece of equipment its own device"
```

---

## Task B6: Availability, three levels

**Files:**
- Modify: `custom_components/nina_astrophotography/entity.py`,
  `custom_components/nina_astrophotography/coordinator.py`
- Test: `tests/ha/test_availability.py`

**Interfaces:**
- Produces: `NinaEntity.available` implementing level 2, and
  `log-when-unavailable` — the transition logged once at `warning`, recovery once
  at `info`.

- [ ] **Step 1: Write the failing test**

Level 1 is `CoordinatorEntity.available` propagating `last_update_success` —
**do not test it** (§8.2). Levels 2 and 3 are ours.

```python
"""Availability levels 2 and 3. Level 1 is Home Assistant's own."""


async def test_a_disconnected_device_makes_its_entities_unavailable(
    hass, loaded_entry, advance
) -> None:
    await advance("camera_disconnected")
    assert hass.states.get("sensor.n_i_n_a_camera_temperature").state == "unavailable"


async def test_a_sentinel_reading_is_unknown_not_unavailable(hass, loaded_entry) -> None:
    """Reachable and connected but the value is missing: "NaN", HFR 0, the
    meridian 24 sentinel."""
    assert hass.states.get("sensor.n_i_n_a_mount_time_to_meridian_flip").state == "unknown"


async def test_the_safety_monitor_keeps_its_connected_sensor(hass, loaded_entry) -> None:
    """THE highest-value test in the file.

    A disconnected safety monitor would make safety_unsafe unavailable, so a
    roof-close automation on `to: "off"` does not fire. `to: "unavailable"`
    cannot substitute — it conflates device-disconnected, N.I.N.A.-unreachable,
    HA-restarting and coordinator-failed. This is the only asymmetric-risk
    entity in the set.
    """
    state = hass.states.get("binary_sensor.n_i_n_a_safety_monitor_connected")
    assert state is not None
    assert state.attributes["device_class"] == "connectivity"


async def test_the_safety_monitor_connected_sensor_survives_disconnection(
    hass, loaded_entry, advance
) -> None:
    await advance("safety_monitor_disconnected")
    assert hass.states.get(
        "binary_sensor.n_i_n_a_safety_monitor_connected"
    ).state == "off"


async def test_unavailability_is_logged_once_and_recovery_once(
    hass, loaded_entry, advance, caplog
) -> None:
    await advance("nina_unreachable")
    await advance("nina_unreachable")
    assert caplog.text.count("is unavailable") == 1
    await advance("imaging")
    assert caplog.text.count("is back online") == 1
```

- [ ] **Step 2: Implement, run, commit**

Delete `poll_all`'s `except: results[key] = {}` pattern — it no longer exists,
but assert its absence in review. Then:

```bash
uv run pytest tests/ha/test_availability.py -v
git add custom_components/nina_astrophotography tests/ha/test_availability.py
git commit -m "feat: derive availability from connection state, logging once"
```

---

## Task B7: Config flow — instance name and 100% coverage

**Files:**
- Modify: `custom_components/nina_astrophotography/config_flow.py`,
  `custom_components/nina_astrophotography/const.py`,
  `custom_components/nina_astrophotography/strings.json`
- Test: `tests/ha/test_config_flow.py`

**Interfaces:**
- Produces: a user step taking host, port, poll interval and **instance name**;
  the `vol.In(["v2"])` API-version dropdown **removed** (one valid choice);
  `CONF_INSTANCE_NAME = "instance_name"` in `const.py`.

Bronze `config-flow-test-coverage` is **100%, branch** — including error recovery
and the duplicate-entry guard.

- [ ] **Step 1: Write the failing tests**

```python
"""The config flow, at 100% branch coverage."""
from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.nina_astrophotography.api.errors import (
    NinaConnectionError,
    NinaEndpointError,
)

CLIENT = "custom_components.nina_astrophotography.api.v2.client.NinaClientV2.get_version"


async def test_a_valid_rig_creates_an_entry(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"})
    with patch(CLIENT, return_value="2.2.15.2"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Rooftop"


async def test_an_unreachable_rig_shows_cannot_connect_and_recovers(hass) -> None:
    """Bronze test-before-configure, plus the recovery branch."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"})
    with patch(CLIENT, side_effect=NinaConnectionError("refused")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"},
        )
    assert result["errors"] == {"base": "cannot_connect"}
    with patch(CLIENT, return_value="2.2.15.2"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_build_without_the_api_shows_unsupported(hass) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"})
    with patch(CLIENT, side_effect=NinaEndpointError("no /version")):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Rooftop"},
        )
    assert result["errors"] == {"base": "unsupported_api"}


async def test_the_same_host_and_port_cannot_be_added_twice(hass, loaded_entry) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"})
    with patch(CLIENT, return_value="2.2.15.2"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "nina.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Again"},
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_a_second_rig_on_a_different_host_is_allowed(hass, loaded_entry) -> None:
    """Two rigs must coexist — that is why the instance name exists."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"})
    with patch(CLIENT, return_value="2.2.15.2"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_HOST: "other.local", CONF_PORT: 1888, CONF_INSTANCE_NAME: "Dome"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_options_flow_changes_the_poll_interval(hass, loaded_entry) -> None:
    result = await hass.config_entries.options.async_init(loaded_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_POLL_INTERVAL: 30})
    assert result["type"] is FlowResultType.CREATE_ENTRY
```

- [ ] **Step 2: Promote `config_flow.py` out of `PENDING`**

In `scripts/coverage_floors.py`, move `"config_flow.py": 100` from `PENDING`
into `FLOORS`. This is the PR that makes it achievable, so it is the PR that
makes it binding.

- [ ] **Step 3: Add the session rollover hour to the options flow**

§4.4 promises the rollover hour is configurable, and `derive.session_start` and
`fold` both take it — but nothing supplies it. Add `CONF_ROLLOVER_HOUR` to the
options flow, defaulting to 12.

> A noon default is wrong for a rig whose Windows clock runs UTC, which is
> common on hosted setups: all N.I.N.A. timestamps are local to that clock, so
> "local noon" falls at 07:00 site time for a −05:00 site — inside the dawn flat
> run, splitting one night's session in two. This option is what makes that
> fixable, so surface it in the README rather than burying it.

- [ ] **Step 4: Implement, then prove 100%**

```bash
uv run coverage run -m pytest tests/ha/test_config_flow.py
uv run coverage json
uv run python scripts/coverage_floors.py
```

Expected: `config_flow.py` at exactly 100. If a branch is uncovered, the missing
test is the interesting one — write it rather than lowering the floor.

- [ ] **Step 5: Commit**

```bash
git add custom_components/nina_astrophotography/config_flow.py \
        scripts/coverage_floors.py \
        custom_components/nina_astrophotography/const.py \
        custom_components/nina_astrophotography/strings.json \
        tests/ha/test_config_flow.py
git commit -m "feat: name each N.I.N.A. instance in the config flow"
```

---

## Task B8: Start the rename record

**Files:**
- Create: `docs/2.0-renames.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Create the file with this phase's renames**

```markdown
# 2.0 entity renames

Every entity whose `entity_id` or `unique_id` changed in 2.0, with the 1.4.5
name it replaces. Appended by each phase-B and phase-C PR; formatted in D1.

The authoritative record is the entity registry snapshot (§8.6) — this file must
match it.

| 1.4.5 | 2.0 | Why |
|---|---|---|
| `sensor.nina_camera_temperature` | `sensor.<instance>_camera_temperature` | Entities hang off their own device (§5.1) |
```

- [ ] **Step 2: Open the CHANGELOG's breaking-changes section**

```markdown
## [2.0.0] — unreleased

### Breaking

- Every entity id changes: entities now hang off a device per equipment type
  rather than one device per integration. `docs/2.0-renames.md` is the mapping.
- `binary_sensor.*_connected` are removed for ten devices; a disconnected device
  now makes its entities `unavailable`. The safety monitor keeps its connected
  sensor deliberately — see the README.
```

- [ ] **Step 3: Commit**

```bash
git add docs/2.0-renames.md CHANGELOG.md
git commit -m "docs: start the rename record and the breaking-changes section"
```

---

## Known gaps in this plan

| Task | What is prose-only | Weight |
|---|---|---|
| B1 | `start`/`stop` and the receive loop | Lifted from `websocket.py`, which works; keep its reconnect backoff |
| B3 | `_tier_due`, `_seconds_since_last_image_save` | The tier table and the tests fully determine both |
| B4 | `_assemble`, `_already_seen`, `_mark_seen`, `_REFETCH_ON` | `_assemble` refactors A14's inline `NinaData` construction — do that first, it is the one that is not a one-liner |
| B5 | `device.py`'s three functions | The registry shape is pinned by the tests |
| B6 | availability levels 2 and 3, log-once | Level 1 is deliberately untested (it is `CoordinatorEntity`'s) |

## Phase B exit criteria

- [ ] Both suites green; six CI jobs green.
- [ ] `config_flow.py` at 100% branch coverage.
- [ ] A restart scenario passes end-to-end from the captured `dawn_*` →
      `restart_*` pair: generation changes, the fold filters rather than clears,
      and the reseed uses `?all=true`.
- [ ] `scripts/measure_payloads.sh` confirms the tiering saving, or §3.3 is
      amended with the new numbers.
- [ ] `websocket.py` and `frame_statistics.py` are deleted.
- [ ] `docs/2.0-renames.md` exists and covers every rename made so far.
- [ ] `_INSTANCE_NAMES` exists nowhere as a module-level dict.

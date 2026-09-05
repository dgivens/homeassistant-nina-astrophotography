"""Fixtures for the Home-Assistant-dependent suite."""
from __future__ import annotations

import sys
from typing import NamedTuple

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from scenarios.fake_rig import FakeRig
from scenarios.states import AWAITING_CAPTURE, STATES

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
        # No `instance_name`: a 1.4.x entry, which is what an upgrade brings.
        # 1.4.5's flow already set this unique id, so every real entry has one.
        unique_id="nina.local:1888",
        entry_id="01JTESTENTRY0000000000000",
    )


def _serve(monkeypatch, session) -> None:
    """Give the integration `session` as its HTTP transport, and silence the
    event socket: pytest-socket refuses the connection and the reconnect loop
    would otherwise outlive the test. Tests push through the `push` fixture.

    Only `start` is stubbed. With no receive task and no socket, the real
    `stop` runs harmlessly on unload — and stubbing it too would leave nothing
    for a test of the unload path to observe.
    """
    import custom_components.nina_astrophotography as integration
    from custom_components.nina_astrophotography.api.v2 import NinaEventStream

    monkeypatch.setattr(integration, "async_get_clientsession", lambda hass: session)
    monkeypatch.setattr(NinaEventStream, "start", lambda self: _async(None))


@pytest.fixture
def rig(monkeypatch) -> FakeRig:
    """The fake rig the entry polls, serving the `imaging` state.

    A transport fake, not a client fake: the real client runs above it, so
    setup exercises envelope classification, the wire→model mapper and the
    rig-offset cache against captured bytes — including `/version`, which is
    served rather than stubbed.
    """
    fake = FakeRig(STATES, start="imaging")
    _serve(monkeypatch, fake)
    return fake


@pytest.fixture
def nina_responses(rig):
    """The rig, under the name the phase-A tests ask for.

    Returns the fixture loader, so a test that needs the same wire data can
    read it without opening the file itself.
    """
    from helpers import load_fixture

    return load_fixture


@pytest.fixture
def advance(hass, loaded_entry, rig):
    """Move the fake rig to a named state and let Home Assistant settle."""
    async def _advance(name: str) -> None:
        if name in AWAITING_CAPTURE:
            pytest.skip(f"awaiting capture: {name}")
        rig.goto(name)
        await loaded_entry.runtime_data.coordinator.async_refresh()
        await hass.async_block_till_done()

    return _advance


class _RigRouter:
    """One transport in front of several rigs, dispatching on the URL's host."""

    def __init__(self, rigs: dict[str, FakeRig]) -> None:
        self.rigs = rigs

    def _rig(self, url: str) -> FakeRig:
        return self.rigs[url.split("//", 1)[1].split(":", 1)[0]]

    def get(self, url, params=None, timeout=None):
        return self._rig(url).get(url, params, timeout)

    def post(self, url, json=None, params=None, timeout=None):
        return self._rig(url).post(url, json, params, timeout)


class TwoRigs(NamedTuple):
    """Two loaded entries and the rig each one reads, in the same order."""

    entries: tuple[MockConfigEntry, ...]
    rigs: tuple[FakeRig, ...]


@pytest.fixture
async def two_rigs(hass, monkeypatch) -> TwoRigs:
    """Two loaded instances, each reading its own rig.

    The second rig starts restarted: two identical rigs cannot show that a
    request reached the right one. The rigs come back too, so a test can move
    one instance without touching the other.
    """
    instances = [("nina.local", "N.I.N.A.", "imaging"),
                 ("other.local", "Dome", "nina_restarted")]
    rigs = {host: FakeRig(STATES, start=state) for host, _, state in instances}
    _serve(monkeypatch, _RigRouter(rigs))
    entries = []
    for index, (host, title, _) in enumerate(instances):
        entry = MockConfigEntry(
            domain=DOMAIN, title=title,
            data={CONF_HOST: host, CONF_PORT: 1888},
            unique_id=f"{host}:1888",
            entry_id=f"01JTESTENTRY000000000000{index}",
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        entries.append(entry)
    await hass.async_block_till_done()
    return TwoRigs(tuple(entries), tuple(rigs.values()))


@pytest.fixture
def push(loaded_entry):
    """Deliver one socket payload — the `Response` of a captured push — as the
    live receive loop would.

    `_dispatch` is the one private call test code makes: the socket itself is
    silenced, and driving the stream from outside is the only way to exercise
    the push path. Everything above it is public.
    """
    runtime = loaded_entry.runtime_data

    def _push(payload: dict) -> None:
        runtime.events._dispatch(payload, runtime.coordinator.generation)

    return _push


async def _async(value):
    return value


@pytest.fixture
async def loaded_entry(hass, config_entry, nina_responses) -> MockConfigEntry:
    """The entry set up against the dawn snapshot, exactly as captured."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def set_up_with_flat_device(hass, config_entry, nina_responses, monkeypatch):
    """Set the entry up against the dawn snapshot with its panel varied.

    Varies the mapped MODEL, not the captured wire JSON: the fixture rule bans
    hand-written wire documents, and every flat-panel state a test needs is one
    field away from the panel the rig actually reported.
    """
    from dataclasses import replace

    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
    from custom_components.nina_astrophotography.api.v2.mapper import map_equipment_info

    async def _set_up(**changes):
        snapshot = map_equipment_info(nina_responses("dawn_equipment_info.json"))
        snapshot = replace(snapshot, flat_device=replace(snapshot.flat_device, **changes))
        monkeypatch.setattr(NinaClientV2, "get_equipment", lambda self: _async(snapshot))
        config_entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()
        return config_entry

    return _set_up


@pytest.fixture
async def flat_panel_entry(set_up_with_flat_device):
    """The dawn panel lit at half output: driver 2048 of 4096."""
    return await set_up_with_flat_device(brightness=2048.0, light_on=True)


@pytest.fixture
async def idle_flat_panel_entry(set_up_with_flat_device):
    """The dawn panel exactly as captured: off, brightness 0."""
    return await set_up_with_flat_device()


@pytest.fixture
async def disconnected_flat_panel_entry(set_up_with_flat_device):
    """Observed once, now down: Min 0 / Max 0 is what a disconnected panel reports."""
    return await set_up_with_flat_device(
        connected=False, brightness=None, light_on=None,
        min_brightness=0.0, max_brightness=0.0,
    )


@pytest.fixture
async def cover_only_flat_panel_entry(set_up_with_flat_device):
    return await set_up_with_flat_device(supports_on_off=False)


class _Sent:
    """Records the flat panel commands the entity sends, in order."""

    def __init__(self, monkeypatch) -> None:
        self._monkeypatch = monkeypatch
        self.calls: list[tuple[str, object]] = []

    @property
    def brightness(self):
        """The last driver-unit brightness sent, or None."""
        values = [value for name, value in self.calls if name == "set_flat_brightness"]
        return values[-1] if values else None

    @property
    def last_call(self):
        return self.calls[-1] if self.calls else None

    def patch(self, name: str, method) -> None:
        from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

        self._monkeypatch.setattr(NinaClientV2, name, method)


@pytest.fixture
def sent(monkeypatch) -> _Sent:
    """Patched on the class, so it works whichever order the fixtures resolve."""
    recorder = _Sent(monkeypatch)

    async def set_flat_brightness(self, brightness: int) -> None:
        recorder.calls.append(("set_flat_brightness", brightness))

    async def set_flat_light(self, on: bool) -> None:
        recorder.calls.append(("set_flat_light", on))

    recorder.patch("set_flat_brightness", set_flat_brightness)
    recorder.patch("set_flat_light", set_flat_light)
    return recorder

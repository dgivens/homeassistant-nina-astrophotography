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


@pytest.fixture
def nina_responses(monkeypatch):
    """Stub the client's fast-tier reads with captured fixtures.

    `get_equipment` runs the captured `/equipment/info` response through the
    real wire→model mapper, so setup sees a snapshot shaped exactly as the rig
    produces it. The socket is silenced: pytest-socket refuses the connection
    and the reconnect loop would otherwise outlive the test.
    """
    import json
    from pathlib import Path

    from custom_components.nina_astrophotography.api.models import VersionInfo
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
    from custom_components.nina_astrophotography.api.v2.mapper import map_equipment_info
    from custom_components.nina_astrophotography.websocket import NinaWebSocketClient

    fixtures = Path(__file__).resolve().parents[1] / "fixtures"

    def _response(name: str):
        document = json.loads((fixtures / name).read_text(encoding="utf-8"))
        document.pop("_meta", None)
        return document["Response"]

    monkeypatch.setattr(
        NinaClientV2, "get_versions",
        lambda self: _async(VersionInfo("2.2.15.2", "3.2.0.9001")),
    )
    monkeypatch.setattr(
        NinaClientV2, "get_equipment",
        lambda self: _async(map_equipment_info(_response("dawn_equipment_info.json"))),
    )
    monkeypatch.setattr(NinaClientV2, "get_image_history_count", lambda self: _async(122))
    monkeypatch.setattr(
        NinaClientV2, "get_application_start", lambda self: _async("2026-09-04T10:58:59"),
    )
    monkeypatch.setattr(NinaWebSocketClient, "start", lambda self: _async(None))
    monkeypatch.setattr(NinaWebSocketClient, "stop", lambda self: _async(None))
    return _response


async def _async(value):
    return value


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

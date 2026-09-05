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

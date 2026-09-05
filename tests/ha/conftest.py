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

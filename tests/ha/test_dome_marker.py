"""Dome ships untested — the marker is enforced, not merely documented.

`tests/ha` rather than `tests/unit`: every platform module imports Home
Assistant, so this cannot run under `pytest tests/unit -p no:homeassistant`.
The mapper half, which touches `api/v2/mapper.py` and nothing else, is
`tests/unit/test_dome_mapping.py`.
"""
import importlib

import pytest
from homeassistant.const import EntityCategory

PLATFORMS = ("binary_sensor", "sensor", "number", "switch", "button")


def _dome(module_name: str) -> list:
    module = importlib.import_module(
        f"custom_components.nina_astrophotography.{module_name}"
    )
    return [d for d in module.DESCRIPTIONS if getattr(d, "kind", None) == "dome"]


@pytest.mark.parametrize("module_name", PLATFORMS, ids=PLATFORMS)
def test_every_dome_descriptor_is_marked_unverified(module_name: str) -> None:
    """No dome has ever been validated against hardware (§5.3.1), and the
    marker is what a reviewer of a future dome change looks for."""
    dome = _dome(module_name)
    assert dome, f"{module_name} declares no dome entities — remove it from PLATFORMS"
    assert [d.key for d in dome if d.verified] == []


@pytest.mark.parametrize("module_name", PLATFORMS, ids=PLATFORMS)
def test_every_dome_entity_ships_diagnostic_and_disabled(module_name: str) -> None:
    """Asserted on the descriptors: no capture observes a dome, so there is no
    registry row to read it off."""
    assert [
        d.key
        for d in _dome(module_name)
        if d.entity_category is not EntityCategory.DIAGNOSTIC
        or d.entity_registry_enabled_default
    ] == []

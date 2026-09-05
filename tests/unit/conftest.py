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

"""Registers the integration package for import.

The modules under test import no Home Assistant code, so these tests run with
`uv sync` and no HA checkout. The integration's
`__init__.py` does import Home Assistant, so the package is registered here
with its `__path__` set but never executed — submodules and their relative
imports still resolve.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

_COMPONENT = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "nina_astrophotography"
)

if "nina_astrophotography" not in sys.modules:
    _pkg = types.ModuleType("nina_astrophotography")
    _pkg.__path__ = [str(_COMPONENT)]
    sys.modules["nina_astrophotography"] = _pkg

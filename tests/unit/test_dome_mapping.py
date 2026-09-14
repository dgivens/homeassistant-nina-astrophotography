"""The dome mapper path, on a fixture no rig produced.

There is no dome available and no prospect of one, so `DomeInfo` cannot be
validated — and it is the one subsystem where the spec is known wrong (five
missing fields, `Azimuth` typed integer while the wire sends `"NaN"`). The
drift guard cannot see dome fields at all.

Reachability only, never values: what the fixture proves is that the connected
branch runs, not what a real dome would report through it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nina_astrophotography.api.v2.mapper import map_equipment_info

_FIXTURE = Path(__file__).resolve().parents[1] / "synthetic" / "dome_connected.json"


@pytest.fixture
def snapshot():
    wire = json.loads(_FIXTURE.read_text(encoding="utf-8"))["Response"]
    return map_equipment_info(wire)


@pytest.mark.synthetic
def test_a_connected_dome_reaches_the_mapped_model(snapshot) -> None:
    assert snapshot.dome is not None
    assert snapshot.dome.connected is True


@pytest.mark.synthetic
def test_the_other_ten_blocks_are_the_captures_own(snapshot) -> None:
    """Only `Dome` is fabricated: a synthetic file that quietly changed a
    second block would put the rest of the suite on invented wire data."""
    captured = json.loads(
        (_FIXTURE.parents[1] / "fixtures" / "restart_equipment_partial_connect.json")
        .read_text(encoding="utf-8")
    )["Response"]
    wire = json.loads(_FIXTURE.read_text(encoding="utf-8"))["Response"]
    assert {k: v for k, v in wire.items() if k != "Dome"} == {
        k: v for k, v in captured.items() if k != "Dome"
    }

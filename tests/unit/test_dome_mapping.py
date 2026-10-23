"""The dome mapper, against the test VM's OmniSim dome (`docs/test-vm.md`).

Real wire data from a simulated dome: no dome owner has reported a capture, so
a real driver's quirks — a roll-off roof with no azimuth, a slow shutter, a
`ShutterError` — are not in the corpus.
"""

from copy import deepcopy

from nina_astrophotography.api.v2.mapper import map_dome, map_equipment_info
import pytest

from helpers import load_fixture as load


def _dome(state: str):
    return map_equipment_info(load(f"simulator_dome_{state}_equipment_info.json")).dome


@pytest.mark.parametrize(
    ("state", "field", "expected"),
    [
        ("parked", "shutter_status", "closed"),
        ("parked", "at_park", True),
        ("parked", "azimuth", 180.0),
        ("following", "shutter_status", "open"),
        ("following", "following", True),
        ("following", "synchronized", True),
        ("slewing", "slewing", True),
        ("at_home", "at_home", True),
        ("disconnected", "shutter_status", None),  # ShutterNone, down
        ("disconnected", "azimuth", None),  # "NaN"
    ],
)
def test_each_capture_maps_its_readings(state, field, expected) -> None:
    assert getattr(_dome(state), field) == expected


def test_synchronized_is_none_unless_following() -> None:
    """N.I.N.A. keeps `IsSynchronized` true after following stops."""
    wire = load("simulator_dome_parked_equipment_info.json")["Dome"]
    assert wire["IsSynchronized"] is True
    assert map_dome(wire).synchronized is None


@pytest.mark.parametrize(
    "field", ["can_set_shutter", "can_set_azimuth", "can_park", "can_find_home"]
)
def test_capabilities_survive_a_disconnect(field) -> None:
    """Read from the block, not the readings, as the flat panel's are."""
    assert getattr(_dome("parked"), field) is True
    assert getattr(_dome("disconnected"), field) is False


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        ("ShutterOpening", "opening"),
        ("ShutterClosing", "closing"),
        ("ShutterError", "error"),
        ("ShutterNone", None),
        ("ShutterAjar", None),
    ],
)
def test_every_shutter_state_maps(wire, expected) -> None:
    """The parked capture with `ShutterStatus` moved. Opening and closing were
    seen on the wire but finish between two of N.I.N.A.'s refreshes too often
    to capture; `ShutterError` is N.I.N.A.'s enum name, which the simulator
    cannot produce; `ShutterNone` on a connected dome is a driver with no
    shutter; an unknown name reads as no reading.
    """
    block = deepcopy(load("simulator_dome_parked_equipment_info.json")["Dome"])
    block["ShutterStatus"] = wire
    assert map_dome(block).shutter_status == expected

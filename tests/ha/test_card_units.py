"""`www/nina-units.js` against core's own unit converters.

A card converts a reading into the unit the integration publishes before it
compares it with a threshold, so every unit Home Assistant can show one of our
sensors in has to come back to that unit as core would convert it.
`convert_units.mjs` runs the shipped module under node; a Python copy of the
table would only prove itself right.
"""

from collections.abc import Sequence
import json
from pathlib import Path

from homeassistant.components.sensor.const import DEVICE_CLASS_UNITS, UNIT_CONVERTERS
from homeassistant.const import UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureDeltaConverter
import pytest

from custom_components.nina_astrophotography.sensor import (
    DESCRIPTIONS,
    WEATHER_CHANNELS,
)
from helpers import needs_node, run_node

DRIVER = Path(__file__).parent / "convert_units.mjs"

pytestmark = needs_node

VALUES = (0.5, 3.0, 250.75)

# Each convertible device class a sensor of ours has, with the unit it is
# published in. The number platform's one conversion is the temperature setpoint,
# in °C, which the sensors already cover.
CONVERTIBLE = sorted(
    {
        (device_class, description.native_unit_of_measurement)
        for description in DESCRIPTIONS + WEATHER_CHANNELS
        if (device_class := description.device_class) is not None
        and device_class in UNIT_CONVERTERS
    }
)


def _run(cases: Sequence[Sequence[object]]) -> list[object]:
    return run_node(DRIVER, cases)


def test_every_unit_core_can_show_converts_back_as_core_does() -> None:
    cases = [
        (device_class, value, str(unit), native)
        for device_class, native in CONVERTIBLE
        for unit in sorted(DEVICE_CLASS_UNITS[device_class], key=str)
        for value in VALUES
    ]
    converted = _run(
        [["convert", value, unit, native] for _, value, unit, native in cases]
    )

    assert converted == [
        pytest.approx(UNIT_CONVERTERS[device_class].convert(value, unit, native))
        for device_class, value, unit, native in cases
    ]


def test_a_temperature_difference_converts_as_an_interval() -> None:
    units = sorted(UnitOfTemperature, key=str)
    shown = _run([["interval", 3.0, UnitOfTemperature.CELSIUS, unit] for unit in units])

    assert shown == [
        pytest.approx(
            TemperatureDeltaConverter.convert(3.0, UnitOfTemperature.CELSIUS, unit)
        )
        for unit in units
    ]


def test_units_that_measure_different_things_do_not_convert() -> None:
    cases: list[list[str | float | None]] = [
        ["convert", 3.0, "m/s", "mm/h"],
        ["convert", 3.0, "°C", "s"],
    ]
    assert _run(cases) == [None] * len(cases)


FLIP = "sensor.n_i_n_a_mount_time_to_meridian_flip"
CARD_STATES = json.loads(
    (Path(__file__).parent / "snapshots" / "card_states.json").read_text(
        encoding="utf-8"
    )
)


def _flip_hass(dump: str, state: str, unit: str = "min") -> dict[str, object]:
    """The captured flip row, with only its reading and unit changed: a card
    reads `flip_fires_at_minutes` as the sensor publishes it.
    """
    row = CARD_STATES[dump]["states"][FLIP]
    attributes = {**row["attributes"], "unit_of_measurement": unit}
    return {"states": {FLIP: {"state": state, "attributes": attributes}}}


@pytest.mark.parametrize(
    ("dump", "state", "unit", "window"),
    [
        # A profile with Min 5 and Max 15: the window is ten minutes wide.
        ("site_configured", "22", "min", {"earliest": 12, "latest": 22}),
        ("site_configured", "6", "min", {"earliest": 0, "latest": 6}),
        ("site_configured", "0.5", "h", {"earliest": 20, "latest": 30}),
        # The profile not read yet: the countdown is all there is.
        ("dawn_flats", "22", "min", {"earliest": 22, "latest": 22}),
        ("site_configured", "unknown", "min", None),
    ],
)
def test_the_flip_window_runs_from_the_earliest_slew_to_the_countdown(
    dump: str, state: str, unit: str, window: dict[str, float] | None
) -> None:
    assert _run([["flipWindow", _flip_hass(dump, state, unit), FLIP]]) == [
        None if window is None else pytest.approx(window)
    ]


@pytest.mark.parametrize(
    ("earliest", "latest", "shown"),
    [(12.4, 22.4, "12–22"), (0, 6, "≤ 6"), (22.2, 22.4, "22"), (0, 0.2, "0")],
)
def test_a_flip_window_prints_in_whole_minutes(
    earliest: float, latest: float, shown: str
) -> None:
    assert _run([["flipRange", {"earliest": earliest, "latest": latest}]]) == [shown]


@pytest.mark.parametrize(
    ("earliest", "latest", "soon"),
    [(10, 20, True), (15, 25, False), (0, 6, True), (0, 0, False), (14.9, 14.9, True)],
)
def test_a_flip_is_soon_inside_fifteen_minutes_of_the_earliest_slew(
    earliest: float, latest: float, soon: bool
) -> None:
    assert _run([["flipSoon", {"earliest": earliest, "latest": latest}]]) == [soon]


def test_no_flip_window_is_never_soon() -> None:
    assert _run([["flipSoon", None]]) == [False]

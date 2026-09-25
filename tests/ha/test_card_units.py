"""`www/nina-units.js` against core's own unit converters.

A card converts a reading into the unit the integration publishes before it
compares it with a threshold, so every unit Home Assistant can show one of our
sensors in has to come back to that unit as core would convert it.
`convert_units.mjs` runs the shipped module under node; a Python copy of the
table would only prove itself right.
"""

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


def _run(cases: list[list[str | float | None]]) -> list[float | None]:
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

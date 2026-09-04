"""Guards the field names the last-image sensors read out of a frame.

A name that is not in the payload resolves to None, and the sensor sits at
`unknown` forever with nothing logged — `DetectedStars` did exactly that. The
API renames the field on its way out: upstream assigns
`Stars = e.StarDetectionAnalysis.DetectedStars`, so the NINA-side name is the
tempting wrong answer.

A source check, because sensor.py imports Home Assistant and this suite
deliberately does not. Its scope is sensor.py and calls that go through
_latest_stat: frame_statistics.py reads the same vocabulary out of the
WebSocket payload, which is a different shape and is covered behaviourally.
"""
from __future__ import annotations

import ast
from pathlib import Path

SENSOR = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "nina_astrophotography"
    / "sensor.py"
)

# Every key of an /image-history frame, from a captured session.
FRAME_FIELDS = {
    "CameraName", "Date", "ExposureTime", "Filename", "Filter", "FocalLength",
    "Gain", "HFR", "HFRStDev", "ImageType", "IsBayered", "Max", "Mean",
    "Median", "Min", "Offset", "RmsText", "StDev", "Stars", "TargetName",
    "TelescopeName", "Temperature",
}


def _stat_field_args() -> list[ast.expr]:
    """The field-name argument of every _latest_stat call, as AST nodes.

    Parsed rather than pattern-matched: parsing never runs the module, so the
    Home Assistant imports are irrelevant, and it is not fooled by quoting,
    line wrapping, a trailing comma, or a keyword argument.
    """
    tree = ast.parse(SENSOR.read_text(encoding="utf-8"))
    args = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "_latest_stat":
            continue
        positional = node.args[1:2]
        keyword = [kw.value for kw in node.keywords if kw.arg == "stat_key"]
        args.extend(positional or keyword)
    return args


def test_every_frame_field_read_by_a_sensor_exists() -> None:
    args = _stat_field_args()
    assert args, "no _latest_stat calls found — has the helper been renamed?"

    for arg in args:
        assert isinstance(arg, ast.Constant), (
            f"line {arg.lineno}: field name is not a literal, so it cannot be checked"
        )
        assert arg.value in FRAME_FIELDS, (
            f"line {arg.lineno}: no such field on an image-history frame: {arg.value!r}"
        )


def test_the_newest_frame_is_read_from_the_end_of_the_history() -> None:
    """/image-history is oldest-first, so index 0 is the first frame of the night.

    Reverting to it pins every last-image sensor to that frame for the rest of
    the session — a plausible number that never moves, which is worse than the
    empty sensor this fixes.
    """
    src = SENSOR.read_text(encoding="utf-8")
    offenders = [
        f"line {n}: {line.strip()}"
        for n, line in enumerate(src.splitlines(), 1)
        if "history[0]" in line
    ]

    assert not offenders, "\n".join(offenders)
    assert "history[-1]" in src, "the newest-frame read is gone entirely"

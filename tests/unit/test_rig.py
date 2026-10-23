"""The test VM's lifecycle decisions: when the base image is too old, and what
it downloads.
"""

from datetime import date, timedelta
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "windows-rig"))
import rig

BUILT = date(2026, 10, 21)


@pytest.mark.parametrize(
    ("age", "refuse"),
    [(0, None), (79, None), (80, False), (89, False), (90, True), (200, True)],
)
def test_the_base_image_ages_out_with_its_evaluation(
    age: int, refuse: bool | None
) -> None:
    verdict = rig.age_verdict(BUILT, BUILT + timedelta(days=age))

    assert (verdict and verdict[0]) == refuse


def _pins() -> list[object]:
    downloads = json.loads((rig.HERE / "provision" / "downloads.json").read_text())
    stable = rig._channels()["stable"]
    pins = [
        *(
            (f"{name} {pin.get('arch', '')}", pin)
            for name, entry in downloads.items()
            for pin in (entry if isinstance(entry, list) else [entry])
        ),
        ("stable N.I.N.A.", stable["nina"]),
        *((f"stable {pin['name']}", pin) for pin in stable["plugin"]),
    ]
    return [pytest.param(pin, id=name.strip()) for name, pin in pins]


@pytest.mark.parametrize("pin", _pins())
def test_every_pinned_download_names_its_sha256(pin: dict[str, str]) -> None:
    assert re.fullmatch(r"[0-9A-Fa-f]{64}", pin["sha256"])
    assert pin["url"].startswith("https://")

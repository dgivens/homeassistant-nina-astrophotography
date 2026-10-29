"""The floors script fails on a breach and on an unmeasured file."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import coverage_floors

PREFIX = coverage_floors.PREFIX

# The tests supply their own floors rather than asserting against the shipped
# set, which is a release decision rather than a property of the script.
FLOORS = {"derive.py": 95, "session.py": 95, "api/v2/mapper.py": 90}


def _report(tmp_path: Path, files: dict[str, float]) -> None:
    (tmp_path / "coverage.json").write_text(
        json.dumps(
            {
                "files": {
                    PREFIX + name: {"summary": {"percent_covered": pct}}
                    for name, pct in files.items()
                }
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("measured", "exit_code"),
    [
        ({"derive.py": 96.0, "session.py": 95.0, "api/v2/mapper.py": 90.0}, 0),
        ({"derive.py": 94.9, "session.py": 95.0, "api/v2/mapper.py": 90.0}, 1),
        # An unenforced floor is worse than no floor.
        ({"derive.py": 96.0, "session.py": 95.0}, 1),
    ],
    ids=["met", "breached", "unmeasured"],
)
def test_the_floors_fail_on_a_breach_and_on_an_unmeasured_file(
    tmp_path, monkeypatch, measured: dict[str, float], exit_code: int
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coverage_floors, "FLOORS", FLOORS)
    _report(tmp_path, measured)
    assert coverage_floors.main() == exit_code

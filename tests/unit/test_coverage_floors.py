"""The floors script fails on a breach and on an unmeasured file."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import coverage_floors  # noqa: E402

PREFIX = coverage_floors.PREFIX

# The script ships with FLOORS empty until each module lands, so the tests
# supply their own set rather than depending on how far the stack has got.
FLOORS = {"derive.py": 95, "session.py": 95, "api/v2/mapper.py": 90}


def _report(tmp_path: Path, files: dict[str, float]) -> None:
    (tmp_path / "coverage.json").write_text(json.dumps({
        "files": {PREFIX + name: {"summary": {"percent_covered": pct}}
                  for name, pct in files.items()}
    }), encoding="utf-8")


def test_a_met_floor_passes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coverage_floors, "FLOORS", FLOORS)
    _report(tmp_path, {"derive.py": 96.0, "session.py": 95.0,
                       "api/v2/mapper.py": 90.0})
    assert coverage_floors.main() == 0


def test_a_breached_floor_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coverage_floors, "FLOORS", FLOORS)
    _report(tmp_path, {"derive.py": 94.9, "session.py": 95.0,
                       "api/v2/mapper.py": 90.0})
    assert coverage_floors.main() == 1


def test_an_unmeasured_file_fails_rather_than_passing_silently(
    tmp_path, monkeypatch
) -> None:
    """An unenforced floor is worse than no floor."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(coverage_floors, "FLOORS", FLOORS)
    _report(tmp_path, {"derive.py": 96.0, "session.py": 95.0})
    assert coverage_floors.main() == 1

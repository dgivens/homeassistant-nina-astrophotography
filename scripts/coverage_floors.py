#!/usr/bin/env python3
"""Enforce per-file coverage floors.

coverage.py has no per-file threshold and this project has no global gate:
coverage is deliberately uneven. Reads coverage.json, written by
`coverage json` after `coverage combine`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

FLOORS: dict[str, int] = {
    "derive.py": 95,
    "session.py": 95,
    "api/v2/mapper.py": 90,
}

# A floor lives here until the PR that creates its module promotes it into
# FLOORS — A11 the mapper, A12 derive, A13 session, B7 the config flow. That
# keeps this job green on every PR in the stack while never leaving a floor
# silently unenforced for a module that exists. Printed as a warning, never a
# failure. D5 asserts PENDING is empty.
PENDING = {"config_flow.py": 100}

PREFIX = "custom_components/nina_astrophotography/"


def main() -> int:
    report = json.loads(Path("coverage.json").read_text(encoding="utf-8"))
    files = report["files"]
    failures = []
    for relative, floor in FLOORS.items():
        key = PREFIX + relative
        if key not in files:
            failures.append(f"{relative}: not measured — the floor is unenforced")
            continue
        actual = files[key]["summary"]["percent_covered"]
        if actual + 1e-9 < floor:
            failures.append(f"{relative}: {actual:.1f}% < {floor}%")
    for relative, floor in PENDING.items():
        print(f"coverage floor pending (not enforced): {relative} >= {floor}%",
              file=sys.stderr)
    for line in failures:
        print(f"coverage floor breached: {line}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

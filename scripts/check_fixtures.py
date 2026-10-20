#!/usr/bin/env python3
"""Fail the commit if any staged fixture still holds sensitive data.

CI is the backstop, not the guard: it fires after the push, by which time a
leaked credential is permanent.
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from redaction import read_fixture, rig_value_kept, scan


def main(paths: list[str]) -> int:
    failures = 0
    for name in paths:
        path = Path(name)
        # The test VM loads what is in tests/fixtures/rig/ as it is.
        kept = rig_value_kept if path.parent.name == "rig" else None
        findings = scan(read_fixture(path), kept=kept)
        if findings:
            print(f"{name}: unredacted {findings}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

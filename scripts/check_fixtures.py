#!/usr/bin/env python3
"""Fail the commit if any staged fixture still holds sensitive data.

CI is the backstop, not the guard: it fires after the push, by which time a
leaked credential is permanent.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from redaction import scan  # noqa: E402


def main(paths: list[str]) -> int:
    failures = 0
    for name in paths:
        findings = scan(json.loads(Path(name).read_text(encoding="utf-8")))
        if findings:
            print(f"{name}: unredacted {findings}", file=sys.stderr)
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

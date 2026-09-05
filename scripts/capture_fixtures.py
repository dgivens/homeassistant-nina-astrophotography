#!/usr/bin/env python3
"""Capture N.I.N.A. Advanced API fixtures from a live rig, redacted.

    scripts/capture_fixtures.py --host H --port 1888 --state <slug> [--dry-run]
      → tests/fixtures/<state-slug>_<endpoint-slug>.json, the raw envelope
      → re-running against an unchanged rig produces a byte-identical file

READ-ONLY. Every endpoint below reports state. NEVER add one that commands
equipment — slew, capture, park, home, connect, disconnect, guider, filter
change, focuser move, flat light, dome, sequence start/stop, profile switch. A
rig may be imaging, and a wasted night is not recoverable. If you are unsure
whether a call mutates state, do not make it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from redaction import PROFILE_ALLOWLIST, project, redact, scan  # noqa: E402

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# (endpoint slug, path, params). Read-only, all of them.
ENDPOINTS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("version", "/version", {}),
    ("nina_version", "/version/nina", {}),
    ("application_start", "/application-start", {}),
    ("equipment_info", "/equipment/info", {}),
    ("sequence_json", "/sequence/json", {}),
    ("sequence_state", "/sequence/state", {}),
    ("image_history_count", "/image-history", {"count": "true"}),
    ("image_history_all", "/image-history", {"all": "true"}),
    ("image_history_latest", "/image-history", {}),
    ("event_history", "/event-history", {}),
    ("flats_status", "/flats/status", {}),
    ("livestack_status", "/livestack/status", {}),
    ("last_af", "/equipment/focuser/last-af", {}),
    ("profile", "/profile/show", {"active": "true"}),
)


def _as_envelope(slug: str, body: str) -> dict:
    """The decoded envelope, or the raw body recorded as one.

    The sequence-serialization failure answers an empty body with no envelope.
    That is a state worth keeping, not a reason to abandon the other endpoints.
    """
    try:
        envelope = json.loads(body)
    except ValueError:
        envelope = None
    if isinstance(envelope, dict):
        return envelope
    print(f"warning: {slug} answered no JSON envelope ({len(body)} B); "
          "recording the raw body", file=sys.stderr)
    return {"_raw": body}


def _serialize(envelope: dict, target: Path) -> str:
    """The file body, keeping the existing `_meta` when nothing else changed.

    That is what makes a re-capture against an unchanged rig byte-identical, so
    a capture run produces no diff of timestamps alone.
    """
    if target.exists():
        previous = json.loads(target.read_text(encoding="utf-8"))
        previous_meta = previous.pop("_meta", None)
        if previous == {k: v for k, v in envelope.items() if k != "_meta"}:
            envelope["_meta"] = previous_meta
    return json.dumps(envelope, indent=2, sort_keys=False) + "\n"


async def capture(host: str, port: int, state: str, dry_run: bool) -> int:
    base = f"http://{host}:{port}/v2/api"
    written = 0
    versions: dict[str, str] = {}
    async with aiohttp.ClientSession() as session:
        for slug, path, params in ENDPOINTS:
            async with session.get(base + path, params=params,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                envelope = _as_envelope(slug, await resp.text())

            if slug == "version":
                versions["api_version"] = str(envelope.get("Response"))
            if slug == "nina_version":
                versions["nina_version"] = str(envelope.get("Response"))
            if slug == "profile":
                envelope["Response"] = project(envelope.get("Response"),
                                               PROFILE_ALLOWLIST)

            envelope = redact(envelope)
            leaks = scan(envelope)
            if leaks:
                print(f"REFUSING to write {slug}: unredacted {leaks}", file=sys.stderr)
                return 1

            envelope["_meta"] = {
                "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "nina_version": versions.get("nina_version", "unknown"),
                "api_version": versions.get("api_version", "unknown"),
                "endpoint": path,
                "params": params,
            }
            target = FIXTURES / f"{state}_{slug}.json"
            body = _serialize(envelope, target)
            if dry_run:
                print(f"would write {target} ({len(body)} B)")
            else:
                target.write_text(body, encoding="utf-8")
                written += 1
    print(f"wrote {written} fixture(s) for state {state!r}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=1888)
    parser.add_argument("--state", required=True, help="state slug, e.g. dawn_flats")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    return asyncio.run(capture(args.host, args.port, args.state, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())

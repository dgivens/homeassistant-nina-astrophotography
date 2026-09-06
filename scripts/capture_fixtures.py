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
from redaction import PROFILE_ALLOWLIST, redact, scan  # noqa: E402

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


def _project(document: object, allowlist: tuple[str, ...]) -> dict:
    """Keep only allowlisted dotted paths. Used for /profile/show only."""
    kept: dict = {}
    for dotted in allowlist:
        node, target = document, kept
        parts = dotted.split(".")
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
            target = target.setdefault(part, {})
        leaf = parts[-1]
        if isinstance(node, dict) and leaf in node:
            target[leaf] = node[leaf]
    return kept


async def capture(host: str, port: int, state: str, dry_run: bool) -> int:
    base = f"http://{host}:{port}/v2/api"
    written = 0
    async with aiohttp.ClientSession() as session:
        versions = {}
        for slug, path, params in ENDPOINTS:
            async with session.get(base + path, params=params,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                envelope = await resp.json(content_type=None)

            if slug == "version":
                versions["api_version"] = str(envelope.get("Response"))
            if slug == "nina_version":
                versions["nina_version"] = str(envelope.get("Response"))
            if slug == "profile":
                envelope["Response"] = _project(envelope.get("Response"),
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
            if target.exists():
                previous = json.loads(target.read_text(encoding="utf-8"))
                previous_meta = previous.pop("_meta", None)
                if previous == {k: v for k, v in envelope.items() if k != "_meta"}:
                    envelope["_meta"] = previous_meta
            body = json.dumps(envelope, indent=2, sort_keys=False) + "\n"
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

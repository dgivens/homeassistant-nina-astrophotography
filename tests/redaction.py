"""Redaction rules for captured fixtures.

Imported by both scripts/capture_fixtures.py and the pre-commit guard so the two
cannot drift. A fixture is committed to a public repository; a profile dump
contains live credentials.

Two rules that are easy to get wrong:

**Redaction preserves the JSON type, containers included.** A string becomes
"REDACTED", a number 0, a null stays null, and a dict stays a dict — otherwise
the type-aware drift guard checks this module's output rather than N.I.N.A.'s,
and a whole settings subtree under a key containing "path" collapses to a
string.

**Site coordinates are kept, deliberately.** The rig is hosted at a public
commercial facility and the owner is content for the repository to show it, so
latitude, longitude, elevation and the pointing fields that reconstruct them
(Altitude at Dec 90, SiderealTime against Coordinates.DateTime.UtcNow) all stay
real. That is not laxity — SiderealTime is the input to the meridian-flip maths
in §11, and zeroing it would leave that formula with no captured fixture to test
against and force a hand-written substitute, which the fixture rules forbid.

Credentials, absolute paths, hostnames, IPv4 addresses, UUIDs and Home Assistant
entity ids are a different matter and are still redacted.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

REDACTED = "REDACTED"

# Substring match on the lowercased key.
_SECRET_KEYS = ("key", "token", "secret", "password", "credential")
_LOCATION_KEYS = ("path", "folder", "directory", "host", "url")

_RENAMED = {"telescopename": "Telescope", "cameraname": "Camera"}
_PSEUDONYM_KEYS = ("deviceid", "entityid")

# Kept deliberately, and asserted by test so a later "tightening" cannot quietly
# break the maths that depends on them:
#   TargetName    an astronomical object, not identifying
#   SideOfPier    not identifying; §11's already-flipped branch needs it
#   site + pointing fields   the site is a public hosting facility, and
#                            SiderealTime is §11's LST input
#   api_version, nina_version   four-part dotted version numbers (.NET's
#                                Major.Minor.Build.Revision) collide with the
#                                bare-IPv4 shape below whenever every segment
#                                is 1-3 digits, e.g. "2.2.15.2"
_KEEP = (
    "targetname", "sideofpier",
    "sitelatitude", "sitelongitude", "siteelevation",
    "latitude", "longitude", "elevation",
    "altitude", "altitudestring", "siderealtime", "siderealtimestring",
    "api_version", "nina_version",
)

_VALUE_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),                                  # Windows path
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),                  # bare IPv4
    re.compile(r"\b[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}\b", re.I),  # UUID
    re.compile(r"\b(?:sensor|binary_sensor|switch|light|number|select|button|"
               r"image|event|camera|climate|cover)\.[a-z0-9_]+\b"),  # HA entity id
)

# Site or facility identifiers seen in device Name/DisplayName/Description.
# Distinctive stems are left unbounded so camel-cased compounds still match
# ("StarfrontObservatory"); short, generic words are word-bounded so they
# don't match as substrings of something else — unbounded "rack" matches the
# sequence node named "Set Tracking", and unbounded "colo" matches
# "Color"/"Colour" (an OSC camera's Name). "coloc" (colocation), not "colo".
_FACILITY = re.compile(
    r"observator|data ?cent|\b(?:building|suite|rack|coloc)\b", re.I
)
_NAME_KEYS = ("name", "displayname", "description")

# /profile/show is captured as an allowlist PROJECTION, not a redaction — its
# secret surface is too large to redact confidently. §8.3.
PROFILE_ALLOWLIST: tuple[str, ...] = (
    "TelescopeSettings.FocalLength",
    "FocuserSettings.AutoFocusTimeoutSeconds",
    "FocuserSettings.RSquaredThreshold",
    "MeridianFlipSettings",
    "CameraSettings.PixelSize",
)


def _digest(value: str, prefix: str, legacy_width: int, suffix: str = "") -> str:
    """A stable pseudonym derived from the value, not from arrival order.

    Order-derived numbering is wrong for Filename: frame identity is
    (Date, Filename) and the fold spans fixtures, so a per-file counter both
    collides distinct frames across files and splits identical ones.

    8 hex digits of the digest (32 bits, ~4.3 billion buckets). A
    positionally-sized decimal form was too narrow: 4 digits is only 10,000
    buckets, so a single 122-frame night collides at roughly 50%; `device-NN`
    at 2 digits (100 buckets) collides even sooner.

    Already-pseudonymised input passes through, in *either* the current 8-hex
    form or the legacy `legacy_width`-digit decimal form the pre-script corpus
    still carries. Without that, hashing is not idempotent — re-redacting an
    already-redacted value yields a different pseudonym — and `scan()`, which
    is a diff against `redact()`, reports every committed fixture as dirty
    forever.
    """
    if re.fullmatch(rf"{re.escape(prefix)}[0-9a-f]{{8}}{re.escape(suffix)}", value):
        return value
    if re.fullmatch(rf"{re.escape(prefix)}\d{{{legacy_width}}}{re.escape(suffix)}", value):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{digest}{suffix}"


def _typed_redaction(value: Any) -> Any:
    """Replace a value while preserving its JSON type, containers included."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return 0
    if isinstance(value, dict):
        return {k: _typed_redaction(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_typed_redaction(v) for v in value]
    return REDACTED


def _redact_scalar(key: str, value: Any) -> Any:
    low = key.lower()
    if low in _KEEP:
        return value
    if low in _RENAMED:
        return _RENAMED[low]
    if low == "filename" and isinstance(value, str):
        return _digest(value, "frame_", 4, ".fits")
    if any(p in low for p in _PSEUDONYM_KEYS) and isinstance(value, str):
        return _digest(value, "device-", 2)
    if any(p in low for p in (*_SECRET_KEYS, *_LOCATION_KEYS)):
        return _typed_redaction(value)
    if low in _NAME_KEYS and isinstance(value, str) and _FACILITY.search(value):
        return REDACTED
    if isinstance(value, str) and any(p.search(value) for p in _VALUE_PATTERNS):
        return REDACTED
    return value


def _walk(key: str, value: Any) -> Any:
    """Redact by key at every depth.

    The key travels with the recursion so a container is redacted as a
    container; applying _redact_scalar to a dict is what flattens a settings
    subtree into the string "REDACTED".
    """
    replaced = _redact_scalar(key, value)
    if replaced is not value:
        return replaced
    if isinstance(value, dict):
        return {k: _walk(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(key, item) for item in value]
    return value


def redact(value: Any) -> Any:
    """Recursively redact a decoded JSON document. Idempotent."""
    return _walk("", value)


def scan(value: Any) -> list[str]:
    """Dotted paths redact() would still change. Empty means clean.

    Expressed as a diff against redact() rather than as a second rule set: that
    is the documented contract, it needs no "already redacted" escape hatch, and
    the two can never disagree. It relies on redact() being idempotent, which
    every rule above is — a digest of a digest is stable because the digest
    forms are themselves kept by their key rules.
    """
    return _differing_paths(value, redact(value))


def _differing_paths(before: Any, after: Any, prefix: str = "") -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        return [path for key in before
                for path in _differing_paths(before[key], after.get(key),
                                             f"{prefix}.{key}" if prefix else key)]
    if isinstance(before, list) and isinstance(after, list):
        return [path for index, item in enumerate(before)
                for path in _differing_paths(item, after[index],
                                             f"{prefix}[{index}]")]
    return [] if before == after else [prefix]

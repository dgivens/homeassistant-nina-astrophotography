"""Redaction rules for captured fixtures, shared by
`scripts/capture_fixtures.py` and the pre-commit guard so the two cannot drift.

**Redaction preserves the JSON type, containers included**: a string becomes
`"REDACTED"`, a number 0, a null stays null, a dict stays a dict — otherwise
the drift guard checks this module's output rather than N.I.N.A.'s.

**Site coordinates are kept.** The rig is hosted at a public facility, and
`SiderealTime` is the meridian-flip maths' input; zeroing it would leave that
formula with no fixture to test against.
"""

from collections.abc import Callable
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET

REDACTED = "REDACTED"

# Substring match on the lowercased key.
_SECRET_KEYS = ("key", "token", "secret", "password", "credential", "email")
_LOCATION_KEYS = (
    "path",
    "folder",
    "directory",
    "host",
    "url",
    "address",
    "machinename",
)
# Whole camel-case words only: "Focuser" and "PauseRequested" both contain
# "user" as a substring, and "AutoFocuserName" spells "username" across the
# seam between "AutoFocuser" and "Name" — a substring rule zeroes the Focuser
# block and the autofocuser's name, neither of which is an account.
_WORD_KEYS = ("user", "username")
_CAMEL_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")

_RENAMED = {"telescopename": "Telescope", "cameraname": "Camera"}
_PSEUDONYM_KEYS = ("deviceid", "entityid")

# Kept deliberately, and asserted by test so a later "tightening" cannot quietly
# break the maths that depends on them:
#   TargetName    an astronomical object, not identifying
#   SideOfPier    not identifying; §11's +12 h windows turn on it
#   site + pointing fields   the site is a public hosting facility, and
#                            SiderealTime is §11's LST input
#   api_version, nina_version   four-part dotted version numbers (.NET's
#                                Major.Minor.Build.Revision) collide with the
#                                bare-IPv4 shape below whenever every segment
#                                is 1-3 digits, e.g. "2.2.15.2"
_KEEP = (
    "targetname",
    "sideofpier",
    "sitelatitude",
    "sitelongitude",
    "siteelevation",
    "latitude",
    "longitude",
    "elevation",
    "altitude",
    "altitudestring",
    "siderealtime",
    "siderealtimestring",
    "api_version",
    "nina_version",
)

_VALUE_PATTERNS = (
    re.compile(r"[A-Za-z]:\\"),  # Windows path
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"),  # bare IPv4
    # IPv6: eight hex groups, or a "::" compression. Timestamps ("21:26:56")
    # and RmsText carry one or two colons and must not match.
    re.compile(
        r"(?<![\w:])(?:(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}"
        r"|(?:[0-9a-f]{1,4}:){1,6}(?::[0-9a-f]{1,4}){1,6}"
        r"|(?:[0-9a-f]{1,4}:){1,7}:|:(?::[0-9a-f]{1,4}){1,7})(?![\w:])",
        re.IGNORECASE,
    ),
    re.compile(r"\.ts\.net\b", re.IGNORECASE),  # Tailscale hostname
    re.compile(
        r"\b[0-9a-f]{8}(?:-?[0-9a-f]{4}){3}-?[0-9a-f]{12}\b", re.IGNORECASE
    ),  # UUID
    re.compile(
        r"\b(?:sensor|binary_sensor|switch|light|number|select|button|"
        r"image|event|camera|climate|cover)\.[a-z0-9_]+\b"
    ),  # HA entity id
)

# Site or facility identifiers, matched two ways: as the whole value of a name
# key (`_NAME_KEYS` below), and as a TOKEN anywhere inside any string value —
# a sequence node's text, a Target Scheduler group label. The token rule
# substitutes rather than replacing the value, because the rest of a sequence
# node's text is the structure the fixtures exist to record.
#
# Distinctive stems are left unbounded so camel-cased compounds still match
# ("StarfrontObservatory"); short, generic words and acronyms are word-bounded
# so they don't match as substrings of something else — unbounded "rack"
# matches the sequence node named "Set Tracking", and unbounded "colo" matches
# "Color"/"Colour" (an OSC camera's Name). "coloc" (colocation), not "colo".
_FACILITY = re.compile(
    r"observator|data ?cent|\b(?:building|suite|rack|coloc|sfro)\b", re.IGNORECASE
)
# `ProjectName` is a Target Scheduler project, which is routinely named after
# the site hosting the rig; `TargetName` stays, being an astronomical object.
_NAME_KEYS = ("name", "displayname", "description", "projectname")

# /profile/show is captured as an allowlist PROJECTION, not a redaction — its
# secret surface is too large to redact confidently. §8.3.
PROFILE_ALLOWLIST: tuple[str, ...] = (
    "TelescopeSettings.FocalLength",
    "FocuserSettings.AutoFocusTimeoutSeconds",
    "FocuserSettings.RSquaredThreshold",
    "MeridianFlipSettings",
    "CameraSettings.PixelSize",
    # The observing site, which is where the rig is rather than where Home
    # Assistant is — the two differ for a hosted rig. Named field by field
    # because the section also holds `HorizonFilePath`.
    "AstrometrySettings.Latitude",
    "AstrometrySettings.Longitude",
    "AstrometrySettings.Elevation",
)


def project(document: object, allowlist: tuple[str, ...]) -> dict:
    """Keep only allowlisted dotted paths; a path naming a section keeps it whole.

    The projection is the capture script's rule for `/profile/show` and lives
    beside the redaction rules so the two cannot drift.
    """
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


def _digest(value: str, prefix: str, legacy_width: int, suffix: str = "") -> str:
    """A stable pseudonym derived from the value, not from arrival order.

    Order-derived numbering is wrong for `Filename`: frame identity is
    `(Date, Filename)` and the fold spans fixtures, so a per-file counter both
    collides distinct frames across files and splits identical ones.

    8 hex digits (32 bits) of the digest; a positional decimal form collided
    too often at the widths tried. Already-pseudonymised input, in the current
    form or the legacy `legacy_width`-digit one, passes through unchanged, or
    `scan()` would report every committed fixture as dirty forever.
    """
    if re.fullmatch(rf"{re.escape(prefix)}[0-9a-f]{{8}}{re.escape(suffix)}", value):
        return value
    if re.fullmatch(
        rf"{re.escape(prefix)}\d{{{legacy_width}}}{re.escape(suffix)}", value
    ):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{digest}{suffix}"


def _typed_redaction(value: Any) -> Any:
    """Replace a value while preserving its JSON type, containers included.

    An empty string is kept: it holds nothing, and a blanked credential is how
    a profile the rig loads carries one.
    """
    if value is None or isinstance(value, bool) or value == "":
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
    if any(word.lower() in _WORD_KEYS for word in _CAMEL_WORDS.findall(key)):
        return _typed_redaction(value)
    if low in _NAME_KEYS and isinstance(value, str) and _FACILITY.search(value):
        return REDACTED
    if isinstance(value, str) and any(p.search(value) for p in _VALUE_PATTERNS):
        return REDACTED
    if isinstance(value, str) and _FACILITY.search(value):
        # Free text under a key no rule names — the token goes, the sentence
        # stays. Idempotent: "REDACTED" carries no facility token itself.
        return _FACILITY.sub(REDACTED, value)
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


def scan(value: Any, kept: Callable[[Any], bool] | None = None) -> list[str]:
    """Dotted paths redact() would still change. Empty means clean.

    Expressed as a diff against redact() rather than as a second rule set: that
    is the documented contract, it needs no "already redacted" escape hatch, and
    the two can never disagree. It relies on redact() being idempotent, which
    every rule above is — a digest of a digest is stable because the digest
    forms are themselves kept by their key rules.

    `kept` exempts values a fixture must hold as they are: `rig_value_kept`
    for the rig's profiles.
    """
    return _differing_paths(value, redact(value), kept or (lambda _: False))


def _differing_paths(
    before: Any, after: Any, kept: Callable[[Any], bool], prefix: str = ""
) -> list[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        return [
            path
            for key in before
            for path in _differing_paths(
                before[key],
                after.get(key),
                kept,
                f"{prefix}.{key}" if prefix else key,
            )
        ]
    if isinstance(before, list) and isinstance(after, list):
        return [
            path
            for index, item in enumerate(before)
            for path in _differing_paths(item, after[index], kept, f"{prefix}[{index}]")
        ]
    return [] if before == after or kept(before) else [prefix]


# The rig's profiles (`tests/fixtures/rig/`) are loaded into the test VM, so
# the values it needs cannot become "REDACTED": a dead path stops the profile
# loading, and a PHD2 host of "REDACTED" stops N.I.N.A. reaching PHD2. Paths
# are normalised under the VM's own `C:\rig\` instead, and the profile's `Id`
# is a GUID minted for the fixture. The hosts are N.I.N.A.'s shipped defaults.
RIG_PATH_PREFIX = "C:\\rig\\"
RIG_PROFILE_ID = "660fe38b-4d3a-458e-b25a-beadb6f9c83c"
# N.I.N.A.'s built-in simulator camera, whose device id is fixed in its source.
NINA_SIMULATOR_CAMERA_ID = "4C0BBF74-0D95-41F6-AAD8-D6D58668CF2C"
_RIG_KEPT = frozenset(
    {
        RIG_PROFILE_ID,
        NINA_SIMULATOR_CAMERA_ID,
        "localhost",
        "nova.astrometry.net",
        "http://nova.astrometry.net",
    }
)


def rig_value_kept(value: Any) -> bool:
    """Whether a rig profile may hold this value as it is."""
    return isinstance(value, str) and (
        value in _RIG_KEPT or value.startswith(RIG_PATH_PREFIX)
    )


def read_fixture(path: Path) -> Any:
    """A fixture decoded into the shape `scan` takes, by its file suffix.

    `.json` is a captured envelope; `.profile` is a N.I.N.A. profile and
    `.xml` an OmniSim device's settings, both XML; `.phdcfg` is PHD2's
    `phd2.exe -s` export, one `key<TAB>type<TAB>value` line per setting under
    a `PHD Config` header. OmniSim writes a byte-order mark.
    """
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix in {".profile", ".xml"}:
        # A profile committed to this repository, not untrusted input.
        return _xml_element(ET.fromstring(text))  # noqa: S314
    if path.suffix == ".phdcfg":
        return _phd2_settings(text)
    return json.loads(text)


def _xml_element(element: ET.Element) -> Any:
    """An element as a dict keyed by local name; repeated children as a list.

    The serializer writes booleans as `true`/`false` text, read back as bools
    so they pass the key rules as JSON's do. Its `i:type` attributes annotate
    a value's type and are not data. A dictionary is written as a run of
    entries, each a `Key` and a `Value` (`KeyValueOf…` from N.I.N.A.,
    `SettingsPair` from OmniSim); it reads back as the dict it was, so the key
    rules see the setting's name, not "Key".
    """
    node: dict[str, Any] = {
        f"@{_local_name(name)}": _xml_text(value)
        for name, value in element.attrib.items()
        if _local_name(name) != "type"
    }
    children = list(element)
    if children and all(_is_entry(child) for child in children):
        entries = (
            {_local_name(part.tag): part for part in child} for child in children
        )
        return {
            str(_xml_element(entry["Key"])): _xml_element(entry["Value"])
            for entry in entries
        }
    if not children:
        text = _xml_text(element.text or "")
        if not node:
            return text
        return node | ({"#text": text} if text != "" else {})
    for child in children:
        name, value = _local_name(child.tag), _xml_element(child)
        if name not in node:
            node[name] = value
        elif isinstance(node[name], list):
            node[name].append(value)
        else:
            node[name] = [node[name], value]
    return node


def _is_entry(element: ET.Element) -> bool:
    name = _local_name(element.tag)
    return name.startswith("KeyValueOf") or name == "SettingsPair"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_text(text: str) -> str | bool:
    return {"true": True, "false": False}.get(text, text)


def _phd2_settings(text: str) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for line in text.splitlines()[1:]:
        key, _kind, value = line.split("\t", 2)
        *parents, leaf = [part for part in key.split("/") if part]
        node = settings
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return settings

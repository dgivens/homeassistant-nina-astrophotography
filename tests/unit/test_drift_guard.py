"""The drift guard — two tests over the whole corpus.

Not one fixture, and the reason is key PRESENCE rather than nullability: a
disconnected device does not null its fields, it drops them. The connected Mount
carries 51 keys and the disconnected one 37 — Coordinates, DeviceId, Name,
DisplayName, TrackingMode, TrackingModes, PrimaryAxisRates and seven more simply
are not there. A single-fixture guard would record whichever half it happened to
read and call the other half drift.

Paths are namespaced by the endpoint each fixture came from, taken from
_meta.endpoint. Without that, the per-device captures contribute bare leaves —
`Connected`, `Name`, `Position` — that collide across devices, and no waiver key
could ever match an observed path.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]
FIXTURES = TESTS / "fixtures"
DEVIATIONS = json.loads((TESTS / "spec_deviations.json").read_text(encoding="utf-8"))

# "NaN" is pre-passed to a sentinel marker so nineteen fields do not register as
# type errors and drown the signal (§8.5).
NAN = "NaN"

# endpoint -> the namespace its Response occupies. /equipment/info is already
# namespaced by its own eleven device keys, so it contributes no prefix.
_NAMESPACE = {
    "/equipment/info": "",
    "/equipment/camera/info": "Camera",
    "/equipment/mount/info": "Mount",
    "/equipment/focuser/info": "Focuser",
    "/equipment/filterwheel/info": "FilterWheel",
    "/equipment/guider/info": "Guider",
    "/equipment/rotator/info": "Rotator",
    "/equipment/dome/info": "Dome",
    "/equipment/flatdevice/info": "FlatDevice",
    "/equipment/weather/info": "WeatherData",
    "/equipment/safetymonitor/info": "SafetyMonitor",
    "/image-history": "ImageStatistics",
    "/event-history": "Event",
    "/sequence/json": "Sequence",
    "/sequence/state": "SequenceState",
    "/flats/status": "FlatsStatus",
    "/livestack/status": "LivestackStatus",
    "/equipment/focuser/last-af": "AutoFocusRun",
    "/application-start": "ApplicationStart",
    "/version": "Version",
    "/profile/show": "Profile",
    # The live IMAGE-SAVE payload already carries ImageStatistics.* under its
    # own key, so it merges into the /image-history namespace deliberately.
    "socket": "",
}


def _type_name(value: object) -> str:
    if value is None:
        return "null"
    if value == NAN:
        return "nan"
    return {bool: "bool", int: "int", float: "float", str: "str",
            dict: "dict", list: "list"}[type(value)]


def _collapse(path: str) -> str:
    """Fold repeated container segments.

    /sequence/json nests Items seven deep and the depth varies with the loaded
    sequence, so an uncollapsed snapshot churns on an unrelated sequence edit.
    Items.Items.Items.Status and Items.Status are the same wire fact.
    """
    parts: list[str] = []
    for segment in path.split("."):
        if not (parts and parts[-1] == segment):
            parts.append(segment)
    return ".".join(parts)


def _observe(document: object, prefix: str = "") -> dict[str, set[str]]:
    """Dotted path -> the set of JSON types seen at it.

    A list ALWAYS records "list" at its own path, empty or not — Camera.Gains
    is always [] and Mount.TrackingModes is a non-empty list of strings, and
    both need the container fact recorded or a waiver naming either reads as
    stale. A dict or list item keeps recursing; a scalar item (Mount.TrackingModes'
    strings) matches neither branch below it, so it is recorded separately at
    a synthetic `<path>[]` leaf rather than silently dropped.
    """
    seen: dict[str, set[str]] = defaultdict(set)
    if isinstance(document, dict):
        if not document and prefix:
            # An empty dict has no leaves, so without this the path vanishes and
            # a waiver naming it reads as stale. Mount.TrackingRate is always {}.
            seen[_collapse(prefix)].add("dict")
        for key, value in document.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                for sub, types_ in _observe(value, path).items():
                    seen[sub] |= types_
            else:
                seen[_collapse(path)].add(_type_name(value))
    elif isinstance(document, list):
        if prefix:
            seen[_collapse(prefix)].add("list")
        for item in document:
            if isinstance(item, (dict, list)):
                for sub, types_ in _observe(item, prefix).items():
                    seen[sub] |= types_
            elif prefix:
                seen[_collapse(f"{prefix}[]")].add(_type_name(item))
    return seen


def _corpus() -> dict[str, set[str]]:
    merged: dict[str, set[str]] = defaultdict(set)
    for path in sorted(FIXTURES.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        # Not every fixture is an envelope: image_history_session.json is a bare
        # JSON list. Guard it, or the whole guard dies on an AttributeError.
        if not isinstance(document, dict):
            continue
        meta = document.pop("_meta", {})              # ours, not N.I.N.A.'s
        endpoint = meta.get("endpoint", "")
        try:
            prefix = _NAMESPACE[endpoint]
        except KeyError:
            raise KeyError(
                f"{path.name}: endpoint {endpoint!r} has no _NAMESPACE entry"
            ) from None
        for dotted, types_ in _observe(document.get("Response"), prefix).items():
            merged[dotted] |= types_
    return merged


def test_a_disconnected_device_drops_keys_rather_than_nulling_them() -> None:
    """The wire fact that makes the whole-corpus rule necessary.

    It is also what makes first-sight device creation derivable: DeviceId and
    Name are present only while a device is connected, so "has ever carried a
    DeviceId" is the observation signal.
    """
    connected = json.loads(
        (FIXTURES / "dawn_equipment_info.json").read_text(encoding="utf-8"))
    disconnected = json.loads(
        (FIXTURES / "restart_equipment_partial_connect.json").read_text(encoding="utf-8"))
    absent = set(connected["Response"]["Mount"]) - set(disconnected["Response"]["Mount"])
    assert {"DeviceId", "Name", "TrackingMode", "TrackingModes"} <= absent


def test_the_corpus_is_actually_being_read() -> None:
    """A guard that collects nothing passes vacuously — every test below would."""
    observed = _corpus()
    assert len(observed) > 100
    assert "FlatDevice.MaxBrightness" in observed


def test_an_always_empty_container_is_still_observed() -> None:
    """Camera.Gains is always [] and Mount.TrackingRate always {} on this build.
    A container with no leaves contributes no path unless recorded explicitly,
    and its waiver then reads as stale."""
    observed = _corpus()
    assert observed["Camera.Gains"] == {"list"}
    assert observed["Mount.TrackingRate"] == {"dict"}


def test_a_scalar_list_item_is_recorded_at_a_bracket_leaf() -> None:
    """A list of scalars (Mount.TrackingModes' strings) matches neither the
    dict nor the list recursion branch, so without a dedicated leaf it is
    silently dropped rather than merely under-typed."""
    assert _observe({"Modes": ["Sidereal", "Lunar"], "Empty": []}, "Mount") == {
        "Mount.Modes": {"list"},
        "Mount.Modes[]": {"str"},
        "Mount.Empty": {"list"},
    }


def test_observed_wire_shape_matches_snapshot(snapshot) -> None:
    """Fires when the WIRE changes — which the spec cannot tell you."""
    shape = {path: "|".join(sorted(types_)) for path, types_ in sorted(_corpus().items())}
    assert shape == snapshot


def test_no_waiver_is_stale() -> None:
    """A waiver naming a path the corpus no longer contains is a lie."""
    observed = set(_corpus())
    stale = [dotted for dotted, entry in DEVIATIONS.items()
             if entry["wire"] != "absent" and dotted not in observed]
    assert not stale, f"waivers that no longer describe the corpus: {stale}"


def test_waivers_state_the_observed_wire_type() -> None:
    """The "deviate only where recorded" check: a waiver's `wire` is exactly the
    type set the corpus shows at that path, so a waiver can neither under- nor
    over-describe the deviation it excuses."""
    observed = _corpus()
    wrong = {dotted: ("|".join(sorted(observed[dotted])), entry["wire"])
             for dotted, entry in DEVIATIONS.items()
             if entry["wire"] != "absent"
             and "|".join(sorted(observed[dotted])) != entry["wire"]}
    assert not wrong, f"waivers whose wire type is not what the corpus shows: {wrong}"


def test_no_field_waived_as_absent_is_present() -> None:
    """ImageStatistics.Index is documented by the spec and on neither path.
    If it ever appears, the waiver must go."""
    observed = set(_corpus())
    present = [dotted for dotted, entry in DEVIATIONS.items()
               if entry["wire"] == "absent" and dotted in observed]
    assert not present, f"fields waived as absent but present on the wire: {present}"

"""Redaction rules — one module, shared by the capture script and the guard."""
from __future__ import annotations

import pytest

from redaction import PROFILE_ALLOWLIST, redact, scan


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"WeatherUndergroundAPIKey": "abc"}, {"WeatherUndergroundAPIKey": "REDACTED"}),
        ({"apikey": "abc"}, {"apikey": "REDACTED"}),
        ({"ImageFilePath": "C:\\Astro"}, {"ImageFilePath": "REDACTED"}),
        ({"Note": "C:\\Users\\dan\\N.I.N.A."}, {"Note": "REDACTED"}),
        ({"Note": "192.168.1.40"}, {"Note": "REDACTED"}),
        ({"Note": "sensor.observatory_roof"}, {"Note": "REDACTED"}),
        # Site and pointing fields are KEPT — see the module docstring.
        ({"SiteLatitude": 41.87}, {"SiteLatitude": 41.87}),
        ({"Altitude": 31.5478}, {"Altitude": 31.5478}),
        ({"SiderealTime": 5.4761}, {"SiderealTime": 5.4761}),
        ({"SideOfPier": "pierEast"}, {"SideOfPier": "pierEast"}),
        ({"TelescopeName": "Esprit 100"}, {"TelescopeName": "Telescope"}),
        ({"TargetName": "NGC 281"}, {"TargetName": "NGC 281"}),
        # "rack" is a substring of a benign sequence node name, not a facility
        # reference — the facility pattern must be word-bounded.
        ({"Name": "Set Tracking"}, {"Name": "Set Tracking"}),
        # "colo" is a substring of an OSC camera's Name, not a facility
        # reference — the facility pattern must not match it unbounded.
        ({"Name": "ASI2600MC Color"}, {"Name": "ASI2600MC Color"}),
        # Distinctive stems stay unbounded so a camel-cased compound with no
        # word boundary still matches.
        ({"Name": "StarfrontObservatory"}, {"Name": "REDACTED"}),
        ({"DisplayName": "Rack 4"}, {"DisplayName": "REDACTED"}),
        # A four-part .NET version string is shaped exactly like a bare IPv4
        # address when every segment is 1-3 digits.
        ({"api_version": "2.2.15.2"}, {"api_version": "2.2.15.2"}),
    ],
)
def test_redacts_by_rule(payload: dict, expected: dict) -> None:
    assert redact(payload) == expected


def test_redaction_preserves_json_type() -> None:
    """A type-aware drift guard must check N.I.N.A.'s output, not the redactor's."""
    assert redact({"LastDownloadTime": 3.0, "ApiKey": None}) == {
        "LastDownloadTime": 3.0,
        "ApiKey": None,
    }


def test_device_ids_become_stable_distinct_pseudonyms() -> None:
    payload = {"a": {"DeviceId": "ASCOM.X"}, "b": {"DeviceId": "ASCOM.Y"},
               "c": {"DeviceId": "ASCOM.X"}}
    out = redact(payload)
    assert out["a"]["DeviceId"] == out["c"]["DeviceId"] != out["b"]["DeviceId"]
    assert out["a"]["DeviceId"].startswith("device-")


def test_filenames_become_stable_pseudonyms_not_positions() -> None:
    frames = [{"Filename": "D:\\a\\M31_001.fits"}, {"Filename": "D:\\a\\M31_002.fits"}]
    out = [f["Filename"] for f in redact(frames)]
    assert out[0] != out[1]
    assert all(name.startswith("frame_") and name.endswith(".fits") for name in out)


def test_legacy_pseudonyms_pass_through_unchanged() -> None:
    """The pre-script corpus used a narrower digest width (4 decimal digits
    for Filename, 2 for DeviceId); still accepted so redact() stays idempotent
    over those already-committed fixtures."""
    assert redact({"Filename": "frame_0121.fits"})["Filename"] == "frame_0121.fits"
    assert redact({"DeviceId": "device-09"})["DeviceId"] == "device-09"


def test_scan_finds_what_redact_would_change() -> None:
    assert scan({"Outer": {"ApiKey": "live"}}) == ["Outer.ApiKey"]


def test_scan_is_clean_after_redaction_by_construction() -> None:
    """redact() is idempotent, so this cannot be satisfied by an escape hatch."""
    assert scan(redact({"Outer": {"ApiKey": "live"}, "DeviceId": "ASCOM.X"})) == []


def test_a_redacted_container_stays_a_container() -> None:
    """Type preservation covers dicts and lists, not only scalars — otherwise a
    dict under a key containing "path" becomes the string "REDACTED"."""
    out = redact({"ImagePathSettings": {"Enabled": True}})
    assert isinstance(out["ImagePathSettings"], dict)


def test_the_meridian_flip_inputs_survive_redaction() -> None:
    """SiderealTime is §11's LST input, and RightAscension its RA.

    A redactor that zeroes either leaves (RA - LST) mod 12 with no captured
    fixture to test against, and the only alternative is a hand-written
    synthetic triple — which the fixture rules forbid.
    """
    mount = {"SiteLatitude": 31.5478, "SiderealTime": 21.021944,
             "RightAscension": 22.071111, "SideOfPier": "pierWest"}
    assert redact(mount) == mount


def test_a_frame_keeps_one_identity_across_files() -> None:
    """Frame identity is (Date, Filename) and the fold spans fixtures, so a
    per-file counter both collides distinct frames and splits identical ones."""
    a = redact({"Filename": "D:\\astro\\M31_014.fits"})
    b = redact({"Other": 1, "Filename": "D:\\astro\\M31_014.fits"})
    c = redact({"Filename": "D:\\astro\\M31_015.fits"})
    assert a["Filename"] == b["Filename"] != c["Filename"]


def test_profile_allowlist_is_the_projection_not_a_denylist() -> None:
    """/profile/show is captured as a projection — its secret surface is too
    large to redact confidently."""
    assert "TelescopeSettings.FocalLength" in PROFILE_ALLOWLIST
    assert "CameraSettings.PixelSize" in PROFILE_ALLOWLIST

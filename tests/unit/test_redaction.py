"""Redaction rules — one module, shared by the capture script and the guard."""

from pathlib import Path

import pytest

from redaction import (
    PROFILE_ALLOWLIST,
    RIG_PROFILE_ID,
    project,
    read_fixture,
    redact,
    rig_value_kept,
    scan,
)


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"WeatherUndergroundAPIKey": "abc"}, {"WeatherUndergroundAPIKey": "REDACTED"}),
        ({"apikey": "abc"}, {"apikey": "REDACTED"}),
        # A blanked credential has nothing left to redact.
        ({"AstrometryAPIKey": ""}, {"AstrometryAPIKey": ""}),
        ({"ImageFilePath": "C:\\Astro"}, {"ImageFilePath": "REDACTED"}),
        ({"Note": "C:\\Users\\dan\\N.I.N.A."}, {"Note": "REDACTED"}),
        ({"Note": "192.168.1.40"}, {"Note": "REDACTED"}),
        ({"Note": "fe80::1c2d:3e4f:5a6b:7c8d"}, {"Note": "REDACTED"}),
        ({"Note": "nina.tail1234.ts.net"}, {"Note": "REDACTED"}),
        ({"Note": "sensor.observatory_roof"}, {"Note": "REDACTED"}),
        ({"UserName": "dan"}, {"UserName": "REDACTED"}),
        ({"User": "dan"}, {"User": "REDACTED"}),
        ({"Email": "dan@example.org"}, {"Email": "REDACTED"}),
        ({"IPAddress": "10.0.0.5"}, {"IPAddress": "REDACTED"}),
        ({"MachineName": "OBS-PC"}, {"MachineName": "REDACTED"}),
        # A timestamp has colons too; only eight groups or a "::" is an IPv6.
        (
            {"Time": "2026-09-03T21:26:56.6584856-05:00"},
            {"Time": "2026-09-03T21:26:56.6584856-05:00"},
        ),
        ({"Username": "dan"}, {"Username": "REDACTED"}),
        # "user" and "username" are whole-word rules: Focuser is a device, not
        # an account, and "AutoFocuserName" spells "username" across the seam
        # between "AutoFocuser" and "Name".
        ({"Focuser": {"Position": 2332}}, {"Focuser": {"Position": 2332}}),
        ({"AutoFocuserName": "Hocus Focus"}, {"AutoFocuserName": "Hocus Focus"}),
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
        # The facility's acronym, word-bounded like any short one, and a
        # Target Scheduler project named after the site that hosts the rig.
        ({"Name": "SFRO Weather Station"}, {"Name": "REDACTED"}),
        ({"ProjectName": "SFRO"}, {"ProjectName": "REDACTED"}),
        ({"ProjectName": "Lobster & Bubble"}, {"ProjectName": "Lobster & Bubble"}),
        # Under a key no rule names, the TOKEN goes and the rest stays: a
        # sequence node's text and a scheduler group label are the structure
        # the fixtures exist to record.
        (
            {"Group": "SFRO / Lobster & Bubble : 2026-09-04 20:51:48"},
            {"Group": "REDACTED / Lobster & Bubble : 2026-09-04 20:51:48"},
        ),
        (
            {"Text": "off as required by SFRO policy"},
            {"Text": "off as required by REDACTED policy"},
        ),
        ({"Text": "off as required by policy"}, {"Text": "off as required by policy"}),
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
    payload = {
        "a": {"DeviceId": "ASCOM.X"},
        "b": {"DeviceId": "ASCOM.Y"},
        "c": {"DeviceId": "ASCOM.X"},
    }
    out = redact(payload)
    assert out["a"]["DeviceId"] == out["c"]["DeviceId"] != out["b"]["DeviceId"]
    assert out["a"]["DeviceId"].startswith("device-")


def test_filenames_become_stable_pseudonyms_derived_from_the_name() -> None:
    """Frame identity is (Date, Filename) and the fold spans fixtures, so a
    per-file counter would both collide distinct frames and split identical
    ones. The pseudonym is a digest of the name: the same name in two files
    is one frame, and two names are two.
    """
    a = redact({"Filename": "D:\\astro\\M31_014.fits"})["Filename"]
    b = redact({"Other": 1, "Filename": "D:\\astro\\M31_014.fits"})["Filename"]
    c = redact({"Filename": "D:\\astro\\M31_015.fits"})["Filename"]
    assert a == b != c
    assert a.startswith("frame_") and a.endswith(".fits")


def test_legacy_pseudonyms_pass_through_unchanged() -> None:
    """The pre-script corpus used a narrower digest width (4 decimal digits
    for Filename, 2 for DeviceId); still accepted so redact() stays idempotent
    over those already-committed fixtures.
    """
    assert redact({"Filename": "frame_0121.fits"})["Filename"] == "frame_0121.fits"
    assert redact({"DeviceId": "device-09"})["DeviceId"] == "device-09"


def test_the_facility_token_rule_is_idempotent() -> None:
    """It substitutes rather than replacing, so it must not match its own
    output — `scan()` is a diff against `redact()` and would otherwise report
    every committed fixture as dirty forever.
    """
    once = redact({"Group": "SFRO / Lobster & Bubble"})
    assert redact(once) == once


def test_scan_finds_what_redact_would_change() -> None:
    assert scan({"Outer": {"ApiKey": "live"}}) == ["Outer.ApiKey"]


def test_scan_is_clean_after_redaction_by_construction() -> None:
    """redact() is idempotent, so this cannot be satisfied by an escape hatch."""
    assert scan(redact({"Outer": {"ApiKey": "live"}, "DeviceId": "ASCOM.X"})) == []


def test_a_redacted_container_stays_a_container() -> None:
    """Type preservation covers dicts and lists, not only scalars — otherwise a
    dict under a key containing "path" becomes the string "REDACTED".
    """
    out = redact({"ImagePathSettings": {"Enabled": True}})
    assert isinstance(out["ImagePathSettings"], dict)


def test_the_meridian_flip_inputs_survive_redaction() -> None:
    """SiderealTime is §11's LST input, and RightAscension its RA.

    A redactor that zeroes either leaves (RA - LST) mod 12 with no captured
    fixture to test against, and the only alternative is a hand-written
    synthetic triple — which the fixture rules forbid.
    """
    mount = {
        "SiteLatitude": 31.5478,
        "SiderealTime": 21.021944,
        "RightAscension": 22.071111,
        "SideOfPier": "pierWest",
    }
    assert redact(mount) == mount


def test_profile_projection_keeps_only_the_allowlist() -> None:
    """/profile/show is captured as a projection, never a redaction — its
    secret surface is too large to redact confidently. A leaf keeps its value,
    a listed section comes through whole, and an unlisted sibling — here the
    key that leaked on a trial capture — is simply not there.
    """
    profile = {
        "TelescopeSettings": {"FocalLength": 500, "Name": "Esprit 100"},
        "CameraSettings": {"PixelSize": 3.76, "Gain": 100},
        "FocuserSettings": {
            "AutoFocusTimeoutSeconds": 600,
            "RSquaredThreshold": 0.9,
            "AutoFocusStepSize": 50,
        },
        "MeridianFlipSettings": {
            "MinutesAfterMeridian": 5,
            "MaxMinutesAfterMeridian": 15,
            "UseSideOfPier": True,
        },
        "WeatherSettings": {"WeatherUndergroundAPIKey": "live"},
        # The site is kept and the path beside it is not, which is why this
        # section is allowlisted field by field rather than whole.
        "AstrometrySettings": {
            "Latitude": 31.5478,
            "Longitude": -110.2977,
            "Elevation": 1509,
            "HorizonFilePath": "C:\\Users\\rig\\horizon.hrz",
        },
    }
    assert project(profile, PROFILE_ALLOWLIST) == {
        "TelescopeSettings": {"FocalLength": 500},
        "CameraSettings": {"PixelSize": 3.76},
        "FocuserSettings": {"AutoFocusTimeoutSeconds": 600, "RSquaredThreshold": 0.9},
        "MeridianFlipSettings": {
            "MinutesAfterMeridian": 5,
            "MaxMinutesAfterMeridian": 15,
            "UseSideOfPier": True,
        },
        "AstrometrySettings": {
            "Latitude": 31.5478,
            "Longitude": -110.2977,
            "Elevation": 1509,
        },
    }


def test_a_nina_profile_reads_as_nested_dicts(tmp_path: Path) -> None:
    fixture = tmp_path / "x.profile"
    fixture.write_text(
        '<Profile xmlns="urn:nina" xmlns:i="urn:i">'
        "<Id>abc</Id><Enabled>false</Enabled><Folder i:nil='true'/>"
        "<Filter>Red</Filter><Filter>Blue</Filter></Profile>",
        encoding="utf-8",
    )
    assert read_fixture(fixture) == {
        "Id": "abc",
        "Enabled": False,
        "Folder": {"@nil": True},
        "Filter": ["Red", "Blue"],
    }


def test_a_serialized_dictionary_reads_as_its_entries(tmp_path: Path) -> None:
    fixture = tmp_path / "x.profile"
    fixture.write_text(
        '<Profile xmlns="urn:nina" xmlns:i="urn:i"><pluginStorage>'
        "<KeyValueOfguidArray><Key>65ca9fd7-8984-4609-b206-86f3f9e8c19d</Key><Value>"
        "<KeyValueOfstringanyType><Key>Type</Key>"
        '<Value i:type="string">SKYSURVEY</Value></KeyValueOfstringanyType>'
        "<KeyValueOfstringanyType><Key>ApiKey</Key>"
        '<Value i:type="string">abc</Value></KeyValueOfstringanyType>'
        "</Value></KeyValueOfguidArray></pluginStorage></Profile>",
        encoding="utf-8",
    )
    storage = read_fixture(fixture)["pluginStorage"]
    assert storage == {
        "65ca9fd7-8984-4609-b206-86f3f9e8c19d": {"Type": "SKYSURVEY", "ApiKey": "abc"}
    }
    assert scan(storage) == ["65ca9fd7-8984-4609-b206-86f3f9e8c19d.ApiKey"]


def test_phd2_settings_read_as_nested_dicts(tmp_path: Path) -> None:
    fixture = tmp_path / "x.phdcfg"
    fixture.write_text(
        "PHD Config 1\n/profile/2/camera/LastMenuchoice\t1\tSimulator\n"
        "/currentProfile\t3\t2\n",
        encoding="utf-8",
    )
    assert read_fixture(fixture) == {
        "profile": {"2": {"camera": {"LastMenuchoice": "Simulator"}}},
        "currentProfile": "2",
    }


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        ("C:\\rig\\images\\", True),
        ("localhost", True),
        (RIG_PROFILE_ID, True),
        ("4C0BBF74-0D95-41F6-AAD8-D6D58668CF2C", True),
        ("C:\\Users\\dan\\Documents\\N.I.N.A", False),
        ("obs-pc.lan", False),
    ],
)
def test_the_rig_fixtures_keep_only_what_the_vm_needs(value: str, kept: bool) -> None:
    assert (scan({"ImagePath": value}, kept=rig_value_kept) == []) is kept

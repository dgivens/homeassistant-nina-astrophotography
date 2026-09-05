"""The mount tracking parameter, which decides whether tracking stops."""
from __future__ import annotations

import pytest

from helpers import FakeSession
from nina_astrophotography.api import NinaApiClient
from nina_astrophotography.const import TrackingMode


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


@pytest.mark.parametrize(
    "enabled,expected",
    [(True, TrackingMode.SIDEREAL), (False, TrackingMode.STOPPED)],
    ids=["start", "stop"],
)
async def test_set_tracking_sends_a_mode_index(enabled, expected):
    """The parameter is `mode`, an int — not the `on` boolean that was sent.

    `on` bound nothing, so mode defaulted to 0 and set_tracking(False) started
    sidereal tracking instead of stopping it. Verified against a live mount.
    """
    session = FakeSession()

    await make_client(session).set_tracking(enabled)

    url, params = session.requests[0]
    assert url.endswith("/equipment/mount/tracking")
    assert params == {"mode": int(expected)}


def test_tracking_labels_match_what_the_mount_reports():
    """The select shows these strings and /equipment/mount/info returns them."""
    assert TrackingMode.SIDEREAL.label == "Sidereal"
    assert TrackingMode.STOPPED.label == "Stopped"

"""The slew coordinates, which decide where the mount points.

N.I.N.A. is inconsistent about RA and this is the one call where it costs
something. `/equipment/mount/info` reports `RightAscension` in hours — 22.07
for 22h04m — and `sensor.mount_ra` carries that through with unit `h`. But
`/equipment/mount/slew` reads `ra` in degrees. Hand it hours and the mount
slews to RA 22.07 degrees, which is 1h28m: the wrong side of the sky, and no
error anywhere, because 22.07 is a perfectly valid RA in degrees.

So the service keeps taking hours, matching its documentation and the sensor
an automation would read a target from, and the conversion happens once, here.
"""
from __future__ import annotations

import pytest

from helpers import FakeSession
from nina_astrophotography.api import NinaApiClient


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


async def test_the_slew_reaches_the_path_the_api_serves():
    """/equipment/mount/slew-to-coordinates-j2000 is not a route on this build."""
    session = FakeSession()

    await make_client(session).slew_mount(ra_hours=5.5755, dec=-5.3911)

    url, _params = session.requests[0]
    assert url.endswith("/equipment/mount/slew")


@pytest.mark.parametrize(
    "ra_hours,ra_degrees",
    [(0.0, 0.0), (5.5755, 83.6325), (12.0, 180.0), (23.9999, 359.9985)],
    ids=["zero", "orion", "twelve-hours", "just-short-of-a-full-turn"],
)
async def test_right_ascension_is_sent_in_degrees(ra_hours, ra_degrees):
    """Sending hours points the mount at a fifteenth of the intended RA."""
    session = FakeSession()

    await make_client(session).slew_mount(ra_hours=ra_hours, dec=-5.3911)

    _url, params = session.requests[0]
    assert params["ra"] == pytest.approx(ra_degrees)


async def test_declination_is_passed_through_unchanged():
    """Dec is already degrees on both sides; converting it too would be worse."""
    session = FakeSession()

    await make_client(session).slew_mount(ra_hours=5.5755, dec=-5.3911)

    _url, params = session.requests[0]
    assert params["dec"] == pytest.approx(-5.3911)

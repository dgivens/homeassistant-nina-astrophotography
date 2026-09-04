"""The guider calibration flag, which decides whether guiding starts at all."""
from __future__ import annotations

import pytest

from helpers import FakeSession
from nina_astrophotography.api import NinaApiClient


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


@pytest.mark.parametrize(
    "force,expected",
    [(True, "true"), (False, "false")],
    ids=["forced", "not-forced"],
)
async def test_start_guiding_sends_the_calibrate_flag(force, expected):
    """The parameter is `calibrate`; `forceCalibration` binds nothing.

    An unbound flag falls back to the API default, so asking for a forced
    calibration would quietly reuse the existing one — which is exactly the
    stale calibration the caller wanted to discard after a meridian flip or a
    change of target.
    """
    session = FakeSession()

    await make_client(session).start_guiding(force_calibration=force)

    _url, params = session.requests[0]
    assert params == {"calibrate": expected}

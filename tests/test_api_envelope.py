"""Envelope checking in the API client.

The Advanced API answers HTTP 200 for every request and reports failure only
in the response body, so `resp.status` alone can never detect a refused
command. Confirmed against a live instance (Advanced API 2.2.15.2):

    GET /image/99999
    HTTP 200
    {"Response":"","Error":"No images available","StatusCode":500,"Success":false}
"""
from __future__ import annotations

import pytest

from helpers import FakeSession, failure, ok
from nina_astrophotography.api import NinaApiClient, NinaApiError


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


async def test_refused_command_raises_with_the_api_error():
    session = FakeSession(default=failure("Dome not connected", 409))

    with pytest.raises(NinaApiError) as excinfo:
        await make_client(session).close_dome()

    message = str(excinfo.value)
    assert "Dome not connected" in message
    assert "409" in message


async def test_successful_command_returns_its_payload():
    session = FakeSession(default=ok({"Temperature": -10.0}))

    result = await make_client(session).get_camera()

    assert result["Response"]["Temperature"] == -10.0


@pytest.mark.parametrize(
    "payload",
    [[1, 2, 3], {"Version": "2.2.15"}],
    ids=["list", "dict-without-success"],
)
async def test_payload_without_an_envelope_passes_through(payload):
    """Only an explicit `Success: false` is a failure; a missing key is not."""
    session = FakeSession(default=payload)

    assert await make_client(session).get_version() == payload


async def test_a_driver_return_value_is_not_an_api_failure():
    """Success false with no error and a 200 code means the command worked.

    Handlers that assign Success from the driver return false on changes that
    succeeded. Treating that as an error made every successful mount tracking
    change raise. Captured from a live rig.
    """
    session = FakeSession(default={
        "Response": "Tracking mode changed",
        "Error": "",
        "StatusCode": 200,
        "Success": False,
    })

    result = await make_client(session).get_camera()

    assert result["Response"] == "Tracking mode changed"


async def test_a_failure_without_a_message_still_raises():
    """An error code with no text is still a failure; don't render "None"."""
    session = FakeSession(default={"Success": False, "Error": "", "StatusCode": 500})

    with pytest.raises(NinaApiError) as excinfo:
        await make_client(session).get_camera()

    assert "unknown error" in str(excinfo.value)


async def test_post_checks_the_envelope_too():
    """No caller uses _post yet, so only a test keeps it honest."""
    session = FakeSession(default=failure("Sequence not running", 409))

    with pytest.raises(NinaApiError, match="Sequence not running"):
        await make_client(session)._post("/sequence/stop")

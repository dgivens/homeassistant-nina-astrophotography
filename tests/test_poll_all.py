"""Tests for failure handling in the bulk poll.

Individual subsystems fail routinely — a rig with no dome must not raise. But
a poll where nothing answered means N.I.N.A. is gone, and that has to reach
the coordinator so entities go unavailable instead of publishing defaults.
"""
from __future__ import annotations

import aiohttp
import pytest

from helpers import FakeResponse, FakeSession, failure, ok
from nina_astrophotography.api import (
    NinaApiClient,
    NinaApiError,
    NinaConnectionError,
    NinaEndpointError,
)


def unreachable() -> aiohttp.ClientError:
    """What a crashed N.I.N.A. actually raises."""
    return aiohttp.ServerDisconnectedError()


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


async def test_one_failing_subsystem_is_tolerated():
    session = FakeSession(
        responses={"/equipment/dome/info": unreachable()},
        default=ok({"Connected": True}),
    )

    result = await make_client(session).poll_all()

    assert result["dome"] == {}
    assert result["camera"]["Response"]["Connected"] is True


async def test_a_refused_subsystem_is_tolerated_too():
    """An error envelope now raises, so it must not fail the whole poll."""
    session = FakeSession(
        responses={"/equipment/dome/info": failure("Dome not connected")},
        default=ok(),
    )

    result = await make_client(session).poll_all()

    assert result["dome"] == {}
    assert result["camera"] != {}


async def test_total_connection_loss_raises():
    session = FakeSession(default=unreachable())

    with pytest.raises(NinaConnectionError):
        await make_client(session).poll_all()


async def test_total_api_failure_raises():
    session = FakeSession(default=failure("boom", 500))

    with pytest.raises(NinaApiError):
        await make_client(session).poll_all()


async def test_a_single_reachable_subsystem_prevents_raising():
    """The boundary: N.I.N.A. is alive, so degrade rather than fail."""
    session = FakeSession(
        responses={"/equipment/camera/info": ok({"Connected": True})},
        default=unreachable(),
    )

    result = await make_client(session).poll_all()

    assert result["camera"]["Response"]["Connected"] is True
    assert result["mount"] == {}


async def test_nothing_served_is_reported_as_an_endpoint_error():
    """All-404 means the wrong API, not equipment that is merely unhappy.

    The coordinator retries an unhappy rig forever, which is right; it should
    not do that for a client asking for paths this build has never served.
    """
    session = FakeSession(default=FakeResponse("<html>404</html>", status=404))

    with pytest.raises(NinaEndpointError):
        await make_client(session).poll_all()

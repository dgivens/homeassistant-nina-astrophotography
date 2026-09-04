"""Transport failures are lost connections, not API errors."""
from __future__ import annotations

import pytest

import asyncio

import aiohttp

from helpers import FakeSession
from nina_astrophotography.api import NinaApiClient, NinaConnectionError


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


@pytest.mark.parametrize(
    "error",
    [aiohttp.ServerDisconnectedError(), aiohttp.ClientOSError(), asyncio.TimeoutError()],
    ids=["disconnected", "os-error", "timeout"],
)
async def test_transport_failures_raise_connection_error(error):
    """Any aiohttp failure is a lost connection, not an API error.

    Only ClientConnectorError and TimeoutError used to be mapped, so a crashed
    N.I.N.A. — which produces ServerDisconnectedError — was reported as an API
    error by poll_all.
    """
    session = FakeSession(default=error)

    with pytest.raises(NinaConnectionError):
        await make_client(session).get_camera()


async def test_the_image_fetch_maps_transport_failures_too():
    """get_image_bytes has its own handler, separate from _get's."""
    session = FakeSession(default=aiohttp.ServerDisconnectedError())

    with pytest.raises(NinaConnectionError):
        await make_client(session).get_image_bytes()

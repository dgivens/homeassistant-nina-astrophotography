"""The image-history endpoint's path and parameters."""
from __future__ import annotations

import pytest

from helpers import FakeSession, ok
from nina_astrophotography.legacy_api import NinaApiClient


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


async def test_image_history_uses_the_documented_path_and_params():
    """/image/history 500s and `count` is a boolean, so both were wrong."""
    session = FakeSession(default=ok([]))

    await make_client(session).get_image_history()

    url, params = session.requests[0]
    assert url.endswith("/image-history")
    assert params == {"all": "true"}

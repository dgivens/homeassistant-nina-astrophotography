"""The image fetch, which returns bytes rather than an envelope."""
from __future__ import annotations

import pytest

from helpers import FakeResponse, FakeSession, failure
from nina_astrophotography.api import NinaApiClient, NinaApiError

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


async def test_the_index_is_a_path_segment_not_a_query_parameter():
    """/image is not a route; the API serves /image/{index}."""
    session = FakeSession(default=FakeResponse(JPEG, content_type="image/jpeg"))

    await make_client(session).get_image_bytes(index=3)

    url, params = session.requests[0]
    assert url.endswith("/image/3")
    assert "index" not in params


async def test_an_image_is_returned_as_bytes():
    session = FakeSession(default=FakeResponse(JPEG, content_type="image/jpeg"))

    assert await make_client(session).get_image_bytes() == JPEG


async def test_a_refusal_raises_instead_of_returning_json_as_image_data():
    """The refusal is HTTP 200 with an envelope, so status alone cannot see it.

    Returned unchecked, ~90 bytes of JSON reach the image entity and get
    cached and served to the frontend as if they were a frame.
    """
    session = FakeSession(
        default=FakeResponse(failure("No images available", 500))
    )

    with pytest.raises(NinaApiError, match="No images available"):
        await make_client(session).get_image_bytes()


async def test_the_stream_url_uses_the_same_path():
    """The Lovelace card builds its own URL and had the same bug."""
    url = await make_client(FakeSession()).get_image_stream_url(index=2)

    assert url.startswith("http://h:1888/v2/api/image/2?")


@pytest.mark.parametrize(
    "stretch,expected",
    [(True, "true"), (False, None)],
    ids=["stretched", "unstretched"],
)
async def test_the_stretch_is_requested_as_autoprepare(stretch, expected):
    """`useAutoStretch` is not a parameter on /image/{index}; `autoPrepare` is.

    An unknown query parameter binds nothing and is not rejected, so the
    request succeeded and returned the unstretched linear frame — which for a
    sub-exposure is very nearly black. The image entity looked broken.
    """
    session = FakeSession(default=FakeResponse(JPEG, content_type="image/jpeg"))

    await make_client(session).get_image_bytes(stretch=stretch)

    _url, params = session.requests[0]
    assert "useAutoStretch" not in params
    assert params.get("autoPrepare") == expected


@pytest.mark.parametrize(
    "stretch,expected",
    [(True, "&autoPrepare=true"), (False, "")],
    ids=["stretched", "unstretched"],
)
async def test_the_stream_url_asks_for_the_same_stretch(stretch, expected):
    """The card and the image entity must not show differently stretched frames."""
    url = await make_client(FakeSession()).get_image_stream_url(stretch=stretch)

    assert "useAutoStretch" not in url
    assert url.endswith(f"/image/0?stream=true&quality=85{expected}")

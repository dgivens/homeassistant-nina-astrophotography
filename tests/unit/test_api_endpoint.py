"""A non-200 means the path is wrong, which retrying cannot fix."""
from __future__ import annotations

import pytest

from helpers import FakeResponse, FakeSession
from nina_astrophotography.legacy_api import (
    NinaApiClient,
    NinaApiError,
    NinaEndpointError,
)

# Abridged from what the live rig returns for an unknown path.
NOT_FOUND_HTML = (
    "<html><head><meta charset=\"utf-8\"><title>404 - Not Found</title></head>"
    "<body><h1>404 - Not Found</h1><p><strong>Exception type:</strong> "
    "EmbedIO.HttpException</body></html>"
)


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


async def test_a_missing_endpoint_raises_endpoint_error():
    """N.I.N.A. answers a wrong path with a non-200 HTML page, not an envelope."""
    session = FakeSession(default=FakeResponse(NOT_FOUND_HTML, status=404))

    with pytest.raises(NinaEndpointError) as excinfo:
        await make_client(session).get_camera()

    assert "404" in str(excinfo.value)


async def test_an_existing_api_error_handler_still_catches_this():
    """Callers that predate NinaEndpointError must keep working unchanged."""
    session = FakeSession(default=FakeResponse(NOT_FOUND_HTML, status=404))

    try:
        await make_client(session).get_camera()
    except NinaApiError as exc:
        assert isinstance(exc, NinaEndpointError)
    else:
        pytest.fail("no error raised")


@pytest.mark.parametrize(
    "status,permanent",
    [(404, True), (405, True), (501, True), (500, False), (503, False)],
    ids=["not-found", "method-not-allowed", "not-implemented", "server-error", "unavailable"],
)
async def test_only_a_missing_path_is_treated_as_permanent(status, permanent):
    """A 5xx is a handler that threw or a server still starting — retryable.

    Classifying it permanent fails the config entry outright, which needs
    manual intervention, so the ambiguous cases stay retryable.
    """
    session = FakeSession(default=FakeResponse("<html>e</html>", status=status))

    with pytest.raises(NinaApiError) as excinfo:
        await make_client(session).get_camera()

    assert isinstance(excinfo.value, NinaEndpointError) is permanent


@pytest.mark.parametrize(
    "body",
    [NOT_FOUND_HTML, "500 - Internal Server Error\n\n  Exception:  Foo\n  at Bar"],
    ids=["embedio-page", "with-line-breaks"],
)
async def test_the_error_body_is_collapsed_into_one_short_line(body):
    """The message is logged verbatim, so it must stay short and single-line.

    The live server's page is a single 454-byte line, so truncation is what
    matters against a real rig; the collapsing guards a proxy or a different
    build that does emit breaks.
    """
    session = FakeSession(default=FakeResponse(body, status=404))

    with pytest.raises(NinaEndpointError) as excinfo:
        await make_client(session).get_camera()

    message = str(excinfo.value)
    assert len(message) < 200
    assert "\n" not in message
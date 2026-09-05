"""Command paths, checked against the Advanced API 2.2.15 specification.

Every one of these was a path this build does not serve, so the command came
back as a 404 HTML page and the equipment never moved. A wrong path is
invisible from the outside — the mount simply carries on doing what it was
already doing — so each corrected path is pinned here against the published
spec rather than left to be rediscovered on a clear night.
"""
from __future__ import annotations

import pytest

from helpers import FakeSession
from nina_astrophotography.legacy_api import NinaApiClient


def make_client(session) -> NinaApiClient:
    return NinaApiClient(host="h", port=1888, api_version="v2", session=session)


@pytest.mark.parametrize(
    "call,path",
    [
        (lambda c: c.abort_capture(), "/equipment/camera/abort-exposure"),
        (lambda c: c.start_guiding(), "/equipment/guider/start"),
        (lambda c: c.stop_guiding(), "/equipment/guider/stop"),
        (lambda c: c.find_home(), "/equipment/mount/home"),
        (lambda c: c.toggle_flat_light(True), "/equipment/flatdevice/set-light"),
    ],
    ids=[
        "abort-capture",
        "start-guiding",
        "stop-guiding",
        "find-home",
        "flat-light",
    ],
)
async def test_the_command_reaches_the_path_the_api_serves(call, path):
    session = FakeSession()

    await call(make_client(session))

    url, _params = session.requests[0]
    assert url.endswith(path)


async def test_the_flat_light_keeps_its_on_parameter():
    """The spec renders this parameter as `true`; the name really is `on`.

    Pinned because the published documentation is misleading here and a
    future reader correcting it to match would break a call that works.
    """
    session = FakeSession()

    await make_client(session).toggle_flat_light(False)

    _url, params = session.requests[0]
    assert params == {"on": "false"}

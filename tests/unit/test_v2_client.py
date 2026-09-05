"""The envelope, not the HTTP status, carries the outcome."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import aiohttp
import pytest
from helpers import FakeResponse, FakeSession, failure, ok

from nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from nina_astrophotography.api.models import Frame, SequenceNode, VersionInfo
from nina_astrophotography.api.v2.client import NinaClientV2

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def envelope(name: str) -> dict:
    """A captured envelope, as the wire sent it."""
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    document.pop("_meta", None)
    return document


def _client(session: FakeSession) -> NinaClientV2:
    return NinaClientV2(host="nina.local", port=1888, session=session)


# ── envelope classification (§3.5, §7.1) ─────────────────────────────────────


async def test_empty_history_is_no_data_not_an_error() -> None:
    """`Index out of range` is what an idle rig answers, every HA start."""
    client = _client(FakeSession({"image-history": failure("Index out of range", 400)}))
    assert await client.get_frames() == []


async def test_uninitialised_sequencer_is_no_data_not_an_error() -> None:
    """A ~7.5 s window at N.I.N.A. startup, on the ordinary startup path."""
    client = _client(FakeSession({"sequence/json": failure("Sequence is not initialized", 409)}))
    assert await client.get_sequence() is None


async def test_uninitialised_sequencer_is_recognised_at_400_too() -> None:
    """Ten guards, two codes for one condition — match on the message (§7.1)."""
    client = _client(FakeSession({"sequence/json": failure("Sequence is not initialized", 400)}))
    assert await client.get_sequence() is None


async def test_a_real_envelope_failure_raises_a_command_error() -> None:
    client = _client(FakeSession({"equipment/info": failure("Camera not connected", 409)}))
    with pytest.raises(NinaCommandError) as caught:
        await client.get_equipment()
    assert caught.value.status_code == 409


async def test_a_command_error_carries_the_envelopes_message() -> None:
    client = _client(FakeSession({"equipment/info": failure("Camera not connected", 409)}))
    with pytest.raises(NinaCommandError) as caught:
        await client.get_equipment()
    assert caught.value.api_error == "Camera not connected"


async def test_success_false_with_no_error_and_200_is_success() -> None:
    """Seven handlers assign Success from a driver boolean (§3.5)."""
    body = {"Response": {"Camera": {"Connected": True}}, "Error": "",
            "StatusCode": 200, "Success": False, "Type": "API"}
    client = _client(FakeSession({"equipment/info": body}))
    assert (await client.get_equipment()).camera.connected is True


async def test_a_zero_length_200_is_unavailable_not_a_crash() -> None:
    """Sequence serialization failure: empty body, no envelope (§3.5)."""
    client = _client(FakeSession({"sequence/json": FakeResponse("", content_type="text/plain")}))
    with pytest.raises(NinaUnavailableError):
        await client.get_sequence()


async def test_a_non_json_200_is_unavailable() -> None:
    client = _client(FakeSession({"sequence/json": FakeResponse("<html>oops</html>",
                                                                content_type="text/html")}))
    with pytest.raises(NinaUnavailableError):
        await client.get_sequence()


async def test_json_without_an_envelope_is_unavailable() -> None:
    client = _client(FakeSession({"equipment/info": {"Camera": {}}}))
    with pytest.raises(NinaUnavailableError):
        await client.get_equipment()


async def test_pre_handler_html_404_is_an_endpoint_error() -> None:
    session = FakeSession({"livestack": FakeResponse("<html>404</html>", status=404,
                                                     content_type="text/html")})
    with pytest.raises(NinaEndpointError):
        await _client(session).get_livestack()


async def test_pre_handler_html_400_is_a_request_error_not_a_transient_one() -> None:
    """A pre-handler 400 is permanent; an envelope 400 may be transient (§7.1)."""
    session = FakeSession({"image-history": FakeResponse("<html>400</html>", status=400,
                                                         content_type="text/html")})
    with pytest.raises(NinaRequestError):
        await _client(session).get_frames()


async def test_pre_handler_5xx_is_unavailable() -> None:
    session = FakeSession({"flats/status": FakeResponse("<html>500</html>", status=500,
                                                        content_type="text/html")})
    with pytest.raises(NinaUnavailableError):
        await _client(session).get_flats()


async def test_envelope_5xx_is_unavailable_and_retryable() -> None:
    client = _client(FakeSession({"equipment/info": failure("Internal error", 500)}))
    with pytest.raises(NinaUnavailableError) as caught:
        await client.get_equipment()
    assert caught.value.retryable is True


async def test_a_dropped_connection_is_a_connection_error() -> None:
    session = FakeSession({"version": aiohttp.ClientError("boom")})
    with pytest.raises(NinaConnectionError):
        await _client(session).get_versions()


async def test_a_timeout_is_a_connection_error() -> None:
    session = FakeSession({"version": asyncio.TimeoutError()})
    with pytest.raises(NinaConnectionError):
        await _client(session).get_versions()


# ── reads return models ──────────────────────────────────────────────────────


async def test_get_versions_yields_both_version_strings() -> None:
    session = FakeSession({"version/nina": ok("3.2.0.9001"), "version": ok("2.2.15.2")})
    assert await _client(session).get_versions() == VersionInfo("2.2.15.2", "3.2.0.9001")


async def test_application_start_is_the_timestamp_string() -> None:
    client = _client(FakeSession({"application-start": envelope("restart_application_start.json")}))
    assert await client.get_application_start() == "2026-09-04T10:58:59.1429105-05:00"


async def test_profile_is_mapped_from_the_active_profile() -> None:
    session = FakeSession({"profile/show": ok({"TelescopeSettings": {"FocalLength": 500}})})
    assert (await _client(session).get_profile()).focal_length == 500
    assert session.requests[-1][1] == {"active": "true"}


async def test_image_history_count_returns_the_scalar() -> None:
    client = _client(FakeSession({"image-history": ok(122)}))
    assert await client.get_image_history_count() == 122


async def test_empty_history_count_is_zero_not_none() -> None:
    """?count=true answers 0 where bare /image-history says Index out of range."""
    client = _client(FakeSession({"image-history": ok(0)}))
    assert await client.get_image_history_count() == 0


async def test_frames_are_mapped_from_the_history_list() -> None:
    wire = envelope("dawn_image_history_with_flats.json")
    frames = await _client(FakeSession({"image-history": wire})).get_frames(include_all=True)
    assert len(frames) == len(wire["Response"])
    assert isinstance(frames[0], Frame)


async def test_a_bare_history_dict_is_one_frame() -> None:
    """Bare /image-history answers the latest frame as a single object."""
    latest = envelope("dawn_image_history_with_flats.json")["Response"][-1]
    frames = await _client(FakeSession({"image-history": ok(latest)})).get_frames()
    assert [frame.filename for frame in frames] == [latest["Filename"]]


async def test_the_sequence_tree_is_mapped() -> None:
    client = _client(FakeSession({"sequence/json": envelope("dawn_sequence_complete.json")}))
    assert isinstance(await client.get_sequence(), SequenceNode)


async def test_events_use_the_offset_cached_from_equipment() -> None:
    """The mount's clock is the only place the API states the rig's UTC offset,
    and the log-scraped ERROR-* times are naive in it (dawn fixture: -5 h)."""
    session = FakeSession({"equipment/info": envelope("dawn_equipment_info.json"),
                           "event-history": envelope("dawn_event_history.json")})
    client = _client(session)
    await client.get_equipment()
    events = await client.get_events()
    error = next(event for event in events if event.name == "ERROR-PLATESOLVE")
    assert error.time.utcoffset() == timedelta(hours=-5)


async def test_an_unmappable_event_is_skipped_not_fatal() -> None:
    wire = ok([{"Event": "GHOST"}, {"Event": "SAFETY-CONNECTED", "Time": "2026-09-03T19:41:28-05:00"}])
    events = await _client(FakeSession({"event-history": wire})).get_events()
    assert [event.name for event in events] == ["SAFETY-CONNECTED"]


# ── request parameters ───────────────────────────────────────────────────────
#
# Request parameter names are verified by live probe and pinned here.
#
# The spec declares set-light's parameter as literally `True`; the wire reads
# `on`. `set-light?True=true` answers Success: true and leaves the panel alone.
# Never generate these from the spec.


async def test_set_flat_light_sends_on_not_True() -> None:
    session = FakeSession()
    await _client(session).set_flat_light(True)
    url, params = session.requests[-1]
    assert "/equipment/flatdevice/set-light" in url
    assert params == {"on": "true"}


async def test_set_flat_brightness_sends_brightness() -> None:
    session = FakeSession()
    await _client(session).set_flat_brightness(2048)
    _, params = session.requests[-1]
    assert params == {"brightness": 2048}


async def test_image_history_all_sends_all_true() -> None:
    """?all=true is the only reseed source; bare /image-history returns one frame."""
    session = FakeSession({"image-history": ok([])})
    await _client(session).get_frames(include_all=True)
    _, params = session.requests[-1]
    assert params == {"all": "true"}


async def test_the_image_endpoint_sends_autoPrepare_not_useAutoStretch() -> None:
    """An unknown parameter binds nothing and is not rejected, so the request
    succeeds and quietly returns the linear frame."""
    session = FakeSession({"/image/": FakeResponse(b"\xff\xd8", content_type="image/jpeg")})
    await _client(session).get_image_bytes(0)
    _, params = session.requests[-1]
    assert params["autoPrepare"] == "true"
    assert "useAutoStretch" not in params


async def test_an_image_arrives_as_bytes() -> None:
    session = FakeSession({"/image/": FakeResponse(b"\xff\xd8", content_type="image/jpeg")})
    assert await _client(session).get_image_bytes(0) == b"\xff\xd8"


async def test_an_image_refusal_arrives_as_a_json_envelope() -> None:
    """With stream=true a refusal is still HTTP 200, carrying the envelope."""
    session = FakeSession({"/image/": failure("No image at index", 400)})
    with pytest.raises(NinaCommandError):
        await _client(session).get_image_bytes(0)


@pytest.mark.parametrize(
    ("response", "error"),
    [
        (ok({}), NinaUnavailableError),  # a success envelope is still not an image
        (FakeResponse("<html>404</html>", status=404, content_type="text/html"),
         NinaEndpointError),
        (asyncio.TimeoutError(), NinaConnectionError),
        (aiohttp.ClientError("boom"), NinaConnectionError),
    ],
    ids=["no-image", "pre-handler-404", "timeout", "dropped"],
)
async def test_the_image_endpoint_classifies_its_own_failures(response, error) -> None:
    """Images bypass _get for the byte stream, so the same taxonomy is pinned again."""
    with pytest.raises(error):
        await _client(FakeSession({"/image/": response})).get_image_bytes(0)

"""The envelope, not the HTTP status, carries the outcome."""
from __future__ import annotations

from datetime import timedelta

import aiohttp
import pytest
from helpers import FakeResponse, FakeSession, failure, load_envelope, ok

from nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaRequestError,
    NinaUnavailableError,
)
from nina_astrophotography.api.models import Frame, SequenceNode, VersionInfo
from nina_astrophotography.api.v2.client import NinaClientV2


def _client(session: FakeSession) -> NinaClientV2:
    return NinaClientV2(host="nina.local", port=1888, session=session)


# ── envelope classification (§3.5, §7.1) ─────────────────────────────────────


async def test_empty_history_is_no_data_not_an_error() -> None:
    """`Index out of range` is what an idle rig answers, every HA start."""
    client = _client(FakeSession({"image-history": failure("Index out of range", 400)}))
    assert await client.get_frames() == []


@pytest.mark.parametrize("status", [409, 400])
async def test_uninitialised_sequencer_is_no_data_not_an_error(status) -> None:
    """A ~7.5 s window at N.I.N.A. startup, on the ordinary startup path. Ten
    guards raise it, with 409 on some paths and 400 on others — match on the
    message, not the code (§7.1)."""
    client = _client(FakeSession({"sequence/json": failure("Sequence is not initialized", status)}))
    assert await client.get_sequence() is None


async def test_a_5xx_carrying_the_no_data_text_is_still_unavailable() -> None:
    """The code outranks the message: a handler exception is not "no data yet"."""
    client = _client(FakeSession({"sequence/json": failure("Sequence is not initialized", 500)}))
    with pytest.raises(NinaUnavailableError):
        await client.get_sequence()


async def test_a_device_refusal_worded_not_initialized_is_a_command_error() -> None:
    """Only the sequencer's message means "no data"; a refusal on a command path
    keeps raising."""
    client = _client(FakeSession({"set-light": failure("Flat device is not initialized", 409)}))
    with pytest.raises(NinaCommandError):
        await client.set_flat_light(True)


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [("status_code", 409), ("api_error", "Camera not connected")],
)
async def test_a_command_error_carries_the_envelopes_code_and_message(attribute, expected) -> None:
    client = _client(FakeSession({"equipment/info": failure("Camera not connected", 409)}))
    with pytest.raises(NinaCommandError) as caught:
        await client.get_equipment()
    assert getattr(caught.value, attribute) == expected


@pytest.mark.synthetic
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


@pytest.mark.parametrize(
    ("status", "error"),
    [(404, NinaEndpointError), (400, NinaRequestError), (500, NinaUnavailableError)],
    ids=["not-served", "bad-request", "server-error"],
)
async def test_a_pre_handler_html_status_is_classified_by_its_code(status, error) -> None:
    """EmbedIO answers routing and binding failures itself, with HTML and a
    real status. A pre-handler 400 is permanent where an envelope 400 may be
    transient (§7.1); a 404 says the path is not served by this build."""
    session = FakeSession({"flats/status": FakeResponse(f"<html>{status}</html>",
                                                        status=status, content_type="text/html")})
    with pytest.raises(error):
        await _client(session).get_flats()


async def test_envelope_5xx_is_unavailable_and_retryable() -> None:
    client = _client(FakeSession({"equipment/info": failure("Internal error", 500)}))
    with pytest.raises(NinaUnavailableError) as caught:
        await client.get_equipment()
    assert caught.value.retryable is True


@pytest.mark.parametrize("exc", [aiohttp.ClientError("boom"), TimeoutError()],
                         ids=["dropped", "timeout"])
async def test_a_transport_failure_is_a_connection_error(exc) -> None:
    session = FakeSession({"version": exc})
    with pytest.raises(NinaConnectionError):
        await _client(session).get_versions()


# ── reads return models ──────────────────────────────────────────────────────

# EmbedIO's own 404 page: a path this build does not route at all.
NOT_ROUTED = FakeResponse("<html>404</html>", status=404, content_type="text/html")


async def test_get_versions_yields_both_version_strings() -> None:
    session = FakeSession({"version/nina": ok("3.2.0.9001"), "version": ok("2.2.15.2")})
    assert await _client(session).get_versions() == VersionInfo("2.2.15.2", "3.2.0.9001")


async def test_a_build_without_version_nina_still_reports_the_api_version() -> None:
    """The N.I.N.A. version is diagnostic; its route's absence must not fail setup."""
    session = FakeSession({"version/nina": NOT_ROUTED, "version": ok("2.2.15.2")})
    assert await _client(session).get_versions() == VersionInfo("2.2.15.2", None)


async def test_a_build_without_version_is_an_endpoint_error() -> None:
    session = FakeSession({"version/nina": ok("3.2.0.9001"), "version": NOT_ROUTED})
    with pytest.raises(NinaEndpointError):
        await _client(session).get_versions()


@pytest.mark.synthetic
async def test_a_bare_string_equipment_response_is_no_data() -> None:
    client = _client(FakeSession({"equipment/info": ok("")}))
    assert (await client.get_equipment()).camera is None


@pytest.mark.synthetic
async def test_a_bare_string_history_response_is_no_frames() -> None:
    client = _client(FakeSession({"image-history": ok("")}))
    assert await client.get_frames() == []


async def test_application_start_is_the_timestamp_string() -> None:
    session = FakeSession({"application-start": load_envelope("restart_application_start.json")})
    client = _client(session)
    assert await client.get_application_start() == "2026-09-04T10:58:59.1429105-05:00"


async def test_profile_is_mapped_from_the_active_profile() -> None:
    session = FakeSession({"profile/show": ok({"TelescopeSettings": {"FocalLength": 500}})})
    assert (await _client(session).get_profile()).focal_length == 500
    assert session.requests[-1][1] == {"active": "true"}


async def test_image_history_count_returns_the_scalar() -> None:
    session = FakeSession({"image-history": ok(122)})
    assert await _client(session).get_image_history_count() == 122
    assert session.requests[-1][1] == {"count": "true"}


async def test_empty_history_count_is_zero_not_none() -> None:
    """?count=true answers 0 where bare /image-history says Index out of range."""
    session = FakeSession({"image-history": ok(0)})
    assert await _client(session).get_image_history_count() == 0
    assert session.requests[-1][1] == {"count": "true"}


async def test_frames_are_mapped_from_the_history_list() -> None:
    wire = load_envelope("dawn_image_history_with_flats.json")
    frames = await _client(FakeSession({"image-history": wire})).get_frames(include_all=True)
    assert len(frames) == len(wire["Response"])
    assert isinstance(frames[0], Frame)


@pytest.mark.synthetic
@pytest.mark.parametrize("missing", ["Date", "Filename"])
async def test_a_history_item_without_an_identity_is_skipped_not_fatal(missing) -> None:
    """Frame identity is (Date, Filename); an item lacking either cannot enter
    the fold, so it is dropped the way an unmappable event is. Every captured
    frame carries both, so one is stripped."""
    wire = load_envelope("dawn_image_history_with_flats.json")
    items = wire["Response"]
    items[0] = {k: v for k, v in items[0].items() if k != missing}
    frames = await _client(FakeSession({"image-history": wire})).get_frames(include_all=True)
    assert len(frames) == len(items) - 1


@pytest.mark.synthetic
async def test_a_bare_history_dict_is_one_frame() -> None:
    """The rig answers bare /image-history with a one-element list; a single
    object is the shape the spec documents, and the client takes either."""
    latest = load_envelope("dawn_image_history_with_flats.json")["Response"][-1]
    frames = await _client(FakeSession({"image-history": ok(latest)})).get_frames()
    assert [frame.filename for frame in frames] == [latest["Filename"]]


async def test_the_sequence_tree_is_mapped() -> None:
    client = _client(FakeSession({"sequence/json": load_envelope("dawn_sequence_complete.json")}))
    assert isinstance(await client.get_sequence(), SequenceNode)


async def test_events_use_the_offset_cached_from_equipment() -> None:
    """The mount's clock is the only place the API states the rig's UTC offset,
    and the log-scraped ERROR-* times are naive in it (dawn fixture: -5 h)."""
    session = FakeSession({"equipment/info": load_envelope("dawn_equipment_info.json"),
                           "event-history": load_envelope("dawn_event_history.json")})
    client = _client(session)
    await client.get_equipment()
    events = await client.get_events()
    error = next(event for event in events if event.name == "ERROR-PLATESOLVE")
    assert error.time.utcoffset() == timedelta(hours=-5)


async def test_the_cached_rig_offset_is_readable() -> None:
    """The coordinator places the session's noon rollover in the rig's zone."""
    client = _client(FakeSession({"equipment/info": load_envelope("dawn_equipment_info.json")}))
    assert client.rig_offset is None
    await client.get_equipment()
    assert client.rig_offset == timedelta(hours=-5)


async def test_a_zero_offset_replaces_a_stale_one() -> None:
    """UTC+0 is a real offset, not an absent one — a rig leaving summer time
    must not keep +1 h for the life of the process."""
    def clock(now: str) -> dict:
        return ok({"Mount": {"Coordinates": {"DateTime": {"Now": now}}}})

    session = FakeSession({"equipment/info": clock("2026-09-04T08:11:22-05:00"),
                           "event-history": ok([{"Event": "ERROR-PLATESOLVE",
                                                 "Time": "2026-09-03T21:54:26.93"}])})
    client = _client(session)
    await client.get_equipment()
    session.responses["equipment/info"] = clock("2026-09-04T13:11:22+00:00")
    await client.get_equipment()
    (event,) = await client.get_events()
    assert event.time.utcoffset() == timedelta(0)


async def test_an_unmappable_event_is_skipped_not_fatal() -> None:
    wire = ok([{"Event": "GHOST"}, {"Event": "SAFETY-CONNECTED", "Time": "2026-09-03T19:41:28-05:00"}])
    events = await _client(FakeSession({"event-history": wire})).get_events()
    assert [event.name for event in events] == ["SAFETY-CONNECTED"]


@pytest.mark.synthetic
@pytest.mark.parametrize(
    "response",
    [{"Event": "IMAGE-SAVE"}, ["IMAGE-SAVE"], 5],
    ids=["one-object", "list-of-strings", "scalar"],
)
async def test_an_event_history_of_the_wrong_shape_is_empty_not_fatal(response) -> None:
    """The setup replay runs inside `async_config_entry_first_refresh`, so a
    shape this never anticipated would fail the whole entry rather than lose
    one event. Every capture is a list of objects; these are not."""
    session = FakeSession({"event-history": ok(response)})
    assert await _client(session).get_events() == []


# ── request parameters ───────────────────────────────────────────────────────
#
# Request parameter names are verified by live probe and pinned here.
#
# The spec declares set-light's parameter as literally `True`; the wire reads
# `on`. `set-light?True=true` answers Success: true and leaves the panel alone.
# Never generate these from the spec.


@pytest.mark.parametrize(
    ("call", "path", "params"),
    [
        # camera
        (lambda c: c.cool_camera(-10.0), "/equipment/camera/cool",
         {"temperature": -10.0, "minutes": -1}),
        (lambda c: c.warm_camera(), "/equipment/camera/warm", {"minutes": -1}),
        (lambda c: c.set_target_temperature(-10.0), "/equipment/camera/cool",
         {"temperature": -10.0}),
        (lambda c: c.set_target_temperature(-10.0, minutes=5), "/equipment/camera/cool",
         {"temperature": -10.0, "minutes": 5}),
        (lambda c: c.set_cooler(True, -10.0), "/equipment/camera/cool",
         {"temperature": -10.0, "minutes": -1}),
        (lambda c: c.set_cooler(False, -10.0), "/equipment/camera/warm",
         {"minutes": -1}),
        (lambda c: c.set_dew_heater(True), "/equipment/camera/dew-heater",
         {"power": "true"}),
        (lambda c: c.set_usb_limit(40), "/equipment/camera/usb-limit", {"limit": 40}),
        (lambda c: c.capture_image(30), "/equipment/camera/capture",
         {"duration": 30, "save": "false"}),
        (lambda c: c.capture_image(5, gain=100, save=True), "/equipment/camera/capture",
         {"duration": 5, "save": "true", "gain": 100}),
        (lambda c: c.abort_capture(), "/equipment/camera/abort-exposure", None),
        # mount
        (lambda c: c.slew_mount(331.07, 56.6), "/equipment/mount/slew",
         {"ra": 331.07, "dec": 56.6}),
        (lambda c: c.park_mount(), "/equipment/mount/park", None),
        (lambda c: c.unpark_mount(), "/equipment/mount/unpark", None),
        (lambda c: c.find_home(), "/equipment/mount/home", None),
        (lambda c: c.set_tracking_mode(0), "/equipment/mount/tracking", {"mode": 0}),
        # focuser
        (lambda c: c.move_focuser(12000), "/equipment/focuser/move",
         {"position": 12000}),
        (lambda c: c.auto_focus(), "/equipment/focuser/auto-focus", None),
        # filter wheel
        (lambda c: c.change_filter(3), "/equipment/filterwheel/change-filter",
         {"filterId": 3}),
        # guider
        (lambda c: c.start_guiding(), "/equipment/guider/start",
         {"calibrate": "false"}),
        (lambda c: c.start_guiding(force_calibration=True), "/equipment/guider/start",
         {"calibrate": "true"}),
        (lambda c: c.stop_guiding(), "/equipment/guider/stop", None),
        (lambda c: c.clear_guider_calibration(),
         "/equipment/guider/clear-calibration", None),
        # rotator
        (lambda c: c.move_rotator(90.0), "/equipment/rotator/move",
         {"position": 90.0}),
        (lambda c: c.move_rotator_mechanical(90.0),
         "/equipment/rotator/move-mechanical", {"position": 90.0}),
        (lambda c: c.set_rotator_reverse(True), "/equipment/rotator/reverse",
         {"reverseDirection": "true"}),
        # dome
        (lambda c: c.slew_dome(180.0), "/equipment/dome/slew", {"azimuth": 180.0}),
        (lambda c: c.open_dome(), "/equipment/dome/open", None),
        (lambda c: c.close_dome(), "/equipment/dome/close", None),
        (lambda c: c.park_dome(), "/equipment/dome/park", None),
        (lambda c: c.home_dome(), "/equipment/dome/home", None),
        (lambda c: c.set_dome_follow(True), "/equipment/dome/set-follow",
         {"enabled": "true"}),
        # flat device
        (lambda c: c.set_flat_light(True), "/equipment/flatdevice/set-light",
         {"on": "true"}),
        (lambda c: c.set_flat_brightness(2048), "/equipment/flatdevice/set-brightness",
         {"brightness": 2048}),
        (lambda c: c.open_flat_cover(), "/equipment/flatdevice/set-cover",
         {"closed": "false"}),
        (lambda c: c.close_flat_cover(), "/equipment/flatdevice/set-cover",
         {"closed": "true"}),
        # switch
        (lambda c: c.set_switch_value(2, 1.0), "/equipment/switch/set",
         {"index": 2, "value": 1.0}),
        # sequence
        (lambda c: c.start_sequence(), "/sequence/start", None),
        (lambda c: c.stop_sequence(), "/sequence/stop", None),
        (lambda c: c.load_sequence("Autumn"), "/sequence/load",
         {"sequenceName": "Autumn"}),
        # livestack
        (lambda c: c.start_livestack(), "/livestack/start", None),
        (lambda c: c.stop_livestack(), "/livestack/stop", None),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
async def test_command_parameter_names_are_pinned(call, path, params) -> None:
    session = FakeSession()
    await call(_client(session))
    url, sent = session.requests[-1]
    assert path in url
    assert sent == params


async def test_a_refused_command_raises_rather_than_reporting_success() -> None:
    """Every command shares the envelope path, so none of them can be checked
    by a caller reading a return value: they all return None."""
    session = FakeSession({"mount/park": failure("Telescope not connected", 409)})
    with pytest.raises(NinaCommandError):
        await _client(session).park_mount()


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
    assert params == {"stream": "true", "quality": 85, "autoPrepare": "true"}


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
        (FakeResponse("<html>", content_type="text/html"), NinaUnavailableError),
        (NOT_ROUTED, NinaEndpointError),
        (TimeoutError(), NinaConnectionError),
        (aiohttp.ClientError("boom"), NinaConnectionError),
    ],
    ids=["no-image", "html-at-200", "pre-handler-404", "timeout", "dropped"],
)
async def test_the_image_endpoint_classifies_its_own_failures(response, error) -> None:
    """Images bypass _get for the byte stream, so the same taxonomy is pinned again."""
    with pytest.raises(error):
        await _client(FakeSession({"/image/": response})).get_image_bytes(0)

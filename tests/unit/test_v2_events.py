"""The socket is a data source, not a hint — and it lives inside the seam."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from helpers import FakeSession, load_envelope, load_fixture

from nina_astrophotography.api.models import NinaEvent
from nina_astrophotography.api.v2 import events as events_module
from nina_astrophotography.api.v2.client import NinaClientV2
from nina_astrophotography.api.v2.events import NinaEventStream

HISTORY: list[dict] = load_fixture("dawn_event_history.json")


def captured(name: str) -> dict:
    """One stored `/event-history` entry, as the rig sent it."""
    return next(event for event in HISTORY if event["Event"] == name)


def stream(**kwargs) -> NinaEventStream:
    return NinaEventStream(host="nina.local", port=1888, session=None, **kwargs)


def subscribed(**kwargs) -> tuple[NinaEventStream, list[NinaEvent]]:
    """A stream and the list one subscriber appends to."""
    socket = stream(**kwargs)
    seen: list[NinaEvent] = []
    socket.subscribe(seen.append)
    return socket, seen


# ── dispatch ─────────────────────────────────────────────────────────────────


def test_subscribe_returns_an_unsubscribe() -> None:
    socket = stream()
    seen: list[NinaEvent] = []
    unsubscribe = socket.subscribe(seen.append)
    socket._dispatch(captured("IMAGE-SAVE"), "g1")
    unsubscribe()
    socket._dispatch(captured("IMAGE-SAVE"), "g1")
    assert len(seen) == 1


def test_subscribers_receive_models_not_dicts() -> None:
    """No dict crosses the api/ boundary."""
    socket, seen = subscribed()
    socket._dispatch(captured("MOUNT-BEFORE-FLIP"), "g1")
    assert isinstance(seen[0], NinaEvent)
    assert isinstance(seen[0].time, datetime)


def test_one_failing_subscriber_does_not_starve_the_others() -> None:
    socket = stream()
    seen: list[NinaEvent] = []
    socket.subscribe(lambda _event: (_ for _ in ()).throw(RuntimeError("boom")))
    socket.subscribe(seen.append)
    socket._dispatch(captured("SAFETY-CHANGED"), "g1")
    assert len(seen) == 1


@pytest.mark.synthetic
@pytest.mark.parametrize(
    "payload",
    [{"Response": "hello from the sequence"}, "hello from the sequence"],
    ids=["no-Event", "bare-string"],
)
def test_an_eventless_payload_does_not_crash_the_stream(payload) -> None:
    """The "Send WebSocket Event" instruction puts a bare string in Response."""
    socket, seen = subscribed()
    socket._dispatch(payload, "g1")
    assert seen == []


def test_image_save_from_the_socket_carries_statistics() -> None:
    """The live socket carries ImageStatistics and no Time; /event-history the
    reverse — all its stored copies are exactly {Event, Time}."""
    socket, seen = subscribed()
    socket._dispatch(load_fixture("live_image_save_push.json"), "g1")
    assert seen[0].frame is not None
    assert seen[0].frame.filename == "frame_0000.fits"


@pytest.mark.synthetic
def test_a_timeless_frameless_payload_is_stamped_on_arrival() -> None:
    """The socket carries no clock of its own, and every NinaEvent.time must be
    offset-aware for the fold to sort. Only /event-history entries were
    captured, and all of them carry a Time."""
    socket, seen = subscribed()
    socket._dispatch({"Event": "GUIDER-DITHER"}, "g1")
    assert seen[0].time.tzinfo is not None
    assert abs(seen[0].time - datetime.now(UTC)) < timedelta(seconds=5)


@pytest.mark.parametrize(
    ("success", "expected"),
    [(True, ["IMAGE-SAVE"]),
     pytest.param(False, [], marks=pytest.mark.synthetic)],
    ids=["success", "failure"],
)
def test_a_socket_frame_is_unwrapped_like_any_other_envelope(success, expected) -> None:
    """The socket sends the same `{Response, Success, …}` envelope the HTTP
    paths do. Every captured push succeeded, so the flag is flipped here."""
    envelope = load_envelope("live_image_save_push.json") | {"Success": success}
    socket, seen = subscribed()
    socket._receive(json.dumps(envelope))
    assert [event.name for event in seen] == expected


def test_the_rig_offset_provider_resolves_a_naive_local_time() -> None:
    """The log-scraped ERROR-* times are naive in the rig's zone (dawn: -5 h)."""
    socket, seen = subscribed(rig_offset=lambda: timedelta(hours=-5))
    socket._dispatch(captured("ERROR-PLATESOLVE"), "g1")
    assert seen[0].time.utcoffset() == timedelta(hours=-5)


# ── replay ───────────────────────────────────────────────────────────────────


def _client() -> NinaClientV2:
    session = FakeSession({"event-history": load_envelope("dawn_event_history.json")})
    return NinaClientV2(host="nina.local", port=1888, session=session)


async def test_replay_folds_the_whole_stored_history() -> None:
    assert len(await stream().replay(_client(), "g1")) == len(HISTORY)


async def test_replay_caps_the_fold_at_the_newest_events(monkeypatch) -> None:
    """`WebSocketV2.Events` is an unbounded static list, so replay caps it —
    and a cap that dropped the newest events would replay a stale night."""
    monkeypatch.setattr(events_module, "REPLAY_CAP", 10)
    replayed = await stream().replay(_client(), "g1")
    assert [event.name for event in replayed] == [
        event["Event"] for event in HISTORY[-10:]
    ]


# ── lifecycle ────────────────────────────────────────────────────────────────


async def test_stopping_a_stream_that_never_started_is_harmless() -> None:
    """Unload runs the on_unload callbacks even when setup failed before start."""
    await stream().stop()

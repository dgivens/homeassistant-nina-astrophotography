"""Named rig states, assembled from captured fixtures.

A state maps an endpoint key to the FULL envelope the wire sent, so `FakeRig`
serves it through the real client rather than around it. An endpoint key is the
client's path with its single query parameter appended where the answer depends
on it (`/image-history?count=true`); `"*"` matches every path the state does
not name.

Every state carries the same endpoints, so advancing never changes which routes
exist — an endpoint one state serves and another does not reads to the client
as a build that dropped a route.

Every endpoint the integration reads now has a capture, in `imaging_guiding`.
The other states deliberately do NOT serve `/livestack/status`,
`/profile/show?active=true` or `/equipment/focuser/last-af`: an unregistered
path answers 404, which is what a build without the livestack plugin sends, and
that keeps the coordinator's not-served latch exercised.

Adding a state: build it from captured envelopes, never from a hand-written
document. A state the corpus cannot show belongs in `AWAITING_CAPTURE`.
"""
from __future__ import annotations

import json
from typing import Any

import aiohttp
from helpers import FIXTURES, load_envelope, ok

State = dict[str, Any]

# Keys the wire DROPS when a device disconnects — exactly these seven, read off
# the corpus: the focuser goes 15 keys to 8, the rotator 15 to 8 and the weather
# station 22 to 15, each losing this set and nothing else. A disconnected device
# does not null its fields; deriving one by setting Connected=False on a full
# block would produce a shape the wire never sends, and the coordinator's
# first-sight latch keys on DeviceId.
_IDENTITY_KEYS = (
    "DeviceId",
    "Name",
    "DisplayName",
    "Description",
    "DriverInfo",
    "DriverVersion",
    "SupportedActions",
)


def _versions(name: str = "dawn_equipment_info.json") -> State:
    """`/version` and `/version/nina`, read from what the capture ran against.

    From `_meta`, not from the captured `/version` envelope: a four-part .NET
    version is shaped exactly like a bare IPv4 address, so the redactor claims
    the Response and leaves the real number only in `_meta`.
    """
    meta = json.loads((FIXTURES / name).read_text(encoding="utf-8"))["_meta"]
    return {
        "/version": ok(meta["api_version"]),
        "/version/nina": ok(meta["nina_version"]),
    }


def _truncated_after_the_last_autofocus_start(name: str) -> dict:
    """The event history cut off at the newest `AUTOFOCUS-STARTING`.

    A hung autofocus is an absence — no COMPLETE follows — so the state is a
    slice of the captured list, the eighth start being the last of the eight
    the dawn capture holds.
    """
    envelope = load_envelope(name)
    events = envelope["Response"]
    starts = [i for i, event in enumerate(events) if event.get("Event") == "AUTOFOCUS-STARTING"]
    return {**envelope, "Response": events[: starts[-1] + 1]}


def _newest_frame(name: str) -> dict:
    """Bare `/image-history`: the newest frame of a captured `?all=true` list.

    The bytes are captured; only the envelope around them is assembled, for a
    rig state whose own bare path was never captured. The frame is the wire's
    own newest by `Date`, wrapped in a ONE-ELEMENT LIST — which is what the
    captured `imaging_guiding_image_history_latest.json` holds, so that is the
    shape. One frame is one frame either way: reseeding the session from this
    path is what leaves `Session Image Count` reading 1.
    """
    frames = load_envelope(name)["Response"]
    return ok([max(frames, key=lambda frame: frame["Date"])])


def _shorter_history(name: str, keep: int) -> dict:
    """The captured `?all=true` list cut to its newest `keep` frames.

    A history that shrinks is the other restart signal, and the only one when
    `/application-start` reads unchanged. No capture holds a cleared history
    beside an unchanged start time, so the list is a slice of a captured one.
    """
    envelope = load_envelope(name)
    frames = sorted(envelope["Response"], key=lambda frame: frame["Date"])
    return {**envelope, "Response": frames[-keep:]}


def _replace_device(state: State, device: str, block: dict) -> State:
    """A copy of `state` with one `/equipment/info` device block swapped."""
    envelope = state["/equipment/info"]
    response = {**envelope["Response"], device: block}
    return {**state, "/equipment/info": {**envelope, "Response": response}}


_IMAGING: State = {
    **_versions(),
    # No /application-start was captured beside the dawn corpus. The generation
    # tag is an opaque string; this one precedes the dawn event history.
    "/application-start": ok("2026-09-03T18:22:11"),
    "/equipment/info": load_envelope("dawn_equipment_info.json"),
    "/image-history?count=true": load_envelope("dawn_image_history_count.json"),
    "/image-history?all=true": load_envelope("dawn_image_history_with_flats.json"),
    "/image-history": _newest_frame("dawn_image_history_with_flats.json"),
    "/event-history": load_envelope("dawn_event_history.json"),
    "/sequence/json": load_envelope("dawn_sequence_complete.json"),
    "/flats/status": load_envelope("dawn_flats_status_idle.json"),
}

# 01:45 rig-local, 4.2 h into a session that began with a restart at 17:27: the
# camera exposing, the guider locked, 27 frames down, livestack running. The
# only state whose every endpoint is captured.
_IMAGING_GUIDING: State = {
    **_versions("imaging_guiding_equipment_info.json"),
    "/application-start": load_envelope("imaging_guiding_application_start.json"),
    "/equipment/info": load_envelope("imaging_guiding_equipment_info.json"),
    "/image-history?count=true": load_envelope("imaging_guiding_image_history_count.json"),
    "/image-history?all=true": load_envelope("imaging_guiding_image_history_all.json"),
    "/image-history": load_envelope("imaging_guiding_image_history_latest.json"),
    "/event-history": load_envelope("imaging_guiding_event_history.json"),
    "/sequence/json": load_envelope("imaging_guiding_sequence_json.json"),
    "/sequence/state": load_envelope("imaging_guiding_sequence_state.json"),
    "/flats/status": load_envelope("imaging_guiding_flats_status.json"),
    "/livestack/status": load_envelope("imaging_guiding_livestack_status.json"),
    "/profile/show?active=true": load_envelope("imaging_guiding_profile.json"),
    "/equipment/focuser/last-af": load_envelope("imaging_guiding_last_af.json"),
}

_RESTARTED: State = {
    **_versions(),
    "/application-start": load_envelope("restart_application_start.json"),
    "/equipment/info": load_envelope("restart_equipment_partial_connect.json"),
    "/image-history?count=true": load_envelope("restart_image_history_count_zero.json"),
    "/image-history?all=true": load_envelope("restart_image_history_empty_list.json"),
    "/image-history": load_envelope("restart_image_history_empty_index_error.json"),
    "/event-history": load_envelope("restart_event_history_truncated.json"),
    # Captured at a start, which is what a restart is: until a sequence loads,
    # /sequence/json answers "Sequence is not initialized" with a 409.
    "/sequence/json": load_envelope("startup_sequence_not_initialized.json"),
    # An idle flat wizard is idle whatever else the rig is doing.
    "/flats/status": load_envelope("dawn_flats_status_idle.json"),
}

# ClientError, not ClientConnectorError: a crashed N.I.N.A. raises
# ServerDisconnectedError, and the client classifies the whole family alike.
_REFUSED = aiohttp.ClientError("refused")


def _down(block: dict) -> dict:
    """A connected block as its disconnected self.

    The corpus has no capture of the camera, flat panel, safety monitor or
    switch hub down, so those four are derived — by the rule the corpus does
    show, comparing the connected and disconnected blocks it holds: the
    identity keys go, `Connected` is false.
    """
    return {k: v for k, v in block.items() if k not in _IDENTITY_KEYS} | {"Connected": False}


def disconnect(state: State, *devices: str) -> State:
    """Derive a state with `devices` disconnected, leaving `state` untouched.

    Prefers a captured disconnected block over a derived one wherever the
    corpus holds the device down.
    """
    reference = load_envelope("restart_equipment_partial_connect.json")["Response"]
    for device in devices:
        captured = reference[device]
        block = captured if captured.get("DeviceId") is None else _down(
            state["/equipment/info"]["Response"][device]
        )
        state = _replace_device(state, device, block)
    return state


# Each name gets its own dict even where two are content-equal, so an in-place
# edit in one test cannot leak into a state of another name.
STATES: dict[str, State] = {
    # Mid-session: eleven devices, 122 frames, the sequence running.
    "imaging": dict(_IMAGING),
    # Mid-session with everything captured: guider Guiding, camera exposing,
    # livestack Running, the profile and the last autofocus run served.
    "imaging_guiding": dict(_IMAGING_GUIDING),
    # CONTENT-IDENTICAL to `imaging`, deliberately: the 67 flats are in the
    # same history, because dawn flats are a phase of the night rather than a
    # different snapshot. The name exists so a test can say what it is
    # exercising; a distinct capture would replace it in place.
    "dawn_flats": dict(_IMAGING),
    # The mount parked with tracking off, which is what reports 24 hours to
    # meridian flip. The sequence document is the completed one _IMAGING already
    # carries — it is the only /sequence/json the dawn capture holds.
    "sequence_complete_tracking_off": _replace_device(
        _IMAGING, "Mount", load_envelope("dawn_mount_tracking_off.json")["Response"]
    ),
    # Four of eleven devices connected, mid-reconnect.
    "partial_equipment_connection": dict(_RESTARTED),
    "nina_restarted": dict(_RESTARTED),
    "sequencer_not_initialized": {
        **_IMAGING,
        "/sequence/json": load_envelope("startup_sequence_not_initialized.json"),
    },
    # Also content-identical to `imaging`: the dawn capture IS the physical
    # station — SkyBrightness 5692 with CloudCover "NaN", on device-09 — and
    # `weather_openmeteo` below is the contrast it exists for.
    "weather_physical_station": dict(_IMAGING),
    # The same rig reporting weather from OpenMeteo on device-12: CloudCover 14
    # with SkyBrightness "NaN". The two sources' fields are disjoint.
    "weather_openmeteo": {
        **_IMAGING,
        "/equipment/info": load_envelope("weather_source_openmeteo.json"),
    },
    # The same rig with `?count=true` one frame ahead of `?all=true`, which is
    # what a frame saved between the two reads looks like. The count is a
    # scalar, so this varies the captured envelope's one number rather than
    # inventing a history: no capture can hold a snapshot of a race.
    "imaging_count_ahead": {
        **_IMAGING,
        "/image-history?count=true": {
            **load_envelope("dawn_image_history_count.json"),
            "Response": 123,
        },
    },
    # The same rig with a SHORTER history under an UNCHANGED
    # /application-start: `?count=true` going backwards is a restart signal in
    # its own right, and the generation tag does not move with it. Slice and
    # scalar variants of captured envelopes, for the same reason
    # `imaging_count_ahead` is one.
    "imaging_count_behind": {
        **_IMAGING,
        "/image-history?count=true": {
            **load_envelope("dawn_image_history_count.json"),
            "Response": 100,
        },
        "/image-history?all=true": _shorter_history(
            "dawn_image_history_with_flats.json", 100
        ),
    },
    # The same rig answering /application-start with a null Response — the
    # generation unreadable for one tick. Also a scalar variant: the corpus
    # holds no capture of a transiently empty endpoint.
    "imaging_start_unreadable": {**_IMAGING,
                                 "/application-start": {**ok(), "Response": None}},
    "camera_disconnected": disconnect(_IMAGING, "Camera"),
    "safety_monitor_disconnected": disconnect(_IMAGING, "SafetyMonitor"),
    # All eleven down: the seven the restart capture holds down, plus the four
    # that are connected in every capture.
    "equipment_disconnected": disconnect(
        _RESTARTED, "Camera", "FlatDevice", "SafetyMonitor", "Switch"
    ),
    "nina_unreachable": {**dict.fromkeys(_IMAGING, _REFUSED), "*": _REFUSED},
    "autofocus_timed_out": {
        **_IMAGING,
        "/event-history": _truncated_after_the_last_autofocus_start(
            "dawn_event_history.json"
        ),
    },
}

# Ordered walks a test can drive with FakeRig.advance().
SEQUENCES: dict[str, list[str]] = {
    "restart": ["imaging", "nina_restarted"],
    "dawn": ["imaging", "dawn_flats", "sequence_complete_tracking_off"],
}

# States no capture can show yet. A test that needs one is skipped and named —
# never faked from a hand-written document, which would encode the spec's
# mistakes rather than the rig's behaviour.
#
# - camera_warm_at_setup: CoolerPower "NaN" with the camera connected, proving
#   a transiently-NaN field does not become a dynamic channel.
# - idle_with_stale_running_nodes: /sequence/json reading RUNNING with no
#   frames captured.
# - guider_lost_lock: the guider connected and no longer guiding.
#
# No ENDPOINT awaits capture any more — `imaging_guiding` serves all of them.
AWAITING_CAPTURE = frozenset(
    {"camera_warm_at_setup", "idle_with_stale_running_nodes", "guider_lost_lock"}
)

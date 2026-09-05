"""Named rig states, assembled from captured fixtures.

A state maps an endpoint key to the FULL envelope the wire sent, so `FakeRig`
serves it through the real client rather than around it. An endpoint key is the
client's path with its single query parameter appended where the answer depends
on it (`/image-history?count=true`); `"*"` matches every path the state does
not name.

Every state carries the same endpoints, so advancing never changes which routes
exist — an endpoint one state serves and another does not reads to the client
as a build that dropped a route. `/livestack/status` is in no state: the corpus
holds no capture of it, so it answers 404 and the client raises
`NinaEndpointError`, which is the truthful "this build does not serve it".

Adding a state: build it from captured envelopes, never from a hand-written
document. A state the corpus cannot show belongs in `AWAITING_CAPTURE`.
"""
from __future__ import annotations

import json
from typing import Any

import aiohttp
from helpers import FIXTURES, load_envelope, ok

State = dict[str, Any]

# Identity keys the wire DROPS when a device disconnects. A disconnected device
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
)


def _versions() -> State:
    """`/version` and `/version/nina`, read from what the capture ran against."""
    meta = json.loads(
        (FIXTURES / "dawn_equipment_info.json").read_text(encoding="utf-8")
    )["_meta"]
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
    "/event-history": load_envelope("dawn_event_history.json"),
    "/sequence/json": load_envelope("dawn_sequence_complete.json"),
    "/flats/status": load_envelope("dawn_flats_status_idle.json"),
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


STATES: dict[str, State] = {
    # Mid-session: eleven devices, 122 frames, the sequence running.
    "imaging": _IMAGING,
    # The 67 flats are in the same history — dawn flats are a phase of the
    # night, not a different snapshot.
    "dawn_flats": dict(_IMAGING),
    # The mount parked with tracking off, which is what reports 24 hours to
    # meridian flip. The sequence document is the completed one _IMAGING already
    # carries — it is the only /sequence/json the dawn capture holds.
    "sequence_complete_tracking_off": _replace_device(
        _IMAGING, "Mount", load_envelope("dawn_mount_tracking_off.json")["Response"]
    ),
    # Four of eleven devices connected, mid-reconnect.
    "partial_equipment_connection": _RESTARTED,
    "nina_restarted": dict(_RESTARTED),
    "sequencer_not_initialized": {
        **_IMAGING,
        "/sequence/json": load_envelope("startup_sequence_not_initialized.json"),
    },
    # The dawn capture IS the physical station: SkyBrightness 5692 with
    # CloudCover "NaN", on device-09.
    "weather_physical_station": dict(_IMAGING),
    # The same rig reporting weather from OpenMeteo on device-12: CloudCover 14
    # with SkyBrightness "NaN". The two sources' fields are disjoint.
    "weather_openmeteo": {
        **_IMAGING,
        "/equipment/info": load_envelope("weather_source_openmeteo.json"),
    },
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
AWAITING_CAPTURE = frozenset(
    {"camera_warm_at_setup", "idle_with_stale_running_nodes", "guider_lost_lock"}
)

"""The state catalogue resolves, and FakeRig serves it as the wire does.

The states are read through the real client: a state that the mapper cannot
read is not a state, and dispatch that cannot tell `?all=true` from
`?count=true` would answer the reseed with a frame count.
"""
from __future__ import annotations

from dataclasses import fields

import pytest
from scenarios.fake_rig import FakeRig
from scenarios.states import AWAITING_CAPTURE, SEQUENCES, STATES, disconnect

from nina_astrophotography.api.errors import NinaConnectionError, NinaEndpointError
from nina_astrophotography.api.v2.client import NinaClientV2

FAST_TIER = {
    "/version",
    "/version/nina",
    "/application-start",
    "/equipment/info",
    "/image-history?count=true",
}


def _client(rig: FakeRig) -> NinaClientV2:
    return NinaClientV2(host="nina.local", port=1888, session=rig)


def test_every_state_named_by_a_test_exists() -> None:
    """A typo in advance("…") must fail here, not as a confusing KeyError."""
    assert AWAITING_CAPTURE.isdisjoint(STATES)


def test_every_sequence_names_states_that_exist() -> None:
    assert {name for steps in SEQUENCES.values() for name in steps} <= set(STATES)


@pytest.mark.parametrize("name", sorted(STATES))
def test_each_state_carries_the_fast_tier_endpoints(name: str) -> None:
    """Advancing must not change which endpoints exist: an endpoint one state
    serves and another does not reads as a build that dropped a route."""
    assert FAST_TIER <= set(STATES[name])


async def test_the_history_parameters_dispatch_to_different_answers() -> None:
    """`?all=true` is the only reseed source, so answering it with the count —
    or with the bare path's single newest frame — silently caps the session."""
    client = _client(FakeRig(STATES, start="imaging"))
    assert await client.get_image_history_count() == 122
    assert len(await client.get_frames(include_all=True)) == 122


async def test_a_bare_path_is_served_when_the_state_registers_one() -> None:
    """Bare /image-history answers `Index out of range` on a restarted rig,
    which is no data rather than a failure."""
    client = _client(FakeRig(STATES, start="nina_restarted"))
    assert await client.get_frames() == []


async def test_a_path_no_state_serves_reads_as_a_route_this_build_lacks() -> None:
    """404 with EmbedIO's HTML, so a missing endpoint fails loud. The corpus
    holds no /livestack/status, and inventing one would be a written fixture."""
    client = _client(FakeRig(STATES, start="imaging"))
    with pytest.raises(NinaEndpointError):
        await client.get_livestack()


async def test_goto_changes_what_the_rig_serves() -> None:
    rig = FakeRig(STATES, start="imaging")
    client = _client(rig)
    assert await client.get_image_history_count() == 122
    rig.goto("nina_restarted")
    assert await client.get_image_history_count() == 0


async def test_advance_walks_the_named_sequence() -> None:
    rig = FakeRig(STATES, start="imaging", sequence=SEQUENCES["restart"])
    assert rig.advance() == "nina_restarted"
    assert rig.state_name == "nina_restarted"


async def test_an_unreachable_rig_refuses_every_path() -> None:
    client = _client(FakeRig(STATES, start="nina_unreachable"))
    with pytest.raises(NinaConnectionError):
        await client.get_equipment()


async def test_a_command_is_recorded_and_answered_success() -> None:
    """No state carries a command: nothing on this API can be confirmed from
    its own response, so the fake records the call and the poll reads it back."""
    rig = FakeRig(STATES, start="imaging")
    await _client(rig).set_flat_brightness(2048)
    assert rig.sent == [("/equipment/flatdevice/set-brightness", {"brightness": 2048})]


@pytest.mark.parametrize("device", ["Camera", "SafetyMonitor", "Mount"])
def test_a_disconnected_device_drops_its_identity_rather_than_nulling_it(
    device: str,
) -> None:
    """The wire DROPS DeviceId, Name and DisplayName when a device goes down.
    Setting Connected=False on a full block would produce a shape it never
    sends, and the first-sight latch keys on DeviceId."""
    block = disconnect(STATES["imaging"], device)["/equipment/info"]["Response"][device]
    assert not {"DeviceId", "Name", "DisplayName"} & set(block)
    assert block["Connected"] is False


def test_disconnecting_leaves_the_state_it_was_derived_from_alone() -> None:
    disconnect(STATES["imaging"], "Camera")
    camera = STATES["imaging"]["/equipment/info"]["Response"]["Camera"]
    assert camera["DeviceId"] == "device-01"


async def test_every_device_is_down_in_the_fully_disconnected_state() -> None:
    rig = FakeRig(STATES, start="equipment_disconnected")
    snapshot = await _client(rig).get_equipment()
    devices = [getattr(snapshot, field.name) for field in fields(snapshot)]
    assert not [d for d in devices if d is not None and d.meta.device_id]

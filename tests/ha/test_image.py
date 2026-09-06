"""image: the last saved frame, and the accumulating stack.

Both routes answer 200 whatever happens, so what these tests are about is the
two things that separate a frame from a refusal — the content type on the wire,
and the timestamp above it. The bytes are never inspected: the rig fake serves
a JPEG magic number, because the pixels are not this platform's business.
"""
from datetime import datetime

import pytest
from helpers import failure, ok
from homeassistant.components.image import async_get_image
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

LAST_FRAME = "image.n_i_n_a_last_frame"
LIVESTACK = "image.n_i_n_a_livestack"


def _params(rig, fragment: str) -> dict | None:
    """The parameters of the last request whose URL carries `fragment`."""
    return next(
        (params for url, params in reversed(rig.requests) if fragment in url), None
    )


async def test_the_last_frame_serves_the_stretched_frame(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """autoPrepare, not useAutoStretch: an unknown parameter binds nothing and
    is not rejected, so the request succeeds and returns the linear frame."""
    assert (await async_get_image(hass, LAST_FRAME)).content_type == "image/jpeg"
    assert _params(rig, "/image/0")["autoPrepare"] == "true"


@pytest.mark.parametrize(
    "envelope",
    [failure("Index out of range", 400), failure("Camera not connected", 409)],
    ids=["no-data", "refused"],
)
async def test_an_envelope_arriving_at_200_is_never_served_as_an_image(
    hass: HomeAssistant, loaded_entry, rig, envelope: dict
) -> None:
    """With stream=true a real image is image/jpeg or image/png; both of these
    arrive as 200 carrying the JSON envelope, and neither may reach a dashboard
    as image bytes."""
    rig.respond("/image/0", envelope)
    with pytest.raises(HomeAssistantError):
        await async_get_image(hass, LAST_FRAME)


async def test_a_real_failure_is_raised_naming_the_route_that_failed(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """A swallowed failure leaves a fresh timestamp beside a permanently blank
    card, and Home Assistant's own message says only "unable to get image" —
    nothing naming N.I.N.A., the route or the reason. `stream` no longer
    binding is exactly this shape: the route answers a success envelope, and
    the bytes never come."""
    rig.respond("/image/0", ok({"Image": "<base64>"}))
    with pytest.raises(HomeAssistantError, match="/image/0"):
        await async_get_image(hass, LAST_FRAME)


async def test_a_rig_with_no_frame_yet_says_nothing_about_a_route(
    hass: HomeAssistant, two_rigs
) -> None:
    """An empty history answers `Index out of range` every time a dashboard
    draws the card before the first sub — the idle rig's ordinary state, which
    must stay Home Assistant's plain "unable to get image" rather than being
    dressed up as a fault of ours."""
    with pytest.raises(HomeAssistantError) as raised:
        await async_get_image(hass, "image.dome_last_frame")
    assert "/image/0" not in str(raised.value)


async def test_the_last_frame_timestamp_is_the_newest_frame_the_rig_holds(
    hass: HomeAssistant, loaded_entry, nina_responses
) -> None:
    """Never `utcnow()`, which reports the moment the integration loaded as the
    moment a frame was captured — and never the session window either: the
    rig's history does not roll over at local noon, so what `/image/0` renders
    after the rollover is still last night's frame."""
    frames = nina_responses("dawn_image_history_with_flats.json")
    newest = max(frame["Date"] for frame in frames)
    assert hass.states.get(LAST_FRAME).state == datetime.fromisoformat(newest).isoformat()


async def test_the_last_frame_timestamp_advances_when_a_frame_is_saved(
    hass: HomeAssistant, loaded_entry, push, nina_responses
) -> None:
    before = hass.states.get(LAST_FRAME).state
    push(nina_responses("live_image_save_push.json"))
    await hass.async_block_till_done()
    assert hass.states.get(LAST_FRAME).state > before


async def test_a_rig_that_has_captured_nothing_reports_unknown(
    hass: HomeAssistant, two_rigs
) -> None:
    """The second instance starts restarted: an empty history answers `Index
    out of range`, which is what an idle rig sends. No frame is not an error."""
    assert hass.states.get("image.dome_last_frame").state == "unknown"


async def test_the_livestack_image_follows_the_pair_the_stack_last_reported(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """`STACK-UPDATED` names the target and filter currently accumulating;
    `/livestack/image/available` lists every pair without saying which."""
    await async_get_image(hass, LIVESTACK)
    assert _params(rig, "/livestack/image/NGC%20281/S") is not None


async def test_the_livestack_image_is_absent_until_a_stack_has_updated(
    hass: HomeAssistant, two_rigs
) -> None:
    """§5.2.2 first sight: with no pair there is no path to fetch, and the
    restarted rig's truncated event history holds no STACK-UPDATED."""
    assert hass.states.get("image.dome_livestack") is None


async def test_both_images_hang_off_the_hub(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    """Neither is equipment: the stack is the plugin's and `/image/0` indexes
    the rig's history, so a camera disconnecting must not take them down.

    Compared against a button already known to be on the hub, which is what the
    entity ids promise and what `docs/2.0-renames.md` records.
    """
    on_the_hub = entity_registry.async_get("button.n_i_n_a_sequence_start").device_id
    assert {entity_registry.async_get(e).device_id for e in (LAST_FRAME, LIVESTACK)} == {
        on_the_hub
    }


async def test_the_livestack_image_says_which_stack_it_is_showing(
    hass: HomeAssistant, loaded_entry
) -> None:
    """One entity follows whichever filter updated last, so on a mono rig the
    tile jumps between channels — a caption needs somewhere to read the pair
    from."""
    attributes = hass.states.get(LIVESTACK).attributes
    assert (attributes["target"], attributes["filter"]) == ("NGC 281", "S")


async def test_a_stack_that_starts_after_home_assistant_did_gets_its_entity(
    hass: HomeAssistant, two_rigs
) -> None:
    """Gold `dynamic-devices`. The default rig already carries a stack at
    setup, so the listener that adds one later is never exercised there —
    delete it and the rest of this file stays green."""
    entry = two_rigs.entries[1]
    assert hass.states.get("image.dome_livestack") is None
    entry.runtime_data.events._dispatch(
        {"Event": "STACK-UPDATED", "Time": "2026-09-04T04:30:00-05:00",
         "Target": "NGC 281", "Filter": "S"},
        entry.runtime_data.coordinator.generation,
    )
    await hass.async_block_till_done()
    assert hass.states.get("image.dome_livestack") is not None

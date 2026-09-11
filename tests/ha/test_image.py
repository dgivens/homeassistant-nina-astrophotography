"""image: the last saved frame, and the accumulating stack.

Both routes answer 200 whatever happens, so what these tests are about is the
two things that separate a frame from a refusal — the content type on the wire,
and the timestamp above it. The bytes are never inspected: the rig fake serves
a JPEG magic number, because the pixels are not this platform's business.
"""
from datetime import datetime

import pytest
from helpers import failure
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


async def test_a_refusal_arriving_as_a_200_envelope_is_not_served_as_an_image(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """With stream=true a real image is image/jpeg or image/png; a refusal
    arrives as 200 carrying the JSON envelope, which must never reach a
    dashboard as image bytes."""
    rig.respond("/image/0", failure("Index out of range", 400))
    with pytest.raises(HomeAssistantError):
        await async_get_image(hass, LAST_FRAME)


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

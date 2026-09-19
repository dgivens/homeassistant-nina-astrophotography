"""The image proxy: a dashboard card's only route to N.I.N.A.'s bytes.

Not tested here: that `HomeAssistantView` enforces auth on an unsigned,
unauthenticated request — that is Home Assistant's own framework behaviour,
not this integration's.

Most cases force the count to 1 (`rig.respond("/image-history?count=true",
ok(1))`) so index 0 translates to N.I.N.A.'s own index 0, leaving the
translation arithmetic itself to
`test_index_0_is_translated_to_ninas_newest_index`. The `imaging` state serves
bytes at its own newest index only, so a case that reads the body stubs
`/image/0` for itself.
"""
import pytest

from helpers import FakeResponse, failure, ok

ENTITY = "image.n_i_n_a_last_frame"
FRAME = b"\xff\xd8\xff\xe0 not a frame"


def _params(rig, fragment: str) -> dict | None:
    """The parameters of the last request whose URL ENDS WITH `fragment`.

    Not `in`: `/image/1` is a substring of `/image/121`, and a fragment match
    would silently pass against the wrong request.
    """
    return next(
        (params for url, params in reversed(rig.requests) if url.endswith(fragment)),
        None,
    )


async def test_a_real_image_proxies_through_with_its_content_type(
    hass, loaded_entry, rig, hass_client
) -> None:
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert resp.status == 200
    assert resp.content_type == "image/jpeg"
    # Not just a 200: the bytes proxied through are the ones the rig served.
    assert await resp.read() == FRAME


async def test_index_0_is_translated_to_ninas_newest_index(
    hass, loaded_entry, rig, hass_client
) -> None:
    """N.I.N.A. counts the other way — 0 is its OLDEST frame, confirmed
    against a live rig — so asking this proxy for index 0 (newest, matching
    `recent_frames`) must reach N.I.N.A.'s `count - 1`, never its own 0.
    """
    rig.respond("/image-history?count=true", ok(5))
    rig.respond("/image/4", ok({"Image": "irrelevant"}))  # proves 4 was asked
    client = await hass_client()
    await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert _params(rig, "/image/4") is not None
    assert _params(rig, "/image/0") is None


async def test_an_index_at_or_past_the_current_count_answers_404(
    hass, loaded_entry, rig, hass_client
) -> None:
    """The count is fetched fresh per request rather than trusted from a
    cached history, so a card asking for a frame N.I.N.A. no longer reports
    gets a clean 404 instead of a negative real index.
    """
    rig.respond("/image-history?count=true", ok(1))
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/1")
    assert resp.status == 404


@pytest.mark.parametrize(
    "envelope",
    [failure("Index out of range", 400), failure("Camera not connected", 409)],
    ids=["no-data", "refused"],
)
async def test_an_envelope_arriving_at_200_is_never_served_as_an_image(
    hass, loaded_entry, rig, hass_client, envelope: dict
) -> None:
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image/0", envelope)
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert resp.status == 404


async def test_the_rig_being_unreachable_for_the_count_answers_502(
    hass, loaded_entry, rig, hass_client
) -> None:
    """The count fetch can fail independently of the image fetch it gates —
    covered separately, since it is a distinct request the view makes. A
    handler exception (5xx) is the one failure shape that is never a
    disguised "no data yet" refusal.
    """
    rig.respond(
        "/image-history?count=true",
        FakeResponse("<html>500</html>", status=500, content_type="text/html"),
    )
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert resp.status == 502


async def test_an_unknown_entity_answers_404(hass, loaded_entry, rig, hass_client) -> None:
    client = await hass_client()
    resp = await client.get("/api/nina_astrophotography/image/image.no_such_entity/0")
    assert resp.status == 404


async def test_an_entity_whose_entry_is_unloaded_answers_404(
    hass, loaded_entry, rig, hass_client, entity_registry
) -> None:
    """The registry row survives an unload; the entry behind it does not."""
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert entity_registry.async_get(ENTITY) is not None

    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert resp.status == 404


@pytest.mark.parametrize(
    "path",
    [f"/api/nina_astrophotography/image/{ENTITY}/not-a-number",
     f"/api/nina_astrophotography/image/{ENTITY}/-1",
     f"/api/nina_astrophotography/image/{ENTITY}/0?quality=high",
     f"/api/nina_astrophotography/image/{ENTITY}/0?quality=0",
     f"/api/nina_astrophotography/image/{ENTITY}/0?quality=101"],
    ids=["bad-index", "negative-index", "bad-quality", "quality-too-low",
         "quality-too-high"],
)
async def test_an_invalid_index_or_quality_answers_400(
    hass, loaded_entry, rig, hass_client, path: str
) -> None:
    client = await hass_client()
    resp = await client.get(path)
    assert resp.status == 400


async def test_autoprepare_is_only_sent_when_the_query_asks_for_it(
    hass, loaded_entry, rig, hass_client
) -> None:
    """The card omits `autoPrepare` entirely to ask for the linear frame — an
    absent query param must not default to stretched, or a `stretch: false`
    card would get N.I.N.A.'s auto-stretch anyway.
    """
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert "autoPrepare" not in _params(rig, "/image/0")

    await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?autoPrepare=true")
    assert _params(rig, "/image/0")["autoPrepare"] == "true"

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

from urllib.parse import quote

import pytest

from custom_components.nina_astrophotography.api.v2.mapper import map_frame
from helpers import FakeResponse, failure, load_envelope, ok

ENTITY = "image.n_i_n_a_last_frame"
FRAME = b"\xff\xd8\xff\xe0 not a frame"


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
    """N.I.N.A. counts the other way — 0 is its OLDEST frame — so asking this
    proxy for index 0 (newest, matching `recent_frames`) must reach N.I.N.A.'s
    `count - 1`, never its own 0.
    """
    rig.respond("/image-history?count=true", ok(5))
    rig.respond("/image/4", ok({"Image": "irrelevant"}))  # proves 4 was asked
    client = await hass_client()
    await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0")
    assert rig.last_params("/image/4") is not None
    assert rig.last_params("/image/0") is None


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
    """The count fetch is a request of its own and can fail on its own. A
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


async def test_an_unknown_entity_answers_404(
    hass, loaded_entry, rig, hass_client
) -> None:
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
    [
        f"/api/nina_astrophotography/image/{ENTITY}/not-a-number",
        f"/api/nina_astrophotography/image/{ENTITY}/-1",
        f"/api/nina_astrophotography/image/{ENTITY}/0?quality=high",
        f"/api/nina_astrophotography/image/{ENTITY}/0?quality=0",
        f"/api/nina_astrophotography/image/{ENTITY}/0?quality=101",
        f"/api/nina_astrophotography/image/{ENTITY}/0?width=wide",
        f"/api/nina_astrophotography/image/{ENTITY}/0?width=0",
        f"/api/nina_astrophotography/image/{ENTITY}/0?date=yesterday",
        f"/api/nina_astrophotography/image/{ENTITY}/0?date=2026-09-05T01:41:27",
    ],
    ids=[
        "bad-index",
        "negative-index",
        "bad-quality",
        "quality-too-low",
        "quality-too-high",
        "bad-width",
        "width-too-small",
        "bad-date",
        "date-without-offset",
    ],
)
async def test_an_invalid_query_answers_400(
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
    params = rig.last_params("/image/0")
    assert params is not None
    assert "autoPrepare" not in params

    await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?autoPrepare=true")
    params = rig.last_params("/image/0")
    assert params is not None
    assert params["autoPrepare"] == "true"


async def test_a_width_asks_the_rig_for_a_scaled_render(
    hass, loaded_entry, rig, hass_client
) -> None:
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?width=640")
    params = rig.last_params("/image/0")
    assert params is not None
    assert (params["resize"], params["size"]) == ("true", "640x640")


async def test_a_thumbnail_is_the_rigs_own_when_it_keeps_one(
    hass, loaded_entry, rig, hass_client
) -> None:
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image/thumbnail/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(
        f"/api/nina_astrophotography/image/{ENTITY}/0?thumbnail=true&width=128"
    )
    assert await resp.read() == FRAME
    assert rig.last_params("/image/0") is None


async def test_a_thumbnail_the_rig_does_not_keep_is_rendered_at_the_width(
    hass, loaded_entry, rig, hass_client
) -> None:
    """The plugin keeps none while its "Create Thumbnails" setting is off."""
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image/thumbnail/0", failure("No thumbnails available", 400))
    rig.respond("/image/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(
        f"/api/nina_astrophotography/image/{ENTITY}/0?thumbnail=true&width=128"
    )
    assert await resp.read() == FRAME
    params = rig.last_params("/image/0")
    assert params is not None
    assert params["size"] == "128x128"


def _captured(position: int) -> tuple[dict, str]:
    """A captured frame's wire, and the `date` its `recent_frames` entry carries."""
    wire = load_envelope("imaging_guiding_image_history_all.json")["Response"][position]
    return wire, quote(map_frame(wire, None).date.isoformat())


async def test_a_date_finds_its_frame_past_one_saved_since(
    hass, loaded_entry, rig, hass_client
) -> None:
    """The card's newest is the rig's second newest once another frame is saved,
    so age 0 must not serve the newer frame under the older one's readings.
    """
    older, date = _captured(-2)
    newer, _ = _captured(-1)
    rig.respond("/image-history?count=true", ok(5))
    rig.respond("/image-history?index=4", ok([newer]))
    rig.respond("/image-history?index=3", ok([older]))
    rig.respond("/image/3", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?date={date}")
    assert await resp.read() == FRAME
    assert rig.last_params("/image/4") is None


async def test_a_date_with_nothing_saved_since_is_served_where_counted(
    hass, loaded_entry, rig, hass_client
) -> None:
    newest, date = _captured(-1)
    rig.respond("/image-history?count=true", ok(5))
    rig.respond("/image-history?index=4", ok([newest]))
    rig.respond("/image/4", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?date={date}")
    assert await resp.read() == FRAME


@pytest.mark.parametrize(("saved_since", "status"), [(10, 200), (11, 404)])
async def test_a_date_is_looked_for_past_ten_frames_saved_since(
    hass, loaded_entry, rig, hass_client, saved_since: int, status: int
) -> None:
    """A burst of short calibration frames can outrun the card's list."""
    history = load_envelope("imaging_guiding_image_history_all.json")["Response"]
    _, date = _captured(0)
    rig.respond("/image-history?count=true", ok(saved_since + 1))
    for index in range(saved_since + 1):
        rig.respond(f"/image-history?index={index}", ok([history[index]]))
    rig.respond("/image/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?date={date}")
    assert resp.status == status


async def test_a_date_no_frame_was_saved_at_answers_404(
    hass, loaded_entry, rig, hass_client
) -> None:
    """As after N.I.N.A. restarts: the card's list names the last process's frames."""
    _, date = _captured(-1)
    older, _ = _captured(-2)
    rig.respond("/image-history?count=true", ok(1))
    rig.respond("/image-history?index=0", ok([older]))
    rig.respond("/image/0", FakeResponse(FRAME, content_type="image/jpeg"))
    client = await hass_client()
    resp = await client.get(f"/api/nina_astrophotography/image/{ENTITY}/0?date={date}")
    assert resp.status == 404

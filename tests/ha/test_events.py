"""The push path's Home Assistant surface: the bus contract and unload."""
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_a_pushed_event_reaches_the_bus_under_both_names(
    hass: HomeAssistant, loaded_entry, push, nina_responses
) -> None:
    """1.4.x automations trigger on `nina_<event>` or the catch-all `nina_event`;
    the payload is now model-derived, so `frame` is a mapped Frame, not wire."""
    fired = {}
    hass.bus.async_listen("nina_image_save", lambda e: fired.update(named=e.data))
    hass.bus.async_listen("nina_event", lambda e: fired.update(catch_all=e.data))

    push(nina_responses("live_image_save_push.json"))
    await hass.async_block_till_done()

    assert fired["named"] == fired["catch_all"]
    assert fired["named"]["event"] == "IMAGE-SAVE"
    assert fired["named"]["time"]
    assert fired["named"]["frame"]["filename"] == "frame_0000.fits"


async def test_unloading_stops_the_event_stream(
    hass: HomeAssistant, loaded_entry
) -> None:
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    assert loaded_entry.state is ConfigEntryState.NOT_LOADED

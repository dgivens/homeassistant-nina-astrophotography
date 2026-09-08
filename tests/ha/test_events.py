"""The push path's Home Assistant surface: the bus contract and unload."""
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.v2 import NinaEventStream


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
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses, monkeypatch
) -> None:
    """`entry.async_on_unload(events.stop)` is what keeps the reconnect task
    from outliving the entry. The spy wraps the real `stop` rather than
    replacing it, and is installed before setup because `async_on_unload`
    captures the bound method there.
    """
    stopped: list[NinaEventStream] = []
    real_stop = NinaEventStream.stop

    async def spy(self: NinaEventStream) -> None:
        await real_stop(self)
        stopped.append(self)

    monkeypatch.setattr(NinaEventStream, "stop", spy)
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    stream = config_entry.runtime_data.events
    stream.connected = True  # as a live socket would leave it

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()

    assert stopped == [stream]
    assert stream.connected is False

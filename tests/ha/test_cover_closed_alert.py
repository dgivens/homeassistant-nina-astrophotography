"""The closed-cover blueprint, run against the integration's own sensor."""

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_mock_service

from helpers import load_fixture

BEHIND_COVER = "binary_sensor.n_i_n_a_flat_panel_light_frames_behind_closed_cover"


@pytest.mark.synthetic
@pytest.mark.parametrize(("image_type", "notified"), [("LIGHT", 1), ("DARK", 0)])
async def test_a_light_behind_the_closed_cover_notifies(
    hass: HomeAssistant, loaded_entry, installed, push, image_type: str, notified: int
) -> None:
    sent = async_mock_service(hass, "notify", "send_message")
    await installed(
        "cover_closed_alert.yaml",
        {"behind_cover": BEHIND_COVER, "notify_target": ["notify.phone"]},
    )
    payload = load_fixture("live_image_save_push.json")
    payload["ImageStatistics"]["ImageType"] = image_type

    push(payload)
    await hass.async_block_till_done()

    assert len(sent) == notified

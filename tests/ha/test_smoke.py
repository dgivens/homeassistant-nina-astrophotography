"""The HA harness itself works: the custom component is discoverable."""
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.nina_astrophotography.const import DOMAIN


async def test_integration_is_loadable(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, DOMAIN)
    assert integration.config_flow is True

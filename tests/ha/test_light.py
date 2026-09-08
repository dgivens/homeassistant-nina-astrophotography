"""The flat panel light — §5.3.4's three fixes, on real hardware numbers."""
import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS, DOMAIN as LIGHT_DOMAIN
from homeassistant.const import ATTR_ENTITY_ID, SERVICE_TURN_OFF, SERVICE_TURN_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.nina_astrophotography.api.errors import NinaCommandError
from custom_components.nina_astrophotography.api.models import DeviceMeta

ENTITY = "light.n_i_n_a_flat_panel_light"


async def _turn_on(hass: HomeAssistant, **data) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: ENTITY, **data}, blocking=True,
    )


async def _turn_off(hass: HomeAssistant) -> None:
    await hass.services.async_call(
        LIGHT_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: ENTITY}, blocking=True,
    )


async def test_brightness_scales_into_the_drivers_own_range(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    """This panel reports MaxBrightness 4096; an Alnitak reports 255."""
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 255})
    assert sent.brightness == 4096


async def test_the_reported_brightness_is_scaled_back_into_ha_units(
    hass: HomeAssistant, flat_panel_entry
) -> None:
    """The raw driver value handed HA 4096 into a property defined as 0-255.

    The fixture panel sits at driver 2048 of 4096, so HA should read 128.
    """
    assert hass.states.get(ENTITY).attributes[ATTR_BRIGHTNESS] == 128


async def test_a_bare_turn_on_does_not_go_to_full_output(
    hass: HomeAssistant, idle_flat_panel_entry, sent
) -> None:
    """THE safety test on this entity.

    A bare set-light?on=true jumps to MaxBrightness — measured 0 to 4096 — and a
    light that comes on at full output is a hazard in a shared observatory. The
    panel's ordinary idle state is Brightness 0, which is exactly the state that
    tempts a falsy-fallback implementation into sending 255.
    """
    await _turn_on(hass)
    assert sent.brightness <= 4096 // 4


async def test_a_bare_turn_on_restores_the_last_level_used(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 64})
    await _turn_off(hass)
    await _turn_on(hass)
    assert sent.brightness == 1028   # round(64 / 255 * 4096)


async def test_turn_on_sends_the_brightness_before_switching_the_light_on(
    hass: HomeAssistant, idle_flat_panel_entry, sent
) -> None:
    """Brightness first: the panel must never pass through full output."""
    await _turn_on(hass, **{ATTR_BRIGHTNESS: 128})
    assert sent.calls == [("set_flat_brightness", 2056), ("set_flat_light", True)]


# Client-side range validation is NOT tested here: Home Assistant's own light
# schema clamps a brightness outside 0-255 before our code runs, so such a test
# would be testing Home Assistant. The driver-range clamp that matters —
# set-brightness?brightness=99999 silently clamping and answering Success: true —
# is covered on number.flat_panel_brightness in phase C Task C2.


async def test_the_idle_panel_reads_off_with_no_brightness(
    hass: HomeAssistant, idle_flat_panel_entry
) -> None:
    """Brightness 0 / LightOn false is the panel's ordinary idle state."""
    state = hass.states.get(ENTITY)
    assert state.state == "off"
    assert state.attributes.get(ATTR_BRIGHTNESS) is None


async def test_a_disconnected_panel_reporting_a_zero_range_is_unavailable(
    hass: HomeAssistant, disconnected_flat_panel_entry
) -> None:
    """Min 0, Max 0 is the ordinary startup state, not a division by zero."""
    assert hass.states.get(ENTITY).state == "unavailable"


async def test_turn_off_uses_set_light_not_brightness_zero(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    """Brightness 0 is not off."""
    await _turn_off(hass)
    assert sent.last_call == ("set_flat_light", False)


async def test_a_panel_that_cannot_switch_its_light_is_unavailable_not_absent(
    hass: HomeAssistant, cover_only_flat_panel_entry
) -> None:
    """A cover-only panel keeps the entity and reports unavailable, so it does
    not appear and disappear across restarts."""
    assert hass.states.get(ENTITY).state == "unavailable"


async def test_a_panel_never_observed_has_no_entity(
    hass: HomeAssistant, set_up_with_flat_device
) -> None:
    """/equipment/info always emits a FlatDevice block; only a DeviceId proves
    the rig has one (§5.2.2)."""
    await set_up_with_flat_device(
        meta=DeviceMeta(None, None, None, None, None), connected=False,
    )
    assert hass.states.get(ENTITY) is None


async def test_a_refused_command_surfaces_as_a_home_assistant_error(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    async def refuse(self, brightness: int) -> None:
        raise NinaCommandError("Flat device not connected")

    sent.patch("set_flat_brightness", refuse)
    with pytest.raises(HomeAssistantError, match="flat panel"):
        await _turn_on(hass, **{ATTR_BRIGHTNESS: 10})

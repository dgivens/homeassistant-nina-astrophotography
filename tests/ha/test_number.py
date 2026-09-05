"""Numbers: per-device ranges, and what a set actually puts on the wire.

The refusal tests all assert `rig.sent` as well as the exception. N.I.N.A.
clamps an out-of-range value silently and answers `Success: true`, so proving
the request was never made is the whole point — an exception raised after the
command left would be no protection at all.
"""
import pytest
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import NinaCommandError
from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
from custom_components.nina_astrophotography.const import DOMAIN
from custom_components.nina_astrophotography.number import DESCRIPTIONS

BRIGHTNESS = "number.n_i_n_a_flat_panel_brightness"
FOCUSER_POSITION = "number.n_i_n_a_focuser_position"
USB_LIMIT = "number.n_i_n_a_camera_usb_limit"


async def _set(hass: HomeAssistant, entity_id: str, value: float) -> None:
    await hass.services.async_call(
        NUMBER_DOMAIN, SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id, ATTR_VALUE: value}, blocking=True,
    )


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    """The entity id claiming this `unique_id` suffix, or None if nothing does."""
    return registry.async_get_entity_id(
        NUMBER_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


@pytest.fixture
async def usb_limit_enabled(hass, entity_registry, loaded_entry):
    """The USB limit ships DIAGNOSTIC and disabled, so a test that reads or
    sets it has to enable the registry row and reload first."""
    entity_registry.async_update_entity(USB_LIMIT, disabled_by=None)
    await hass.config_entries.async_reload(loaded_entry.entry_id)
    await hass.async_block_till_done()
    return loaded_entry


@pytest.mark.parametrize(
    ("attribute", "expected"),
    # MinBrightness/MaxBrightness vary by hardware: 4096 here, 255 on an
    # Alnitak Flat-Man.
    [("max", 4096), ("min", 0)],
)
async def test_ranges_come_from_the_driver_not_a_constant(
    hass: HomeAssistant, loaded_entry, attribute: str, expected: float
) -> None:
    assert hass.states.get(BRIGHTNESS).attributes[attribute] == expected


@pytest.mark.parametrize(("attribute", "expected"), [("min", 40), ("max", 100)])
async def test_the_usb_limit_range_is_this_cameras_own(
    hass: HomeAssistant, usb_limit_enabled, attribute: str, expected: float
) -> None:
    """USBLimitMin/USBLimitMax are narrower than the 0-100 a bare USBLimit
    reading suggests, and 20 is a value this camera would clamp."""
    assert hass.states.get(USB_LIMIT).attributes[attribute] == expected


@pytest.mark.parametrize(
    ("entity_id", "value"),
    [
        (BRIGHTNESS, 99999),
        ("number.n_i_n_a_rotator_position", 400),
        ("number.n_i_n_a_camera_target_temperature", -80),
    ],
)
async def test_out_of_range_input_is_refused_rather_than_silently_clamped(
    hass: HomeAssistant, loaded_entry, rig, entity_id: str, value: float
) -> None:
    """set-brightness?brightness=99999 answers Success: true and clamps."""
    with pytest.raises(ServiceValidationError):
        await _set(hass, entity_id, value)
    assert rig.sent == []


async def test_a_panel_reporting_no_range_is_refused_rather_than_sent_to(
    hass: HomeAssistant, set_up_with_flat_device, sent
) -> None:
    """A cover-only panel reports Min 0 / Max 0, and every value is in range of
    an empty range."""
    await set_up_with_flat_device(max_brightness=0.0)
    with pytest.raises(ServiceValidationError):
        await _set(hass, BRIGHTNESS, 0)
    assert sent.calls == []


async def test_a_set_sends_the_drivers_own_units_and_does_not_touch_the_light(
    hass: HomeAssistant, flat_panel_entry, sent
) -> None:
    """The number is raw driver units, where the `light` is HA's 0-255; and
    brightness 0 is not off, so neither direction toggles the light (§5.3.4)."""
    await _set(hass, BRIGHTNESS, 1024)
    assert sent.calls == [("set_flat_brightness", 1024)]


async def test_a_set_does_not_read_the_new_value_back_from_the_response(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """No command on this API confirms anything (§3.5): the state is the next
    poll's reading, not the value that was asked for."""
    await _set(hass, FOCUSER_POSITION, 2400)
    assert rig.sent == [("/equipment/focuser/move", {"position": 2400})]
    assert hass.states.get(FOCUSER_POSITION).state == "2332"


async def test_a_refused_command_surfaces_as_a_home_assistant_error(
    hass: HomeAssistant, loaded_entry, monkeypatch
) -> None:
    async def refuse(self, _position) -> None:
        raise NinaCommandError("Focuser not connected")

    monkeypatch.setattr(NinaClientV2, "move_focuser", refuse)
    with pytest.raises(HomeAssistantError):
        await _set(hass, FOCUSER_POSITION, 2400)


@pytest.mark.parametrize(
    "suffix",
    # The 1.4.5 spellings: a survivor keeps its unique_id, so an upgraded
    # install keeps the registry row and the automations on it.
    ["camera_cooling_setpoint", "focuser_position_control", "rotator_position_control"],
)
async def test_the_kept_numbers_keep_their_1_4_5_unique_id(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    assert _registered(entity_registry, loaded_entry, suffix) is not None


@pytest.mark.parametrize(
    "key",
    # No client method binds gain, offset or binning, and `models.py` is closed
    # to fields nothing consumes; the filter wheel slot is `select.filter`.
    ["camera_gain_control", "camera_offset_control", "camera_binning_control",
     "filterwheel_slot_control"],
)
async def test_the_cut_numbers_are_not_registered(
    loaded_entry: MockConfigEntry, entity_registry, key: str
) -> None:
    assert _registered(entity_registry, loaded_entry, key) is None


async def test_the_focuser_position_number_exists(
    hass: HomeAssistant, loaded_entry
) -> None:
    """The sensor half of §5.2.3's reinstatement — disabled by default, with
    `state_class: measurement` for long-term statistics — is C6's."""
    assert hass.states.get(FOCUSER_POSITION) is not None


@pytest.mark.parametrize("key", ["camera_usb_limit", "rotator_mechanical_position"])
async def test_the_long_tail_ships_diagnostic_and_disabled(
    loaded_entry: MockConfigEntry, entity_registry, key: str
) -> None:
    """The dome's is absent from this table: no capture observes a dome, so
    §5.2.2 gates `dome_azimuth` out entirely."""
    entry = entity_registry.async_get(_registered(entity_registry, loaded_entry, key))
    assert (entry.entity_category, entry.disabled_by is not None) == (
        EntityCategory.DIAGNOSTIC, True
    )


async def test_a_value_outside_this_cameras_usb_range_is_refused(
    hass: HomeAssistant, usb_limit_enabled, rig
) -> None:
    """20 is inside the 0-100 a hardcoded range would offer and outside the
    40-100 this camera reports."""
    with pytest.raises(ServiceValidationError):
        await _set(hass, USB_LIMIT, 20)
    assert rig.sent == []


def test_every_dome_descriptor_is_marked_unverified() -> None:
    """Dome ships untested; the marker is enforced, not documented (§5.3.1)."""
    assert [d.key for d in DESCRIPTIONS if d.kind == "dome" and d.verified] == []

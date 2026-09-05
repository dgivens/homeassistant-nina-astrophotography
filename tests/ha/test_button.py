"""Buttons: one command each, fire-and-forget.

A press awaits the HTTP round trip and nothing more (§3.5), so every command
test asserts what reached the wire — `rig.sent` — and never a state read back.

No capture observes a dome, so the four dome buttons are never created (§5.2.2).
The path-per-button table therefore drives the descriptors' `press` callables
through a real client, which is the only way to cover all twelve; the entity
wiring above them is proved separately through `button.press`.
"""
import pytest
from helpers import failure
from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.const import ATTR_ENTITY_ID, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.v2.client import NinaClientV2
from custom_components.nina_astrophotography.button import DESCRIPTIONS
from custom_components.nina_astrophotography.const import DOMAIN

AUTO_FOCUS = "button.n_i_n_a_focuser_auto_focus"
CLEAR_CALIBRATION = "button.n_i_n_a_guider_clear_calibration"
DOME_OPEN = "button.n_i_n_a_dome_open"

# The endpoint each button owns. Indexed by the descriptor key, so a button
# added without a row here fails rather than going untested.
PATHS = {
    "mount_park": "/equipment/mount/park",
    "mount_unpark": "/equipment/mount/unpark",
    "mount_find_home": "/equipment/mount/home",
    "camera_abort_exposure": "/equipment/camera/abort-exposure",
    "focuser_auto_focus": "/equipment/focuser/auto-focus",
    "sequence_start": "/sequence/start",
    "sequence_stop": "/sequence/stop",
    "dome_open": "/equipment/dome/open",
    "dome_close": "/equipment/dome/close",
    "dome_park": "/equipment/dome/park",
    "dome_home": "/equipment/dome/home",
    "guider_clear_calibration": "/equipment/guider/clear-calibration",
}


async def _press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call(
        BUTTON_DOMAIN, SERVICE_PRESS, {ATTR_ENTITY_ID: entity_id}, blocking=True
    )


def _registered(registry, entry: MockConfigEntry, suffix: str) -> str | None:
    """The entity id claiming this `unique_id` suffix, or None if nothing does."""
    return registry.async_get_entity_id(
        BUTTON_DOMAIN, DOMAIN, f"{entry.entry_id}_{suffix}"
    )


@pytest.mark.parametrize(
    "description", DESCRIPTIONS, ids=[d.key for d in DESCRIPTIONS]
)
async def test_each_button_sends_its_own_command_path(rig, description) -> None:
    """Twelve buttons differing only in the endpoint they send: the mapping
    from key to path is the whole of this platform's logic."""
    await description.press(NinaClientV2("nina.local", 1888, rig))
    assert rig.sent == [(PATHS[description.key], None)]


async def test_a_press_returns_when_the_api_accepts_the_command(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """Fire-and-forget: v2 issues no request id, so a completion event cannot
    be attributed to a caller and there is nothing to wait for."""
    await _press(hass, AUTO_FOCUS)
    assert rig.sent == [("/equipment/focuser/auto-focus", None)]


async def test_a_refused_command_raises(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """A refusal is HTTP 200 carrying StatusCode 409 (§3.5)."""
    rig.respond("/equipment/focuser/auto-focus", failure("Focuser not connected"))
    with pytest.raises(HomeAssistantError):
        await _press(hass, AUTO_FOCUS)


async def test_success_false_from_clear_calibration_is_not_an_error(
    hass: HomeAssistant, advance, rig
) -> None:
    """clear-calibration is one of seven handlers that assign `Success` from a
    driver boolean, answering `Success: false, Error: "", StatusCode: 200` on a
    call that worked."""
    await advance("imaging_guiding")
    rig.respond("/equipment/guider/clear-calibration", failure("", 200))
    await _press(hass, CLEAR_CALIBRATION)


async def test_a_button_appears_when_its_equipment_is_first_seen(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """The dawn rig has no guider; §5.2.2 creates the button on first sight."""
    assert hass.states.get(CLEAR_CALIBRATION) is None
    await advance("imaging_guiding")
    assert hass.states.get(CLEAR_CALIBRATION) is not None


async def test_a_button_for_equipment_the_rig_has_never_had_is_absent(
    hass: HomeAssistant, loaded_entry
) -> None:
    """A descriptor whose slot is `None` would mint a nameless dome device."""
    assert hass.states.get(DOME_OPEN) is None


@pytest.mark.parametrize(
    "suffix",
    [
        "btn_mount_park",
        "btn_mount_unpark",
        "btn_mount_find_home",
        "btn_camera_abort",
        "btn_auto_focus",
        "btn_sequence_start",
        "btn_sequence_stop",
    ],
)
async def test_the_kept_buttons_keep_their_1_4_5_unique_id(
    loaded_entry: MockConfigEntry, entity_registry, suffix: str
) -> None:
    """The dome's four keep theirs too, but no capture observes a dome, so
    they are never registered to assert on."""
    assert _registered(entity_registry, loaded_entry, suffix) is not None


@pytest.mark.parametrize("suffix", ["btn_guider_start", "btn_guider_stop"])
async def test_the_cut_buttons_are_not_registered(
    loaded_entry: MockConfigEntry, advance, entity_registry, suffix: str
) -> None:
    """`switch.<instance>_guider` is the survivor: guiding is a state that can
    be read back, and a pair of buttons cannot report it."""
    await advance("imaging_guiding")
    assert _registered(entity_registry, loaded_entry, suffix) is None


def test_every_dome_descriptor_is_marked_unverified() -> None:
    """Dome ships untested; the marker is enforced, not documented (§5.3.1)."""
    assert [d.key for d in DESCRIPTIONS if d.kind == "dome" and d.verified] == []


def test_every_dome_button_ships_diagnostic_and_disabled() -> None:
    """Asserted on the descriptors: no capture observes a dome, so there is no
    registry row to read it off."""
    assert [
        d.key
        for d in DESCRIPTIONS
        if d.kind == "dome"
        and (
            d.entity_category is not EntityCategory.DIAGNOSTIC
            or d.entity_registry_enabled_default
        )
    ] == []

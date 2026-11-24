"""The guider not guiding blueprint, run rather than schema-checked."""

from datetime import timedelta

from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

from helpers import state_of

BLUEPRINT = "guider_not_guiding_alert.yaml"
STATUS = "sensor.rig_guider_status"
RMS = "sensor.rig_guider_rms_total"
SWITCH = "switch.rig_guider"
LIGHTS = "sensor.rig_last_image_hfr"
SEQUENCER = "binary_sensor.rig_sequencer_running"
FLIP = "binary_sensor.rig_mount_meridian_flip"
WAITING = "binary_sensor.rig_sequence_waiting"

INPUTS = {
    "guider_status": STATUS,
    "guider_rms": RMS,
    "guider_switch": SWITCH,
    "last_image_hfr": LIGHTS,
    "sequencer_running": SEQUENCER,
    "meridian_flip": FLIP,
    "sequence_waiting": WAITING,
    "notify_target": ["notify.phone"],
}

UNGUIDED = "minutes, and lights are still being saved: they are unguided."

# A sequence running and guiding.
RIG = {STATUS: "Guiding", RMS: "0.74", SWITCH: "on", SEQUENCER: "on", FLIP: "off"}


@pytest.fixture
def notified(hass: HomeAssistant):
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
async def guiding(hass: HomeAssistant, installed, freezer):
    """The blueprint over a rig guiding, with no light saved yet tonight."""
    freezer.move_to("2026-11-22T05:00:00+00:00")
    for entity, state in (RIG | {WAITING: "off"}).items():
        hass.states.async_set(entity, state)
    hass.states.async_set(LIGHTS, "1.43", {"recent_lights": []})
    await installed(BLUEPRINT, INPUTS)


@pytest.fixture
def later(hass: HomeAssistant, freezer):
    async def _later(minutes: float) -> None:
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    return _later


async def _set(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


async def _stop_guiding(hass: HomeAssistant, status: str = "LostLock") -> None:
    """RMS reads unknown in every status but `Guiding`."""
    hass.states.async_set(RMS, "unknown")
    await _set(hass, STATUS, status)


async def _save_light(hass: HomeAssistant) -> None:
    lights = state_of(hass, LIGHTS).attributes["recent_lights"]
    saved = {"date": dt_util.utcnow().isoformat(), "exposure": 300.0}
    hass.states.async_set(LIGHTS, "1.43", {"recent_lights": [*lights, saved]})
    await hass.async_block_till_done()


def _messages(notified) -> list[str]:
    return [call.data["message"] for call in notified]


@pytest.mark.usefixtures("guiding")
@pytest.mark.parametrize(
    ("status", "what"),
    [
        ("LostLock", "The guide star has been lost"),
        ("Looping", "The guider has been looping, not guiding,"),
        ("Paused", "The guider has been paused"),
        # A light saved while it calibrates is not the sequence's own start.
        ("Calibrating", "The guider has been calibrating"),
    ],
)
async def test_a_light_saved_unguided_alerts_once_the_guider_has_not_guided_long_enough(
    hass: HomeAssistant, notified, later, status: str, what: str
) -> None:
    await _stop_guiding(hass, status)
    await later(2)
    await _save_light(hass)
    quiet = len(notified)

    await later(1.1)

    assert (quiet, _messages(notified)) == (0, [f"{what} for 3 {UNGUIDED}"])


@pytest.mark.usefixtures("guiding")
async def test_no_light_saved_since_guiding_stopped_does_not_alert(
    hass: HomeAssistant, notified, later
) -> None:
    """An autofocus run exposes, and saves no light."""
    await _save_light(hass)
    await later(1)
    await _stop_guiding(hass)

    await later(10)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_a_lock_found_again_within_the_time_does_not_alert(
    hass: HomeAssistant, notified, later
) -> None:
    await _stop_guiding(hass)
    await later(1)
    await _save_light(hass)
    await later(1)
    await _set(hass, STATUS, "Guiding")

    await later(5)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_a_lock_lost_and_looping_in_turn_is_timed_from_the_first(
    hass: HomeAssistant, notified, later
) -> None:
    for status in ("LostLock", "Looping", "LostLock"):
        await _stop_guiding(hass, status)
        await later(1.2)
    await _save_light(hass)

    assert len(notified) == 1


@pytest.mark.usefixtures("guiding")
@pytest.mark.parametrize(
    ("entity_id", "state"),
    [
        # N.I.N.A. stopped the guider, which leaves `LostLock` behind.
        (SWITCH, "off"),
        (SEQUENCER, "off"),
        (FLIP, "on"),
        (WAITING, "on"),
    ],
    ids=["guider stopped", "sequence stopped", "flipping", "waiting"],
)
async def test_a_light_saved_while_a_gate_is_shut_does_not_alert(
    hass: HomeAssistant, notified, later, entity_id: str, state: str
) -> None:
    await _set(hass, entity_id, state)
    await _stop_guiding(hass)
    await later(4)

    await _save_light(hass)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_a_gate_shut_when_the_time_is_up_alerts_at_the_next_light_once_open(
    hass: HomeAssistant, notified, later
) -> None:
    await _set(hass, WAITING, "on")
    await _stop_guiding(hass)
    await later(1)
    await _save_light(hass)
    await later(3)
    await _set(hass, WAITING, "off")
    quiet = len(notified)

    await _save_light(hass)

    assert (quiet, len(notified)) == (0, 1)


@pytest.mark.usefixtures("guiding")
async def test_the_same_stretch_alerts_again_only_after_the_cooldown(
    hass: HomeAssistant, notified, later
) -> None:
    await _stop_guiding(hass)
    await later(3.1)
    for _ in range(4):
        await _save_light(hass)
        await later(5)

    assert len(notified) == 2


@pytest.mark.usefixtures("guiding")
async def test_a_new_stretch_alerts_inside_the_cooldown(
    hass: HomeAssistant, notified, later
) -> None:
    await _stop_guiding(hass)
    await later(3.1)
    await _save_light(hass)
    await _set(hass, RMS, "0.81")
    await _set(hass, STATUS, "Guiding")
    await later(1)
    await _stop_guiding(hass)
    await later(3.1)

    await _save_light(hass)

    assert len(notified) == 2


@pytest.mark.usefixtures("guiding")
async def test_running_it_by_hand_sends_the_alert(
    hass: HomeAssistant, notified, later
) -> None:
    await _stop_guiding(hass)
    await later(4)

    await hass.services.async_call(
        AUTOMATION_DOMAIN,
        "trigger",
        {"entity_id": hass.states.async_entity_ids(AUTOMATION_DOMAIN)},
        blocking=True,
    )

    assert _messages(notified) == [f"The guide star has been lost for 4 {UNGUIDED}"]

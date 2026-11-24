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
LIGHTS = "sensor.rig_last_image_hfr"
SEQUENCER = "binary_sensor.rig_sequencer_running"
FLIP = "binary_sensor.rig_mount_meridian_flip"
WAITING = "binary_sensor.rig_sequence_waiting"

INPUTS = {
    "guider_status": STATUS,
    "guider_rms": RMS,
    "last_image_hfr": LIGHTS,
    "sequencer_running": SEQUENCER,
    "meridian_flip": FLIP,
    "sequence_waiting": WAITING,
    "notify_target": ["notify.phone"],
}


# A sequence running and guiding.
RIG = {STATUS: "Guiding", RMS: "0.74", SEQUENCER: "on", FLIP: "off", WAITING: "off"}


@pytest.fixture
def notified(hass: HomeAssistant):
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
async def guiding(hass: HomeAssistant, installed, freezer):
    """The blueprint over a rig guiding, with no light saved yet tonight."""
    freezer.move_to("2026-11-22T05:00:00+00:00")
    for entity, state in RIG.items():
        hass.states.async_set(entity, state)
    hass.states.async_set(LIGHTS, "1.43", {"recent_lights": []})
    await installed(BLUEPRINT, INPUTS)


@pytest.fixture
def later(hass: HomeAssistant, freezer):
    """A second at a time, so a timer runs at its own moment rather than at
    the end of the move, where every clock it reads is already past it.
    """

    async def _later(minutes: float) -> None:
        for _ in range(round(minutes * 60)):
            freezer.tick(timedelta(seconds=1))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    return _later


async def _set(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()


@pytest.fixture
def stop_guiding(hass: HomeAssistant, freezer):
    """The status, then RMS a moment later, as one read writes them: RMS
    reads unknown in every status but `Guiding`.
    """

    async def _stop(status: str = "LostLock") -> None:
        await _set(hass, STATUS, status)
        freezer.tick(timedelta(seconds=1))
        await _set(hass, RMS, "unknown")

    return _stop


async def _save_light(
    hass: HomeAssistant, exposure: float = 60.0, rig_ahead: float = 0.0
) -> None:
    """A light saved now, stamped by a rig clock `rig_ahead` seconds fast."""
    lights = state_of(hass, LIGHTS).attributes["recent_lights"]
    date = dt_util.utcnow() + timedelta(seconds=rig_ahead)
    saved = {"date": date.isoformat(), "exposure": exposure}
    hass.states.async_set(LIGHTS, "1.43", {"recent_lights": [*lights, saved]})
    await hass.async_block_till_done()


def _unguided(status: str, minutes: int) -> str:
    return (
        f"The guider has not guided for {minutes} minutes, and reads {status}:"
        " lights are being saved unguided."
    )


def _messages(notified) -> list[str]:
    return [call.data["message"] for call in notified]


@pytest.mark.usefixtures("guiding")
@pytest.mark.parametrize(
    "status",
    [
        "LostLock",
        "Looping",
        "Selected",
        "Paused",
        # A light saved while it calibrates is not the sequence's own start.
        "Calibrating",
        # A guide camera dropping out mid-night stops PHD2.
        "Stopped",
    ],
)
async def test_a_light_saved_unguided_alerts_once_the_guider_has_not_guided_long_enough(
    hass: HomeAssistant, notified, later, stop_guiding, status: str
) -> None:
    await stop_guiding(status)
    await later(2)
    await _save_light(hass)
    quiet = len(notified)

    await later(1.1)

    assert (quiet, _messages(notified)) == (0, [_unguided(status, 3)])


@pytest.mark.usefixtures("guiding")
async def test_no_light_saved_since_guiding_stopped_does_not_alert(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    """An autofocus run exposes, and saves no light."""
    await _save_light(hass)
    await later(1)
    await stop_guiding()

    await later(10)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_an_autofocus_stop_just_after_a_light_does_not_alert_on_a_fast_rig_clock(
    hass: HomeAssistant, notified, later, freezer
) -> None:
    """N.I.N.A. stops guiding about 3 s after saving a light, and Home
    Assistant reads it up to a poll later, so a rig clock 10 s fast stamps
    that light after the stop.
    """
    await _save_light(hass, exposure=300.0, rig_ahead=10)
    freezer.tick(timedelta(seconds=3))
    await _set(hass, STATUS, "LostLock")
    await _set(hass, RMS, "unknown")

    await later(4.5)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_a_light_begun_before_guiding_stopped_does_not_alert_and_the_next_does(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    await stop_guiding()
    await later(3)
    await _save_light(hass, exposure=300.0)
    await later(4)
    quiet = len(notified)

    await _save_light(hass, exposure=300.0)

    assert (quiet, len(notified)) == (0, 1)


@pytest.mark.usefixtures("guiding")
async def test_a_lock_found_again_within_the_time_does_not_alert(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    await stop_guiding()
    await later(1)
    await _save_light(hass)
    await later(1)
    await _set(hass, STATUS, "Guiding")
    await _set(hass, RMS, "0.81")

    await later(5)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_a_lock_lost_and_looping_in_turn_is_timed_from_the_first(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    await stop_guiding("LostLock")
    for status in ("Looping", "LostLock"):
        await later(1.2)
        await _set(hass, STATUS, status)
    await later(1.2)

    await _save_light(hass)

    assert len(notified) == 1


@pytest.mark.usefixtures("guiding")
@pytest.mark.parametrize(
    ("entity_id", "state"),
    [(SEQUENCER, "off"), (FLIP, "on"), (WAITING, "on")],
    ids=["sequence stopped", "flipping", "waiting"],
)
async def test_a_light_saved_while_a_gate_is_shut_does_not_alert(
    hass: HomeAssistant, notified, later, stop_guiding, entity_id: str, state: str
) -> None:
    await _set(hass, entity_id, state)
    await stop_guiding()
    await later(4)

    await _save_light(hass)

    assert notified == []


@pytest.mark.usefixtures("guiding")
async def test_a_gate_shut_when_the_time_is_up_alerts_at_the_next_light_once_open(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    await _set(hass, WAITING, "on")
    await stop_guiding()
    await later(1)
    await _save_light(hass)
    await later(3)
    await _set(hass, WAITING, "off")
    quiet = len(notified)

    await _save_light(hass)

    assert (quiet, len(notified)) == (0, 1)


@pytest.mark.usefixtures("guiding")
async def test_the_same_stretch_alerts_again_only_after_the_cooldown(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    await stop_guiding()
    await later(3.1)
    for _ in range(4):
        await _save_light(hass)
        await later(5)

    assert len(notified) == 2


@pytest.mark.usefixtures("guiding")
async def test_a_new_stretch_alerts_inside_the_cooldown(
    hass: HomeAssistant, notified, later, stop_guiding
) -> None:
    await stop_guiding()
    await later(3.1)
    await _save_light(hass)
    await _set(hass, STATUS, "Guiding")
    await _set(hass, RMS, "0.81")
    await later(1)
    await stop_guiding()
    await later(3.1)

    await _save_light(hass)

    assert len(notified) == 2


@pytest.mark.usefixtures("guiding")
@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("LostLock", _unguided("LostLock", 4)),
        ("Guiding", "The guider reads Guiding."),
        (None, "The guider reads unknown."),
    ],
    ids=["lost", "guiding", "no status row"],
)
async def test_running_it_by_hand_sends_what_the_guider_reads(
    hass: HomeAssistant, notified, later, stop_guiding, status: str | None, message: str
) -> None:
    if status == "LostLock":
        await stop_guiding(status)
    elif status is None:
        hass.states.async_remove(STATUS)
    await later(4)

    await hass.services.async_call(
        AUTOMATION_DOMAIN,
        "trigger",
        {"entity_id": hass.states.async_entity_ids(AUTOMATION_DOMAIN)},
        blocking=True,
    )

    assert _messages(notified) == [message]

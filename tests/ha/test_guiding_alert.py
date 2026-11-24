"""The guiding alert's not-guiding arm, run rather than schema-checked."""

import asyncio
from datetime import timedelta

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)

BLUEPRINT = "guiding_alert.yaml"
STATUS = "sensor.rig_guider_status"
SWITCH = "switch.rig_guider"
IMAGING = "binary_sensor.rig_imaging"
FLIP = "binary_sensor.rig_mount_meridian_flip"
WAITING = "binary_sensor.rig_sequence_waiting"

INPUTS = {
    "nina_rig": "device-id",
    "rms_sensor": "sensor.rig_guider_rms_total",
    "guider_status": STATUS,
    "notify_target": ["notify.phone"],
    "alert_not_guiding": True,
    "guider_switch": [SWITCH],
    "imaging": [IMAGING],
    "meridian_flip": [FLIP],
    "sequence_waiting": [WAITING],
}

# Imaging and guiding, as a rig mid-sub reads.
RIG = {
    STATUS: "Guiding",
    "sensor.rig_guider_rms_total": "0.74",
    SWITCH: "on",
    IMAGING: "on",
    FLIP: "off",
    WAITING: "off",
}


@pytest.fixture
def notified(hass: HomeAssistant):
    return async_mock_service(hass, "notify", "send_message")


@pytest.fixture
def later(hass: HomeAssistant, freezer):
    """Move the clock on and let the run take its next steps.

    Not `async_block_till_done`: a run in its cooldown is a task it would wait on.
    """

    async def _later(minutes: float) -> None:
        freezer.tick(timedelta(minutes=minutes))
        async_fire_time_changed(hass)
        for _ in range(20):
            await asyncio.sleep(0)

    return _later


@pytest.fixture
def watching(hass: HomeAssistant, installed, freezer):
    """The blueprint over a rig imaging and guiding, with `changes` to the rig
    and `inputs` over this file's.
    """

    async def _watch(changes: dict[str, str] | None = None, **inputs: object) -> None:
        for entity, state in (RIG | (changes or {})).items():
            hass.states.async_set(entity, state)
        await installed(BLUEPRINT, INPUTS | inputs)

    return _watch


async def _status(hass: HomeAssistant, state: str) -> None:
    hass.states.async_set(STATUS, state)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("status", "what"),
    [
        ("LostLock", "The guide star has been lost"),
        ("Looping", "The guider has been looping, not guiding,"),
        ("Paused", "The guider has been paused"),
    ],
)
async def test_a_guider_not_guiding_while_imaging_alerts_once_it_has_lasted(
    hass: HomeAssistant, watching, notified, later, status: str, what: str
) -> None:
    await watching()
    await _status(hass, status)

    await later(2.9)
    quiet = len(notified)
    await later(0.2)

    assert (quiet, [call.data["message"] for call in notified]) == (
        0,
        [f"{what} for 3 minutes while imaging: the frames are unguided."],
    )


async def test_a_lock_lost_and_found_within_the_grace_does_not_alert(
    hass: HomeAssistant, watching, notified, later
) -> None:
    await watching()
    await _status(hass, "LostLock")
    await later(2)
    await _status(hass, "Guiding")

    await later(5)

    assert notified == []


@pytest.mark.parametrize(
    ("changes", "inputs"),
    [
        # N.I.N.A. stopped the guider, which leaves `LostLock` behind.
        ({SWITCH: "off"}, {}),
        ({IMAGING: "off"}, {}),
        ({FLIP: "on"}, {}),
        ({WAITING: "on"}, {}),
        # Without the gates there is nothing to tell a stop's leftover by.
        ({}, {"guider_switch": [], "imaging": []}),
    ],
    ids=["guider stopped", "not imaging", "flipping", "waiting", "no gate entities"],
)
async def test_a_lost_lock_does_not_alert_unless_frames_are_being_taken_unguided(
    hass: HomeAssistant,
    watching,
    notified,
    later,
    changes: dict[str, str],
    inputs: dict[str, object],
) -> None:
    await watching(changes, **inputs)
    await _status(hass, "LostLock")

    await later(5)

    assert notified == []


async def test_an_automation_built_before_the_arm_existed_does_not_alert(
    hass: HomeAssistant, installed, notified, later
) -> None:
    """The integration updates the blueprint under every automation built from
    it, so the arm's default is what those automations get.
    """
    for entity, state in RIG.items():
        hass.states.async_set(entity, state)
    await installed(
        BLUEPRINT,
        {
            key: INPUTS[key]
            for key in ("nina_rig", "rms_sensor", "guider_status", "notify_target")
        },
    )
    await _status(hass, "LostLock")

    await later(5)

    assert notified == []


async def test_calibrating_does_not_alert(
    hass: HomeAssistant, watching, notified, later
) -> None:
    """N.I.N.A. takes no frame while PHD2 calibrates."""
    await watching()
    await _status(hass, "Calibrating")

    await later(5)

    assert notified == []


async def test_high_rms_still_alerts_with_the_not_guiding_arm_on(
    hass: HomeAssistant, watching, notified, later
) -> None:
    await watching()
    hass.states.async_set("sensor.rig_guider_rms_total", "2.6")
    await hass.async_block_till_done()

    await later(3.1)

    assert [call.data["message"] for call in notified] == [
        'Guide RMS has been 2.6" for 3 minutes (threshold 2.0").'
    ]

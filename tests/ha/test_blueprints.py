"""Every shipped blueprint builds a real automation.

The unit suite checks the parts of a blueprint Home Assistant cannot: an input
bound to nothing, a hardcoded entity id. This checks the part only Home
Assistant can — that the triggers, conditions and actions are ones it accepts —
by instantiating each blueprint with a full set of inputs. A blueprint that
fails this is inert on the user's rig, and for the abort blueprint that means a
roof that never closes.
"""
import shutil
from pathlib import Path

import pytest
from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

BLUEPRINTS = Path(__file__).resolve().parents[2] / "blueprints"

# One usable value per input, per blueprint. The entity ids need not exist:
# what is under test is the schema, not the rig.
INPUTS: dict[str, dict[str, object]] = {
    "guiding_alert.yaml": {
        "nina_rig": "device-id",
        "rms_sensor": "sensor.rig_guider_rms_total",
        "guider_entity": "switch.rig_guider",
        "run_autofocus": True,
        "notify_device": "mobile_app_phone",
    },
    "meridian_flip_warning.yaml": {
        "flip_sensor": "sensor.rig_mount_time_to_meridian_flip",
        "notify_device": "mobile_app_phone",
    },
    "session_shutdown.yaml": {
        "nina_rig": "device-id",
        "sequence_running_entity": "binary_sensor.rig_sequence_running",
        "mount_parked_entity": "binary_sensor.rig_mount_at_park",
        "close_dome": True,
        "notify_device": "mobile_app_phone",
    },
    "session_startup.yaml": {
        "nina_rig": "device-id",
        "open_dome": True,
        "sequence_name": "Autumn",
        "notify_device": "mobile_app_phone",
    },
    "weather_abort.yaml": {
        "nina_rig": "device-id",
        "safety_entity": "binary_sensor.rig_safety_monitor_unsafe",
        "safety_connected_entity": "binary_sensor.rig_safety_monitor_connected",
        "mount_parked_entity": "binary_sensor.rig_mount_at_park",
        "close_dome": True,
        "auto_resume": True,
        "resume_conditions": [
            {"condition": "numeric_state",
             "entity_id": "sensor.rig_weather_wind_speed", "below": 10},
        ],
        "notify_device": "mobile_app_phone",
    },
}


@pytest.fixture
async def installed(hass: HomeAssistant):
    """The shipped blueprints, in the config directory Home Assistant reads.

    Turned off again afterwards: a time trigger registers a timer that would
    otherwise outlive the test.
    """
    shutil.copytree(BLUEPRINTS, Path(hass.config.path("blueprints")),
                    dirs_exist_ok=True)
    yield
    if entities := hass.states.async_entity_ids(AUTOMATION_DOMAIN):
        await hass.services.async_call(
            AUTOMATION_DOMAIN, "turn_off", {"entity_id": entities}, blocking=True)


@pytest.mark.parametrize("name", sorted(INPUTS), ids=str)
async def test_a_blueprint_builds_an_automation(
    hass: HomeAssistant, installed, name: str
) -> None:
    assert await async_setup_component(hass, AUTOMATION_DOMAIN, {
        AUTOMATION_DOMAIN: {
            "use_blueprint": {
                "path": f"nina_astrophotography/{name}",
                "input": INPUTS[name],
            },
        },
    })
    await hass.async_block_till_done()

    # A blueprint Home Assistant rejects still yields an automation entity —
    # an `unavailable` one. `on` is what says the config was accepted.
    states = [hass.states.get(entity).state
              for entity in hass.states.async_entity_ids(AUTOMATION_DOMAIN)]
    assert states == ["on"]

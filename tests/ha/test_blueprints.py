"""Every shipped blueprint builds a real automation, on its defaults and fully
configured.

The unit suite checks the parts of a blueprint Home Assistant cannot: an input
bound to nothing, a hardcoded entity id. This checks the part only Home
Assistant can — that the triggers, conditions and actions are ones it accepts.
Both input sets are exercised because the defaults are what a user actually
gets, and an `enabled: !input` branch that is off by default is otherwise never
built. A blueprint that fails this is inert on the rig, and for the abort
blueprint that means a roof that never closes.
"""

from pathlib import Path

from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest

BLUEPRINTS = sorted(
    (Path(__file__).resolve().parents[2] / "blueprints").rglob("*.yaml")
)

# The inputs with no default, which a user must supply. The entity ids need not
# exist: what is under test is the schema, not the rig.
REQUIRED: dict[str, dict[str, object]] = {
    "guiding_alert.yaml": {
        "nina_rig": "device-id",
        "rms_sensor": "sensor.rig_guider_rms_total",
        "guider_status": "sensor.rig_guider_status",
        "notify_target": ["notify.phone"],
    },
    "imaging_stall_alert.yaml": {
        "nina_rig": "device-id",
        "sequencer_running": "binary_sensor.rig_sequencer_running",
        "imaging": "binary_sensor.rig_imaging",
        "scheduler_waiting": "binary_sensor.rig_scheduler_waiting",
        "mount_at_park": "binary_sensor.rig_mount_at_park",
        "last_frame_at": "sensor.rig_last_frame_at",
        "camera_state": "sensor.rig_camera_state",
        "last_image_target": "sensor.rig_last_image_target",
        "sequence_target": "sensor.rig_sequence_target",
        "camera_temperature": "sensor.rig_camera_temperature",
        "camera_cooler_power": "sensor.rig_camera_cooler_power",
    },
    "meridian_flip_warning.yaml": {
        "flip_sensor": "sensor.rig_mount_time_to_meridian_flip",
        "notify_target": ["notify.phone"],
    },
    "session_shutdown.yaml": {
        "nina_rig": "device-id",
        "sequence_running": "binary_sensor.rig_sequencer_running",
        "mount_parked": "binary_sensor.rig_mount_at_park",
    },
    "session_startup.yaml": {
        "nina_rig": "device-id",
        "safety_unsafe": "binary_sensor.rig_safety_monitor_unsafe",
    },
    "weather_abort.yaml": {
        "nina_rig": "device-id",
        "safety_unsafe": "binary_sensor.rig_safety_monitor_unsafe",
        "safety_connected": "binary_sensor.rig_safety_monitor_connected",
        "mount_parked": "binary_sensor.rig_mount_at_park",
    },
}

# Every optional input, set away from its default so the branches it gates are
# built rather than skipped.
OPTIONAL: dict[str, dict[str, object]] = {
    "guiding_alert.yaml": {"run_autofocus": True},
    "imaging_stall_alert.yaml": {
        "safety_unsafe": ["binary_sensor.rig_safety_monitor_unsafe"],
        "last_image_filter": ["sensor.rig_last_image_filter"],
        "guider_status": ["sensor.rig_guider_status"],
        "guider_rms": ["sensor.rig_guider_rms_total"],
        "flip_sensor": ["sensor.rig_mount_time_to_meridian_flip"],
        "mount_at_home": ["binary_sensor.rig_mount_at_home"],
        "autofocus_failed": ["binary_sensor.rig_focuser_autofocus_failed"],
        "safety_connected": ["binary_sensor.rig_safety_monitor_connected"],
        "error_event": ["event.rig_error"],
        "imaging_quiet_minutes": 30,
        "longest_exposure_seconds": 300,
        "grace_minutes": 45,
        "settle_minutes": 20,
        # The one input that gates nothing structural: it is read inside a
        # condition template, so both values build the same automation. False
        # is still the value worth sending — it is the substitution the
        # default never produces.
        "night_only": False,
        "notify_target": ["notify.phone"],
        "escalate_minutes": 90,
        "escalations": 3,
    },
    "meridian_flip_warning.yaml": {},
    "session_shutdown.yaml": {"close_dome": True, "notify_target": ["notify.phone"]},
    "session_startup.yaml": {
        "open_dome": True,
        "sequence_name": "Autumn",
        "notify_target": ["notify.phone"],
    },
    "weather_abort.yaml": {
        "close_dome": True,
        "auto_resume": True,
        "notify_target": ["notify.phone"],
        "resume_conditions": [
            {
                "condition": "numeric_state",
                "entity_id": "sensor.rig_weather_wind_speed",
                "below": 10,
            },
        ],
    },
}


@pytest.mark.parametrize("configured", [False, True], ids=["defaults", "full"])
@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
async def test_a_blueprint_builds_an_automation(
    hass: HomeAssistant, installed, path: Path, configured: bool
) -> None:
    inputs = REQUIRED[path.name] | (OPTIONAL[path.name] if configured else {})
    assert await async_setup_component(
        hass,
        AUTOMATION_DOMAIN,
        {
            AUTOMATION_DOMAIN: {
                "use_blueprint": {
                    "path": f"nina_astrophotography/{path.name}",
                    "input": inputs,
                },
            },
        },
    )
    await hass.async_block_till_done()

    # A blueprint Home Assistant rejects still yields an automation entity —
    # an `unavailable` one. `on` is what says the config was accepted.
    states = [
        hass.states.get(entity).state
        for entity in hass.states.async_entity_ids(AUTOMATION_DOMAIN)
    ]
    assert states == ["on"]

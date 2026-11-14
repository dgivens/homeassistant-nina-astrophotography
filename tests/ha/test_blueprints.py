"""Every shipped blueprint builds a real automation, on its defaults and fully
configured, and keeps the inputs a release has shipped.

The unit suite checks the parts of a blueprint Home Assistant cannot: an input
bound to nothing, a hardcoded entity id. This checks the part only Home
Assistant can — that the triggers, conditions and actions are ones it accepts.
Both input sets are exercised because the defaults are what a user actually
gets, and an `enabled: !input` branch that is off by default is otherwise never
built. A blueprint that fails this is inert on the rig, and for the abort
blueprint that means a roof that never closes.
"""

from pathlib import Path

from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.blueprint.models import Blueprint
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml_dict
import pytest

from custom_components.nina_astrophotography.blueprint_sync import SHIPPED_DIR
from helpers import state_of

BLUEPRINTS = sorted(SHIPPED_DIR.glob("*.yaml"))

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
        "rig_reachable": ["binary_sensor.rig_reachable"],
        "site_latitude": ["sensor.rig_site_latitude"],
        "site_longitude": ["sensor.rig_site_longitude"],
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
        # This and the mute inputs gate nothing structural: they are read
        # inside condition templates, so every value builds the same
        # automation. These are still the values worth sending — the
        # substitutions the defaults never produce.
        "night_only": False,
        "mute_mode": "sun",
        "mute_from": "21:00:00",
        "mute_until": "06:00:00",
        "mute_morning_altitude": -6,
        "mute_evening_altitude": 0,
        "notify_target": ["notify.phone"],
        "escalate_minutes": 90,
        "escalations": 3,
    },
    "meridian_flip_warning.yaml": {},
    "session_shutdown.yaml": {
        "close_dome": True,
        "dome_shutter": ["sensor.rig_dome_shutter_status"],
        "close_timeout_minutes": 10,
        "notify_target": ["notify.phone"],
    },
    "session_startup.yaml": {
        "open_dome": True,
        "sequence_name": "Autumn",
        "notify_target": ["notify.phone"],
    },
    "weather_abort.yaml": {
        "rig_reachable": ["binary_sensor.rig_reachable"],
        "close_dome": True,
        "dome_shutter": ["sensor.rig_dome_shutter_status"],
        "close_timeout_minutes": 10,
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
    await installed(path.name, inputs)

    # A blueprint Home Assistant rejects still yields an automation entity —
    # an `unavailable` one. `on` is what says the config was accepted.
    states = [
        state_of(hass, entity).state
        for entity in hass.states.async_entity_ids(AUTOMATION_DOMAIN)
    ]
    assert states == ["on"]


# Every input a release has shipped. An automation keeps the values it was
# given under these names, and Home Assistant ignores a value for an input the
# blueprint no longer declares, so a removed or renamed input silently drops
# the user's setting. Add a new input here; never take one out.
RELEASED: dict[str, frozenset[str]] = {
    "guiding_alert.yaml": frozenset(
        {
            "cooldown_minutes",
            "guider_status",
            "nina_rig",
            "notify_target",
            "rms_sensor",
            "rms_threshold",
            "run_autofocus",
            "sustained_minutes",
        }
    ),
    "imaging_stall_alert.yaml": frozenset(
        {
            "autofocus_failed",
            "camera_cooler_power",
            "camera_state",
            "camera_temperature",
            "error_event",
            "escalate_minutes",
            "escalations",
            "flip_sensor",
            "grace_minutes",
            "guider_rms",
            "guider_status",
            "imaging",
            "imaging_quiet_minutes",
            "last_frame_at",
            "last_image_filter",
            "last_image_target",
            "longest_exposure_seconds",
            "mount_at_home",
            "mount_at_park",
            "mute_evening_altitude",
            "mute_from",
            "mute_mode",
            "mute_morning_altitude",
            "mute_until",
            "night_only",
            "nina_rig",
            "notify_target",
            "rig_reachable",
            "safety_connected",
            "safety_unsafe",
            "scheduler_waiting",
            "sequence_target",
            "sequencer_running",
            "settle_minutes",
            "site_latitude",
            "site_longitude",
        }
    ),
    "meridian_flip_warning.yaml": frozenset(
        {"flip_sensor", "notify_target", "warning_minutes"}
    ),
    "session_shutdown.yaml": frozenset(
        {
            "close_dome",
            "close_timeout_minutes",
            "dome_shutter",
            "mount_parked",
            "nina_rig",
            "notify_target",
            "only_if_sequence_stopped",
            "sequence_running",
            "trigger_time",
            "warming_ramp_minutes",
        }
    ),
    "session_startup.yaml": frozenset(
        {
            "camera_target_temp",
            "cooling_ramp_minutes",
            "cooling_wait_minutes",
            "nina_rig",
            "notify_target",
            "open_dome",
            "safety_unsafe",
            "sequence_name",
            "trigger_time",
        }
    ),
    "weather_abort.yaml": frozenset(
        {
            "auto_resume",
            "close_dome",
            "close_timeout_minutes",
            "dome_shutter",
            "mount_parked",
            "nina_rig",
            "notify_target",
            "park_mount",
            "resume_conditions",
            "resume_delay_minutes",
            "rig_reachable",
            "safety_connected",
            "safety_unsafe",
            "stop_sequence",
            "warm_camera",
            "warming_minutes",
        }
    ),
}


def _inputs(path: Path) -> dict[str, dict | None]:
    """The blueprint's inputs, flattened through sections."""
    return Blueprint(
        load_yaml_dict(path), expected_domain=AUTOMATION_DOMAIN, schema=lambda x: x
    ).inputs


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_every_released_input_is_still_declared(path: Path) -> None:
    assert not RELEASED[path.name] - set(_inputs(path))


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_every_declared_input_is_recorded_as_released(path: Path) -> None:
    """Otherwise a new input is unprotected from the next release."""
    assert not set(_inputs(path)) - RELEASED[path.name]


# The inputs released without a default. Never add one: the integration updates
# the blueprint under every automation already built from it, and an
# automation missing a required input stops loading.
RELEASED_REQUIRED: dict[str, frozenset[str]] = {
    "guiding_alert.yaml": frozenset(
        {"guider_status", "nina_rig", "notify_target", "rms_sensor"}
    ),
    "imaging_stall_alert.yaml": frozenset(
        {
            "camera_cooler_power",
            "camera_state",
            "camera_temperature",
            "imaging",
            "last_frame_at",
            "last_image_target",
            "mount_at_park",
            "nina_rig",
            "scheduler_waiting",
            "sequence_target",
            "sequencer_running",
        }
    ),
    "meridian_flip_warning.yaml": frozenset({"flip_sensor", "notify_target"}),
    "session_shutdown.yaml": frozenset(
        {"mount_parked", "nina_rig", "sequence_running"}
    ),
    "session_startup.yaml": frozenset({"nina_rig", "safety_unsafe"}),
    "weather_abort.yaml": frozenset(
        {"mount_parked", "nina_rig", "safety_connected", "safety_unsafe"}
    ),
}


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_only_a_released_required_input_lacks_a_default(path: Path) -> None:
    required = {
        name
        for name, spec in _inputs(path).items()
        if not spec or "default" not in spec
    }

    assert required <= RELEASED_REQUIRED[path.name]

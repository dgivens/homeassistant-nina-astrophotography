"""Device registry structure for the N.I.N.A. integration.

N.I.N.A. is a hub: it drives a camera, mount, focuser and so on, each with its
own driver, version and identity. Those get one Home Assistant device apiece,
linked to a N.I.N.A. service device via ``via_device``, so the per-equipment
metadata the API reports (``Name``, ``DeviceId``, ``DriverVersion``,
``DriverInfo``) lands in the device registry where it belongs rather than in
entity attributes.

Equipment is frequently disconnected when Home Assistant starts, so the
metadata is not available at entity-add time. :func:`async_sync_devices` writes
it into the registry as soon as it appears, and keeps it current when a driver
is swapped.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.device_registry import (
    DeviceEntryType,
    DeviceInfo,
)

from .const import DEFAULT_NAME, DOMAIN
from .helpers import safe

_LOGGER = logging.getLogger(__name__)

HUB = "hub"

# entry_id -> the label prefixed to every device name for that instance. Device
# names drive entity ids (has_entity_name is on), so two instances must differ
# here or their entities collide.
_INSTANCE_NAMES: dict[str, str] = {}


def set_instance_name(entry_id: str, name: str) -> None:
    _INSTANCE_NAMES[entry_id] = (name or DEFAULT_NAME).strip() or DEFAULT_NAME


def forget_instance(entry_id: str) -> None:
    _INSTANCE_NAMES.pop(entry_id, None)


def instance_name(entry_id: str) -> str:
    return _INSTANCE_NAMES.get(entry_id, DEFAULT_NAME)

# Coordinator subsystem key -> the device name shown in Home Assistant.
EQUIPMENT: dict[str, str] = {
    "camera": "Camera",
    "mount": "Mount",
    "focuser": "Focuser",
    "filterwheel": "Filter Wheel",
    "guider": "Guider",
    "rotator": "Rotator",
    "dome": "Dome",
    "flatdevice": "Flat Panel",
    "switch": "Switch Device",
    "weather": "Weather Station",
    "safetymonitor": "Safety Monitor",
}

# Entity-key prefix -> subsystem. Longest prefix wins, so the more specific
# entries below are matched before the broader ones.
_PREFIX_MAP: tuple[tuple[str, str], ...] = (
    # Button keys carry a btn_ prefix and do not always name their subsystem.
    ("btn_auto_focus", "focuser"),
    ("btn_focuser_", "focuser"),
    ("btn_mount_", "mount"),
    ("btn_guider_", "guider"),
    ("btn_rotator_", "rotator"),
    ("btn_dome_", "dome"),
    ("btn_camera_", "camera"),
    ("camera_current_filter", "filterwheel"),
    ("filterwheel_", "filterwheel"),
    ("filter_wheel_", "filterwheel"),
    ("camera_", "camera"),
    ("mount_", "mount"),
    ("focuser_", "focuser"),
    ("autofocus_", "focuser"),
    ("guider_", "guider"),
    ("rotator_", "rotator"),
    ("dome_", "dome"),
    ("flatdevice_", "flatdevice"),
    ("flat_", "flatdevice"),
    ("switch_", "switch"),
    ("weather_", "weather"),
    ("safetymonitor_", "safetymonitor"),
)

# Entity keys that belong to the hub even though their prefix suggests
# otherwise — session-scoped data rather than a property of one device.
_HUB_KEYS: frozenset[str] = frozenset(
    {
        "flats_state",
        "flats_progress",
        "flats_running",
        "flat_wizard_running",
        "image_scale",
    }
)


def subsystem_for(key: str) -> str:
    """Return the subsystem an entity key belongs to, or ``HUB``."""
    if key in _HUB_KEYS:
        return HUB
    for prefix, subsystem in sorted(_PREFIX_MAP, key=lambda p: -len(p[0])):
        if key.startswith(prefix):
            return subsystem
    return HUB


def hub_identifier(entry_id: str) -> tuple[str, str]:
    return (DOMAIN, entry_id)


def device_identifier(entry_id: str, subsystem: str) -> tuple[str, str]:
    if subsystem == HUB:
        return hub_identifier(entry_id)
    return (DOMAIN, f"{entry_id}:{subsystem}")


def async_register_hub(hass, entry, host: str, port: int) -> None:
    """Register the N.I.N.A. service device that all equipment hangs off.

    Registered up front rather than through an entity's ``device_info`` so the
    hub exists before any equipment device tries to reference it as its
    ``via_device``.
    """
    from homeassistant.helpers import device_registry as dr

    dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={hub_identifier(entry.entry_id)},
        name=instance_name(entry.entry_id),
        manufacturer="Nighttime Imaging 'N' Astronomy",
        model="Advanced API",
        entry_type=DeviceEntryType.SERVICE,
        configuration_url=f"http://{host}:{port}",
    )


def device_info_for(entry_id: str, subsystem: str) -> DeviceInfo:
    """Device info an entity should claim.

    Equipment devices carry only their identity and link; the driver-reported
    model and version are filled in by :func:`async_sync_devices` once the
    equipment actually reports them, which is usually after startup.
    """
    if subsystem == HUB:
        return DeviceInfo(identifiers={hub_identifier(entry_id)})
    return DeviceInfo(
        identifiers={device_identifier(entry_id, subsystem)},
        name=f"{instance_name(entry_id)} {EQUIPMENT[subsystem]}",
        via_device=hub_identifier(entry_id),
    )


def device_info_for_key(entry_id: str, key: str) -> DeviceInfo:
    """Device info for a descriptor-driven entity, routed by its key."""
    return device_info_for(entry_id, subsystem_for(key))


# ─── Keeping driver metadata current ──────────────────────────────────────────

def _metadata(data: dict, subsystem: str) -> dict[str, Any]:
    """Registry fields for one subsystem, from the latest poll."""
    response = safe(data, subsystem, "Response")
    if not isinstance(response, dict) or not response.get("Connected"):
        # A disconnected device reports stale or empty identity; leave whatever
        # the registry already holds rather than blanking it out.
        return {}
    # DriverInfo is deliberately unused: it is free-form text, and several
    # drivers return the ASCOM template default ("Information about the driver
    # itself. Version: 6.5"), which is worse than leaving manufacturer unset.
    # DisplayName is just Name with " (ASCOM)" appended, so Name is preferred.
    fields = {
        "model": response.get("Name"),
        "model_id": response.get("DeviceId"),
        "sw_version": response.get("DriverVersion"),
    }
    return {k: v for k, v in fields.items() if v}


def async_sync_devices(hass, entry_id: str, data: dict) -> None:
    """Push driver-reported metadata into the device registry.

    Called after every coordinator update. Writes only when something actually
    changed, so this is a no-op on the overwhelming majority of polls.
    """
    from homeassistant.helpers import device_registry as dr

    registry = dr.async_get(hass)

    nina_version = safe(data, "nina_version", "Response")
    if isinstance(nina_version, str) and nina_version:
        hub = registry.async_get_device(identifiers={hub_identifier(entry_id)})
        if hub is not None and hub.sw_version != nina_version:
            registry.async_update_device(hub.id, sw_version=nina_version)

    for subsystem in EQUIPMENT:
        fields = _metadata(data, subsystem)
        if not fields:
            continue
        device = registry.async_get_device(
            identifiers={device_identifier(entry_id, subsystem)}
        )
        if device is None:
            continue
        changed = {
            key: value
            for key, value in fields.items()
            if getattr(device, key, None) != value
        }
        if changed:
            _LOGGER.debug("Updating %s device registry entry: %s", subsystem, changed)
            registry.async_update_device(device.id, **changed)

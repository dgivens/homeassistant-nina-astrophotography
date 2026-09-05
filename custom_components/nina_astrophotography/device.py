"""The device model: a N.I.N.A. hub with one child per piece of equipment.

N.I.N.A. drives a camera, a mount, a focuser and so on, each with its own
driver, version and identity. Each gets its own Home Assistant device linked to
the hub by `via_device_id`, so the driver metadata the API reports lands in the
device registry rather than in entity attributes (§5.1).

Devices are created on FIRST SIGHT: `/equipment/info` always emits all eleven
blocks, so a block's presence proves nothing — the coordinator latches which
slots have ever carried a `DeviceId` and blanks the rest, and this module
creates a device for every slot that survives that. A device once created is
never removed by a poll: equipment is routinely disconnected when Home
Assistant starts, and a device that came and went would take its entity ids
with it. `async_remove_config_entry_device` is the deliberate way out.

`async_sync_devices` is the only writer of device metadata. Entities claim a
device by its identifiers alone (`device_identifiers`), because the metadata is
usually not available when an entity is constructed — equipment is still
connecting — and a value frozen there would never be filled in. The price is
that a platform MUST gate entity creation on its slot being non-`None`, as
`light.py` does: an identifiers-only `DeviceInfo` naming a kind this module has
not created leaves the entity platform to create a nameless device.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .api.models import DeviceMeta, VersionInfo
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN

if TYPE_CHECKING:
    from .coordinator import NinaConfigEntry, NinaData

MANUFACTURER = "N.I.N.A."

# Slot name -> the label shown after the instance name. The slot names are the
# `EquipmentSnapshot` field names, so a kind indexes the snapshot directly.
KINDS: Mapping[str, str] = {
    "camera": "Camera",
    "mount": "Mount",
    "focuser": "Focuser",
    "filter_wheel": "Filter Wheel",
    "guider": "Guider",
    "rotator": "Rotator",
    "dome": "Dome",
    "flat_device": "Flat Panel",
    "weather": "Weather",
    "safety_monitor": "Safety Monitor",
    "switch_device": "Switch",
}


def device_identifiers(entry_id: str, kind: str | None = None) -> set[tuple[str, str]]:
    """What an entity claims: one equipment kind, or the hub when `kind` is None."""
    suffix = f"_{kind}" if kind is not None else ""
    return {(DOMAIN, f"{entry_id}{suffix}")}


def hub_device_info(
    entry_id: str, instance_name: str, version: VersionInfo,
    configuration_url: str | None = None,
) -> DeviceInfo:
    """The service device every piece of equipment hangs off."""
    return DeviceInfo(
        identifiers=device_identifiers(entry_id),
        name=instance_name,
        manufacturer=MANUFACTURER,
        model="Advanced API",
        entry_type=DeviceEntryType.SERVICE,
        **_present(
            sw_version=version.nina_version,
            configuration_url=configuration_url,
        ),
    )


def child_device_info(
    entry_id: str,
    instance_name: str,
    kind: str,
    meta: DeviceMeta | None,
    via_device_id: str,
) -> DeviceInfo:
    """One piece of equipment, linked to the hub.

    `model` and `sw_version` are OMITTED rather than set to `None` when the
    driver is not reporting them: a disconnected device drops its whole
    identity, and writing that through would blank what the registry holds.
    The manufacturer is the hub's — the driver's vendor is not on the wire.
    """
    return DeviceInfo(
        identifiers=device_identifiers(entry_id, kind),
        name=f"{instance_name} {KINDS[kind]}",
        manufacturer=MANUFACTURER,
        via_device_id=via_device_id,
        **_present(
            model=meta.name if meta else None,
            sw_version=meta.driver_version if meta else None,
        ),
    )


@callback
def async_sync_devices(
    hass: HomeAssistant, entry: NinaConfigEntry, data: NinaData
) -> None:
    """Create the hub and every observed child, and keep their metadata current.

    Runs on every coordinator publish. A device that connects long after Home
    Assistant started, or one whose driver is swapped under a running rig,
    fills in or replaces its registry fields here.
    """
    registry = dr.async_get(hass)
    instance_name = entry.runtime_data.instance_name
    hub = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        **hub_device_info(
            entry.entry_id,
            instance_name,
            data.version,
            configuration_url=(
                f"http://{entry.data[CONF_HOST]}:"
                f"{entry.data.get(CONF_PORT, DEFAULT_PORT)}"
            ),
        ),
    )
    for kind in KINDS:
        device = getattr(data.snapshot, kind)
        if device is None:
            continue
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **child_device_info(
                entry.entry_id, instance_name, kind, device.meta, hub.id
            ),
        )


def kind_of(entry_id: str, device: dr.DeviceEntry) -> str | None:
    """The equipment kind a registry device stands for; `None` for the hub.

    Raises `LookupError` for a device this entry does not recognise — one left
    behind by an identifier scheme we no longer write.
    """
    for domain, identifier in device.identifiers:
        if domain != DOMAIN:
            continue
        if identifier == entry_id:
            return None
        kind = identifier.removeprefix(f"{entry_id}_")
        if kind in KINDS:
            return kind
    raise LookupError(device.identifiers)


def _present(**fields: str | None) -> dict[str, str]:
    """The fields that carry a value, so a missing one never blanks the registry."""
    return {name: value for name, value in fields.items() if value is not None}

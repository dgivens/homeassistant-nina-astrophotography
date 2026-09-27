"""The device model: a N.I.N.A. hub with one child per piece of equipment,
carrying the driver metadata.

A device is created once its equipment has been observed (see
`NinaCoordinator`), and a poll never removes one: equipment is routinely
down, and its entity ids would go with it.

`async_sync_devices` is the only writer of device metadata; entities claim a
device by identifiers alone, since the metadata usually arrives later. So a
platform must gate entity creation on `observed()`, or the entity platform
creates a nameless device.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .api.models import DeviceMeta, SwitchChannelModel, VersionInfo
from .const import CONF_HOST, CONF_PORT, DEFAULT_PORT, DOMAIN

if TYPE_CHECKING:
    from .coordinator import NinaConfigEntry, NinaData

MANUFACTURER = "N.I.N.A."

# `EquipmentSnapshot` field -> the device name after the instance name.
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


def observed(data: NinaData, kind: str | None) -> bool:
    """Whether an entity's equipment has been seen; always for the hub (`None`)."""
    return kind is None or getattr(data.snapshot, kind) is not None


def read_field(kind: str, field: str, default: Any = None) -> Callable[[NinaData], Any]:
    """One reading off one equipment model, `default` while the device is absent."""

    def value(data: NinaData) -> Any:
        device = getattr(data.snapshot, kind)
        return default if device is None else getattr(device, field)

    return value


def channels_of(data: NinaData) -> tuple[SwitchChannelModel, ...]:
    """Every channel the N.I.N.A. switch device reports; empty while absent."""
    device = data.snapshot.switch_device
    return device.channels if device is not None else ()


def channel_platform(channel: SwitchChannelModel) -> Platform | None:
    """The platform a channel belongs on; `None` when none can take it.

    Read-only is a `sensor`, one step a `switch`, a wider range a `number`; a
    writable channel with no range is none of them.
    """
    if not channel.writable:
        return Platform.SENSOR
    if channel.binary:
        return Platform.SWITCH
    if channel.minimum is not None and channel.maximum is not None:
        return Platform.NUMBER
    return None


def channels_for(
    data: NinaData, platform: Platform | None
) -> tuple[SwitchChannelModel, ...]:
    """The channels one platform takes; `None` for those no platform claims."""
    return tuple(c for c in channels_of(data) if channel_platform(c) == platform)


def channel_key(channel: SwitchChannelModel) -> str:
    """The `unique_id` suffix for one N.I.N.A. switch-device channel.

    Keyed on the channel's `Id`, not its position, so a channel added later
    renumbers nothing.
    """
    return f"switch_channel_{channel.index}"


def channel_name(channel: SwitchChannelModel) -> str:
    """The driver's name for a channel, else `Channel <n>`.

    An empty name would take the device's, collapsing unnamed channels onto
    one entity id.
    """
    return channel.name or f"Channel {channel.index}"


def channel_of(data: NinaData, index: int) -> SwitchChannelModel | None:
    """The channel with this `Id`, if the driver still reports it."""
    return next((c for c in channels_of(data) if c.index == index), None)


def device_identifiers(entry_id: str, kind: str | None = None) -> set[tuple[str, str]]:
    """What an entity claims: one equipment kind, or the hub when `kind` is None."""
    suffix = f"_{kind}" if kind is not None else ""
    return {(DOMAIN, f"{entry_id}{suffix}")}


def hub_device_info(
    entry_id: str,
    instance_name: str,
    version: VersionInfo,
    configuration_url: str | None = None,
) -> DeviceInfo:
    """The service device every piece of equipment hangs off."""
    return DeviceInfo(
        identifiers=device_identifiers(entry_id),
        name=instance_name,
        manufacturer=MANUFACTURER,
        model="Advanced API",
        entry_type=DeviceEntryType.SERVICE,
    ) | _present(
        sw_version=version.nina_version,
        configuration_url=configuration_url,
    )


def child_device_info(
    entry_id: str,
    instance_name: str,
    kind: str,
    meta: DeviceMeta | None,
    via_device_id: str,
    suggested_area: str | None = None,
) -> DeviceInfo:
    """One piece of equipment, linked to the hub.

    Missing `model` and `sw_version` are omitted rather than `None`, so a
    disconnected device does not blank the registry. The driver's vendor is
    not on the wire.

    `suggested_area` is the hub's area, applied only when the device is
    created: `via_device` does not inherit an area.
    """
    return DeviceInfo(
        identifiers=device_identifiers(entry_id, kind),
        name=f"{instance_name} {KINDS[kind]}",
        manufacturer=MANUFACTURER,
        via_device_id=via_device_id,
    ) | _present(
        model=meta.name if meta else None,
        sw_version=meta.driver_version if meta else None,
        suggested_area=suggested_area,
    )


@callback
def async_sync_devices(
    hass: HomeAssistant, entry: NinaConfigEntry, data: NinaData
) -> None:
    """Create the hub and every observed child, and keep their metadata current.

    Runs on every publish, so late equipment and swapped drivers update.
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
    hub_area = ar.async_get(hass).async_get_area(hub.area_id) if hub.area_id else None
    hub_area_name = hub_area.name if hub_area else None
    for kind in KINDS:
        device = getattr(data.snapshot, kind)
        if device is None:
            continue
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            **child_device_info(
                entry.entry_id,
                instance_name,
                kind,
                device.meta,
                hub.id,
                suggested_area=hub_area_name,
            ),
        )


def kind_of(entry_id: str, device: dr.DeviceEntry) -> str | None:
    """The equipment kind a registry device stands for; `None` for the hub.

    Raises `LookupError` for an identifier this entry does not write.
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


def _present(**fields: str | None) -> DeviceInfo:
    """The fields that carry a value. String-valued keys only: the cast checks
    nothing.
    """
    return cast(
        DeviceInfo,
        {name: value for name, value in fields.items() if value is not None},
    )

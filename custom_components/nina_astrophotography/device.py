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
import math
from typing import TYPE_CHECKING, Any, cast

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .api.models import DeviceMeta, SwitchChannelModel, VersionInfo
from .const import CONF_HOST, CONF_PORT, DOMAIN
from .derive import rotator_fold

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


def supports(kind: str, field: str) -> Callable[[NinaData], bool]:
    """A capability flag off one equipment model, false while it is absent."""
    read = read_field(kind, field)
    return lambda data: bool(read(data))


def refused_while_following(data: NinaData) -> str | None:
    """Refuse a dome move while it follows the mount: N.I.N.A. answers one by
    quietly turning following off, and the slit leaves the scope.
    """
    return "dome_following" if read_field("dome", "following")(data) else None


def refused_while_unsafe(data: NinaData) -> str | None:
    """Refuse opening the dome while the safety monitor reports unsafe.

    N.I.N.A.'s own refusal is a profile option, off by default. A monitor that
    is absent or not reporting refuses nothing here.
    """
    return (
        "dome_unsafe"
        if read_field("safety_monitor", "is_safe")(data) is False
        else None
    )


def refused_while_unsynced(data: NinaData) -> str | None:
    """Refuse a sky-angle move until a plate solve syncs the rotator.

    N.I.N.A. accepts the move, then fails it unsynced after answering, so the
    rotator stays put behind a `Success: true`.
    """
    return (
        "rotator_not_synced" if read_field("rotator", "synced")(data) is False else None
    )


def raise_outside_rotator_range(data: NinaData, angle: float) -> None:
    """Refuse a mechanical angle outside the profile's rotator range.

    N.I.N.A. would turn the rotator to another angle instead, and only says
    so on its own screen.
    """
    arc = data.profile.rotator_range
    if arc is None or arc.span >= 360:
        return
    folded = rotator_fold(angle, arc.start, arc.span)
    if math.isclose(folded, angle % 360, abs_tol=1e-6):
        return
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="outside_rotator_range",
        translation_placeholders={
            "value": f"{angle:g}",
            "start": f"{arc.start:g}",
            "end": f"{(arc.start + arc.span) % 360:g}",
            "folded": f"{folded:g}",
        },
    )


def raise_unless_cover_closed(data: NinaData) -> None:
    """Refuse lighting the panel while its cover reads anything but closed.

    A panel lit with its cover open shines into the observatory, onto every
    other telescope in a shared one. A panel with no cover is exempt, and so is
    a disconnected one, which reports none: N.I.N.A. refuses it itself.
    """
    panel = data.snapshot.flat_device
    if (
        panel is None
        or panel.supports_open_close is False
        or panel.cover_state in ("Closed", "NotPresent")
    ):
        return
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="flat_panel_cover_not_closed",
        translation_placeholders={"cover": panel.cover_state or "Unknown"},
    )


def raise_if_level_lights_open_panel(data: NinaData, level: float) -> None:
    """Refuse a brightness above the panel's minimum unless its cover is
    closed: an ASCOM panel lights at any such level.
    """
    bounds = read_field("flat_device", "brightness_range")(data)
    if bounds is not None and level > bounds[0]:
        raise_unless_cover_closed(data)


def raise_while_lit(data: NinaData) -> None:
    """Refuse opening the cover while the panel reads lit, for the reason
    `raise_unless_cover_closed` gives.
    """
    if read_field("flat_device", "light_on")(data):
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="flat_panel_lit"
        )


def raise_closing_while_running(data: NinaData, force: bool) -> None:
    """Refuse closing the cover while the sequencer runs, unless forced: a
    closed cover blanks every light frame the sequence takes after it.
    """
    if data.running and not force:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="flat_panel_close_while_running"
        )


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
    info = DeviceInfo(
        identifiers=device_identifiers(entry_id),
        name=instance_name,
        manufacturer=MANUFACTURER,
        model="Advanced API",
        entry_type=DeviceEntryType.SERVICE,
    )
    # `update`, not `|`: from Home Assistant 2026.11 `DeviceInfo` is not a dict.
    info.update(
        _present(
            sw_version=version.nina_version,
            configuration_url=configuration_url,
        )
    )
    return info


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
    info = DeviceInfo(
        identifiers=device_identifiers(entry_id, kind),
        name=f"{instance_name} {KINDS[kind]}",
        manufacturer=MANUFACTURER,
        via_device_id=via_device_id,
    )
    info.update(
        _present(
            model=meta.name if meta else None,
            sw_version=meta.driver_version if meta else None,
            suggested_area=suggested_area,
        )
    )
    return info


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
                f"http://{entry.data[CONF_HOST]}:{entry.data[CONF_PORT]}"
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

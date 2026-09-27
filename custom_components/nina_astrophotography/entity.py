"""The shared entity base. Entity names derive from their device."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.models import SwitchChannelModel
from .coordinator import NinaConfigEntry, NinaCoordinator
from .device import channel_key, channel_name, channel_of, device_identifiers


class NinaEntity(CoordinatorEntity[NinaCoordinator]):
    """Base for every N.I.N.A. entity.

    `kind` names the equipment the entity belongs to; `None` puts it on the
    hub. Only the device's identifiers are claimed; `device.async_sync_devices`
    writes its metadata.
    """

    _attr_has_entity_name = True

    # Keeps an entity reporting its own device's state available while down.
    _survives_disconnect = False

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        key: str,
        kind: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers=device_identifiers(entry.entry_id, kind)
        )

    @property
    def available(self) -> bool:
        """The rig is reachable and, for equipment, connected."""
        if not super().available:
            return False
        if self._kind is None or self._survives_disconnect:
            return True
        device = getattr(self.coordinator.data.snapshot, self._kind)
        return device is not None and device.connected


class NinaChannelEntity(NinaEntity):
    """Base for one channel of the N.I.N.A. switch device, keyed on its `Id`
    and named by the driver.
    """

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        channel: SwitchChannelModel,
    ) -> None:
        super().__init__(coordinator, entry, channel_key(channel), kind="switch_device")
        self._index = channel.index
        self._attr_name = channel_name(channel)

    @property
    def channel(self) -> SwitchChannelModel | None:
        """This channel in the newest snapshot; `None` once no longer reported."""
        return channel_of(self.coordinator.data, self._index)

    @property
    def channel_value(self) -> float | None:
        """`Value`, never `TargetValue`, which is only what it was asked for."""
        channel = self.channel
        return None if channel is None else channel.value

    @property
    def available(self) -> bool:
        """Unavailable once the driver stops reporting the channel, though the
        switch device is still connected.
        """
        return super().available and self.channel is not None

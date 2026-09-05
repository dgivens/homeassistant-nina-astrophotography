"""The shared entity base.

Bronze common-modules puts it here; Bronze has-entity-name means every entity
name derives from its device, so `_attr_name` is the channel, never the rig.
"""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NinaConfigEntry, NinaCoordinator
from .device import device_identifiers


class NinaEntity(CoordinatorEntity[NinaCoordinator]):
    """Base for every N.I.N.A. entity.

    `kind` names the equipment this entity belongs to — an `EquipmentSnapshot`
    slot — and `None` puts it on the hub, which is where anything session- or
    rig-scoped belongs. Only the identifiers are claimed: the device itself is
    created and kept current by `device.async_sync_devices`, so metadata that is
    missing when the entity is constructed — the ordinary case, since equipment
    is often still connecting — is filled in by a later poll rather than frozen
    here.
    """

    _attr_has_entity_name = True

    # §7.3's one exception: an entity that REPORTS its own device being down
    # must not be made unavailable by it. Set per entity from its descriptor.
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
        """Level 2 of §7.3: the equipment this entity belongs to is connected.

        Level 1 — the rig being reachable at all — is `CoordinatorEntity`'s and
        is inherited through `super()`. A hub entity has no equipment of its
        own and stops there. Level 3, a sentinel reading `unknown` rather than
        `unavailable`, is a value concern of the platform.

        §7.3's one exception is `_survives_disconnect`: the safety monitor's
        own connectivity sensor stays available while the monitor is down, or a
        roof-close automation triggering on `to: "off"` never fires.
        """
        if not super().available:
            return False
        if self._kind is None or self._survives_disconnect:
            return True
        device = getattr(self.coordinator.data.snapshot, self._kind)
        return device is not None and device.connected

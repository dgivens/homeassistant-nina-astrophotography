"""The shared entity base.

Bronze common-modules puts it here; Bronze has-entity-name means every entity
name derives from its device, so `_attr_name` is the channel, never the rig.
"""
from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NinaConfigEntry, NinaCoordinator


class NinaEntity(CoordinatorEntity[NinaCoordinator]):
    """Base for every N.I.N.A. entity.

    Takes the entry, not its id: the instance name lives on
    `entry.runtime_data`, and device linking needs it.
    """

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: NinaCoordinator, entry: NinaConfigEntry, key: str
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"

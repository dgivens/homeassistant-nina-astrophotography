"""Binary sensors.

Ten `*_connected` sensors are gone: a disconnected device makes its entities
unavailable, which is observable in automations (§5.2.1). The safety monitor is
the exception — a disconnected safety monitor would make `safety_unsafe`
unavailable, so a roof-close automation on `to: "off"` never fires, and
`to: "unavailable"` cannot substitute because it conflates
device-disconnected, N.I.N.A.-unreachable, HA-restarting and coordinator-failed.

Read-only mirrors of a switch, number or select are gone too; the survivor's
state is the ACTUAL value, not the last commanded one. `rotator_synced` stays
because sky-PA `Position` is meaningful only when synced.

**`safety_unsafe` is `on` when conditions are UNSAFE.** That is Home
Assistant's `SAFETY` device class — `on` means problem — and it is what the
shipped abort blueprint triggers on. An entity named for safety that reads `on`
for safe is a trap every user hits exactly once, at the worst possible moment.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

# Read-only: nothing here commands the rig, so there is nothing to serialize.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NinaBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor, plus how to read it out of the snapshot.

    `kind` names the child device the entity hangs off (§5.1); `None` puts it on
    the hub. `verified` is False only for the dome, which cannot be validated
    against hardware — a test asserts every dome descriptor carries the marker.
    `survives_disconnect` drops §7.3's level 2 for the one entity whose job is
    to report that its own device is down.
    """

    value: Callable[[NinaData], bool | None]
    kind: str | None
    verified: bool = True
    survives_disconnect: bool = False


def _read(kind: str, field: str) -> Callable[[NinaData], bool | None]:
    """One flag off one equipment model, `None` while the device is absent.

    A disconnected device's readings are already `None` from the mapper, so
    this yields `unknown` rather than a template default.
    """
    def value(data: NinaData) -> bool | None:
        device = getattr(data.snapshot, kind)
        return None if device is None else getattr(device, field)

    return value


def _unsafe(data: NinaData) -> bool | None:
    """`on` means UNSAFE, which is HA's `SAFETY` convention and the blueprint's."""
    monitor = data.snapshot.safety_monitor
    if monitor is None or monitor.is_safe is None:
        return None
    return not monitor.is_safe


DESCRIPTIONS: tuple[NinaBinarySensorDescription, ...] = (
    NinaBinarySensorDescription(
        key="safety_unsafe",
        translation_key="safety_unsafe",
        device_class=BinarySensorDeviceClass.SAFETY,
        kind="safety_monitor",
        value=_unsafe,
    ),
    NinaBinarySensorDescription(
        key="safety_monitor_connected",
        translation_key="safety_monitor_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="safety_monitor",
        survives_disconnect=True,
        value=_read("safety_monitor", "connected"),
    ),
    NinaBinarySensorDescription(
        key="camera_is_exposing",
        translation_key="camera_is_exposing",
        kind="camera",
        value=_read("camera", "is_exposing"),
    ),
    NinaBinarySensorDescription(
        key="mount_at_park",
        translation_key="mount_at_park",
        kind="mount",
        value=_read("mount", "at_park"),
    ),
    NinaBinarySensorDescription(
        key="mount_at_home",
        translation_key="mount_at_home",
        kind="mount",
        value=_read("mount", "at_home"),
    ),
    NinaBinarySensorDescription(
        key="autofocus_failed",
        translation_key="autofocus_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        kind="focuser",
        # Derived from the folded event set on read — there is no timer to leak.
        value=lambda data: data.session.autofocus.failed,
    ),
    NinaBinarySensorDescription(
        key="sequence_running",
        translation_key="sequence_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        kind=None,
        # The §6.2 activity heuristic, never `/sequence/json` node status: node
        # `Status` persists from the loaded file and from prior runs, so an
        # idle rig reports RUNNING nodes with nothing happening.
        value=lambda data: data.imaging,
    ),
    NinaBinarySensorDescription(
        key="focuser_is_moving",
        translation_key="focuser_is_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="focuser",
        value=_read("focuser", "is_moving"),
    ),
    NinaBinarySensorDescription(
        key="filterwheel_is_moving",
        translation_key="filterwheel_is_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="filter_wheel",
        value=_read("filter_wheel", "is_moving"),
    ),
    NinaBinarySensorDescription(
        key="rotator_is_moving",
        translation_key="rotator_is_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="rotator",
        value=_read("rotator", "is_moving"),
    ),
    NinaBinarySensorDescription(
        key="rotator_synced",
        translation_key="rotator_synced",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="rotator",
        # Retained (§5.2.3): unsynced, sky-PA `Position` degenerates toward
        # `MechanicalPosition`, so the position sensors mean nothing without it.
        value=_read("rotator", "synced"),
    ),
    # The dome is spec-derived and untested against hardware (§5.3.1): bare
    # field reads, no derived state, and `verified=False` on every one.
    NinaBinarySensorDescription(
        key="dome_at_park",
        translation_key="dome_at_park",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=_read("dome", "at_park"),
    ),
    NinaBinarySensorDescription(
        key="dome_at_home",
        translation_key="dome_at_home",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=_read("dome", "at_home"),
    ),
    NinaBinarySensorDescription(
        key="dome_slewing",
        translation_key="dome_slewing",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=_read("dome", "slewing"),
    ),
)


class NinaBinarySensor(NinaEntity, BinarySensorEntity):
    """One descriptor, read out of the published snapshot."""

    entity_description: NinaBinarySensorDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key, kind=description.kind)
        self.entity_description = description
        self._survives_disconnect = description.survives_disconnect

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    added: set[str] = set()

    @callback
    def _add_observed() -> None:
        """Create the entities whose equipment the snapshot now carries.

        Gated on the slot being non-`None`, because an identifiers-only
        `DeviceInfo` naming a kind `device.py` has not created leaves the entity
        platform to create a nameless device. Re-run on every publish, so
        equipment that connects hours after Home Assistant started still gets
        its entities (Gold `dynamic-devices`); a slot never returns to `None`,
        so nothing is ever removed here.
        """
        new = [
            NinaBinarySensor(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and (
                description.kind is None
                or getattr(coordinator.data.snapshot, description.kind) is not None
            )
        ]
        if not new:
            return
        added.update(sensor.entity_description.key for sensor in new)
        async_add_entities(new)

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

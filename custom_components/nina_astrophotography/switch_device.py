"""Entities for the N.I.N.A. switch device (SwitchInfo).

The switch device reports two lists: ReadonlySwitches (monitor-only channels,
e.g. voltages and currents from a power box) and WritableSwitches (settable
channels with a Minimum/Maximum/StepSize range). Those become sensors and
number entities respectively, discovered from the first coordinator refresh.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .device import device_info_for
from .coordinator import NinaDataCoordinator
from .helpers import safe

_LOGGER = logging.getLogger(__name__)

def _switch_list(data: Any, key: str) -> list[dict]:
    switches = safe(data, "switch", "Response", key)
    return [s for s in switches if isinstance(s, dict)] if isinstance(switches, list) else []


def _find_by_id(switches: list[dict], switch_id: Any) -> dict | None:
    for entry in switches:
        if entry.get("Id") == switch_id:
            return entry
    return None


class NinaReadonlySwitchSensor(CoordinatorEntity[NinaDataCoordinator], SensorEntity):
    """One monitor-only channel of the switch device."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:gauge"

    def __init__(self, coordinator, entry_id: str, switch_id: Any, name: str) -> None:
        super().__init__(coordinator)
        self._switch_id = switch_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_switch_ro_{switch_id}"
        self._attr_device_info = device_info_for(entry_id, "switch")

    def _entry(self) -> dict | None:
        return _find_by_id(
            _switch_list(self.coordinator.data, "ReadonlySwitches"), self._switch_id
        )

    @property
    def native_value(self):
        entry = self._entry()
        return entry.get("Value") if entry else None

    @property
    def extra_state_attributes(self) -> dict | None:
        entry = self._entry()
        if not entry or not entry.get("Description"):
            return None
        return {"description": entry["Description"]}

    @property
    def available(self) -> bool:
        return super().available and self._entry() is not None


class NinaWritableSwitchNumber(CoordinatorEntity[NinaDataCoordinator], NumberEntity):
    """One settable channel of the switch device."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:tune-variant"

    def __init__(self, coordinator, client, entry_id: str, switch_id: Any,
                 name: str, definition: dict) -> None:
        super().__init__(coordinator)
        self._client = client
        self._switch_id = switch_id
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_switch_rw_{switch_id}"
        self._attr_device_info = device_info_for(entry_id, "switch")
        # Range is fixed by the driver, so it is read once at discovery.
        self._attr_native_min_value = float(definition.get("Minimum", 0) or 0)
        self._attr_native_max_value = float(definition.get("Maximum", 100) or 100)
        step = definition.get("StepSize")
        self._attr_native_step = float(step) if step else 1.0

    def _entry(self) -> dict | None:
        return _find_by_id(
            _switch_list(self.coordinator.data, "WritableSwitches"), self._switch_id
        )

    @property
    def native_value(self) -> float | None:
        entry = self._entry()
        if not entry:
            return None
        try:
            return float(entry.get("Value"))
        except (TypeError, ValueError):
            return None

    @property
    def extra_state_attributes(self) -> dict | None:
        entry = self._entry()
        if not entry:
            return None
        attrs = {}
        if entry.get("Description"):
            attrs["description"] = entry["Description"]
        if entry.get("TargetValue") is not None:
            attrs["target_value"] = entry["TargetValue"]
        return attrs or None

    @property
    def available(self) -> bool:
        return super().available and self._entry() is not None

    async def async_set_native_value(self, value: float) -> None:
        try:
            await self._client.set_switch_value(self._switch_id, value)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.error("Failed to set switch %s to %s: %s", self._switch_id, value, exc)
            return
        await self.coordinator.async_request_refresh()


def async_readonly_switch_sensors(coordinator, entry_id: str) -> list[SensorEntity]:
    """Build a sensor per monitor-only switch channel found at setup."""
    entities = []
    for entry in _switch_list(coordinator.data, "ReadonlySwitches"):
        switch_id = entry.get("Id")
        if switch_id is None:
            continue
        name = entry.get("Name") or f"Readonly {switch_id}"
        entities.append(
            NinaReadonlySwitchSensor(coordinator, entry_id, switch_id, name)
        )
    return entities


def async_writable_switch_numbers(coordinator, client, entry_id: str) -> list[NumberEntity]:
    """Build a number entity per settable switch channel found at setup."""
    entities = []
    for entry in _switch_list(coordinator.data, "WritableSwitches"):
        switch_id = entry.get("Id")
        if switch_id is None:
            continue
        name = entry.get("Name") or f"Writable {switch_id}"
        entities.append(
            NinaWritableSwitchNumber(
                coordinator, client, entry_id, switch_id, name, entry
            )
        )
    return entities

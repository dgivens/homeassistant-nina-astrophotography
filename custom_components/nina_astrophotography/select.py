"""Select entities for N.I.N.A. Astrophotography – filter wheel and tracking mode."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NinaApiClient
from .const import DOMAIN, TrackingMode
from .coordinator import NinaDataCoordinator

_LOGGER = logging.getLogger(__name__)

TRACKING_RATES = [m.label for m in TrackingMode]


def _safe(data: dict, *keys: str, default=None):
    d = data
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
    return d


# ─── Filter Wheel Select ─────────────────────────────────────────────────────

class NinaFilterSelect(CoordinatorEntity[NinaDataCoordinator], SelectEntity):
    """Select entity that maps human-readable filter names to slot indices."""

    _attr_icon = "mdi:filter-variant"

    def __init__(
        self,
        coordinator: NinaDataCoordinator,
        client: NinaApiClient,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_filterwheel_select"
        self._attr_name = "Active Filter"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }

    def _filters(self) -> list[dict]:
        """Return list of filter dicts from coordinator data."""
        if not self.coordinator.data:
            return []
        return _safe(self.coordinator.data, "filterwheel", "Response", "Filters") or []

    @property
    def options(self) -> list[str]:
        filters = self._filters()
        if not filters:
            return ["—"]
        return [f.get("Name", f"Filter {i}") for i, f in enumerate(filters)]

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data:
            return None
        selected = _safe(
            self.coordinator.data, "filterwheel", "Response", "SelectedFilter"
        )
        if selected is None:
            return None
        # Match by name
        name = selected.get("Name")
        if name and name in self.options:
            return name
        # Fallback: match by Id
        fid = selected.get("Id")
        filters = self._filters()
        if fid is not None and fid < len(filters):
            return filters[fid].get("Name", f"Filter {fid}")
        return None

    async def async_select_option(self, option: str) -> None:
        """Change to the named filter."""
        filters = self._filters()
        for i, f in enumerate(filters):
            if f.get("Name") == option:
                await self._client.change_filter(i)
                await self.coordinator.async_request_refresh()
                return
        _LOGGER.warning("Filter '%s' not found in filter wheel", option)

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(
                _safe(self.coordinator.data, "filterwheel", "Response", "Connected")
            )
            if self.coordinator.data
            else False
        )


# ─── Tracking Rate Select ─────────────────────────────────────────────────────

class NinaTrackingRateSelect(CoordinatorEntity[NinaDataCoordinator], SelectEntity):
    """Select entity for mount tracking rate (Sidereal / Lunar / Solar / King)."""

    _attr_icon = "mdi:orbit"
    _attr_options = TRACKING_RATES

    def __init__(
        self,
        coordinator: NinaDataCoordinator,
        client: NinaApiClient,
        entry_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_tracking_rate_select"
        self._attr_name = "Mount Tracking Rate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": "Nighttime Imaging 'N' Astronomy",
            "model": "Advanced API v2",
        }

    @property
    def current_option(self) -> str | None:
        if not self.coordinator.data:
            return None
        rate = _safe(self.coordinator.data, "mount", "Response", "TrackingRate")
        if rate is None:
            return "Sidereal"
        # TrackingRate may come as int (0=Sidereal,1=Lunar,2=Solar,3=King) or string
        if isinstance(rate, int) and 0 <= rate < len(TRACKING_RATES):
            return TRACKING_RATES[rate]
        if isinstance(rate, str) and rate in TRACKING_RATES:
            return rate
        return "Sidereal"

    async def async_select_option(self, option: str) -> None:
        """Switch the tracking rate."""
        await self._client.set_tracking_mode(TrackingMode[option.upper()])
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        return (
            super().available
            and bool(
                _safe(self.coordinator.data, "mount", "Response", "Connected")
            )
            if self.coordinator.data
            else False
        )


# ─── Platform setup ───────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator: NinaDataCoordinator = entry_data["coordinator"]
    client: NinaApiClient = entry_data["client"]

    async_add_entities([
        NinaFilterSelect(coordinator, client, entry.entry_id),
        NinaTrackingRateSelect(coordinator, client, entry.entry_id),
    ])

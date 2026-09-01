"""Select entities for N.I.N.A. — filter wheel, tracking mode and active tab."""
from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import NinaApiClient
from .const import (
    APPLICATION_TABS,
    DOMAIN,
    TRACKING_MODE_TO_INDEX,
    TRACKING_MODES,
)
from .coordinator import NinaDataCoordinator
from .device import HUB, device_info_for
from .helpers import available_filters, safe


_LOGGER = logging.getLogger(__name__)

_NO_OPTION = "—"

class _NinaSelectBase(CoordinatorEntity[NinaDataCoordinator], SelectEntity):
    """Shared plumbing for the N.I.N.A. select entities."""

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    def __init__(self, coordinator, client: NinaApiClient, entry_id: str,
                 unique_suffix: str, name: str, subsystem: str) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{entry_id}_{unique_suffix}"
        self._attr_name = name
        self._attr_device_info = device_info_for(entry_id, subsystem)


class NinaFilterSelect(_NinaSelectBase):
    """Selects a filter by name, resolving to the wheel's filter Id."""

    _attr_icon = "mdi:filter-variant"

    def __init__(self, coordinator, client, entry_id):
        super().__init__(coordinator, client, entry_id, "filterwheel_select",
                         "Active Filter", "filterwheel")

    @property
    def options(self) -> list[str]:
        names = [
            f.get("Name") for f in available_filters(self.coordinator.data or {})
            if f.get("Name")
        ]
        return names or [_NO_OPTION]

    @property
    def current_option(self) -> str | None:
        name = safe(self.coordinator.data, "filterwheel", "Response",
                    "SelectedFilter", "Name")
        return name if name in self.options else None

    async def async_select_option(self, option: str) -> None:
        for entry in available_filters(self.coordinator.data or {}):
            if entry.get("Name") == option:
                # change-filter takes the filter's Id, not its list position.
                await self._client.change_filter(entry.get("Id"))
                await self.coordinator.async_request_refresh()
                return
        _LOGGER.warning("Filter '%s' not found in filter wheel", option)

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        return bool(safe(self.coordinator.data, "filterwheel", "Response", "Connected"))


class NinaTrackingModeSelect(_NinaSelectBase):
    """Selects the mount tracking mode."""

    _attr_icon = "mdi:orbit"
    _attr_options = TRACKING_MODES

    def __init__(self, coordinator, client, entry_id):
        super().__init__(coordinator, client, entry_id, "tracking_rate_select",
                         "Tracking Mode", "mount")

    @property
    def current_option(self) -> str | None:
        # MountInfo reports the mode name; N.I.N.A. spells sidereal "Siderial",
        # and can also report "Custom", which has no set-side equivalent.
        mode = safe(self.coordinator.data, "mount", "Response", "TrackingMode")
        if not isinstance(mode, str):
            return None
        index = TRACKING_MODE_TO_INDEX.get(mode)
        return TRACKING_MODES[index] if index is not None else None

    async def async_select_option(self, option: str) -> None:
        index = TRACKING_MODE_TO_INDEX.get(option)
        if index is None:
            _LOGGER.warning("Unknown tracking mode '%s'", option)
            return
        await self._client.set_tracking_mode(index)
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        return bool(safe(self.coordinator.data, "mount", "Response", "Connected"))


class NinaBinningSelect(_NinaSelectBase):
    """Selects a camera binning mode by name, e.g. 2x2."""

    _attr_icon = "mdi:grid"

    def __init__(self, coordinator, client, entry_id):
        super().__init__(coordinator, client, entry_id, "camera_binning_select",
                         "Binning Mode", "camera")

    def _modes(self) -> list[str]:
        modes = safe(self.coordinator.data, "camera", "Response", "BinningModes")
        if not isinstance(modes, list):
            return []
        return [m.get("Name") for m in modes if isinstance(m, dict) and m.get("Name")]

    @property
    def options(self) -> list[str]:
        return self._modes() or [_NO_OPTION]

    @property
    def current_option(self) -> str | None:
        x = safe(self.coordinator.data, "camera", "Response", "BinX")
        y = safe(self.coordinator.data, "camera", "Response", "BinY")
        if x is None or y is None:
            return None
        current = f"{x}x{y}"
        return current if current in self.options else None

    async def async_select_option(self, option: str) -> None:
        if option == _NO_OPTION:
            return
        await self._client.set_binning(option)
        await self.coordinator.async_request_refresh()

    @property
    def available(self) -> bool:
        if not super().available or not self.coordinator.data:
            return False
        return bool(safe(self.coordinator.data, "camera", "Response", "Connected"))


class NinaProfileSelect(_NinaSelectBase):
    """Switches the active N.I.N.A. profile.

    Profiles are how most rigs model a changed imaging train — a focal reducer
    in or out, a different camera — so switching one here changes focal length,
    and with it image scale and HFR in arcsec.
    """

    _attr_icon = "mdi:account-switch"

    def __init__(self, coordinator, client, entry_id):
        super().__init__(coordinator, client, entry_id, "profile_select",
                         "Active Profile", HUB)

    def _profiles(self) -> list[dict]:
        profiles = safe(self.coordinator.data, "profiles", "Response")
        if not isinstance(profiles, list):
            return []
        return [p for p in profiles if isinstance(p, dict) and p.get("Name")]

    @property
    def options(self) -> list[str]:
        return [p["Name"] for p in self._profiles()] or [_NO_OPTION]

    @property
    def current_option(self) -> str | None:
        for profile in self._profiles():
            if profile.get("IsActive"):
                return profile["Name"]
        # Fall back to the active profile endpoint if none is flagged.
        name = safe(self.coordinator.data, "profile", "Response", "Name")
        return name if name in self.options else None

    async def async_select_option(self, option: str) -> None:
        for profile in self._profiles():
            if profile["Name"] == option and profile.get("Id"):
                await self._client.switch_profile(profile["Id"])
                await self.coordinator.async_request_refresh()
                return
        _LOGGER.warning("Profile '%s' not found", option)

    @property
    def available(self) -> bool:
        return super().available and bool(self._profiles())


class NinaApplicationTabSelect(_NinaSelectBase):
    """Switches the active tab in the N.I.N.A. UI."""

    _attr_icon = "mdi:tab"
    _attr_options = APPLICATION_TABS
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, client, entry_id):
        super().__init__(coordinator, client, entry_id, "application_tab_select",
                         "Active Tab", HUB)
        self._pending: str | None = None

    @property
    def current_option(self) -> str | None:
        # get-tab is not part of the bulk poll, so the last selection is shown
        # until something else changes it in N.I.N.A.
        return self._pending

    async def async_select_option(self, option: str) -> None:
        await self._client.switch_tab(option)
        self._pending = option
        self.async_write_ha_state()


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
        NinaTrackingModeSelect(coordinator, client, entry.entry_id),
        NinaBinningSelect(coordinator, client, entry.entry_id),
        NinaProfileSelect(coordinator, client, entry.entry_id),
        NinaApplicationTabSelect(coordinator, client, entry.entry_id),
    ])

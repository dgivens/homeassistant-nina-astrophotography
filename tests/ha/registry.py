"""Registry lookups the Home Assistant suite shares."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from custom_components.nina_astrophotography.const import DOMAIN


def registered(
    platform: str, registry: er.EntityRegistry, entry, suffix: str
) -> str | None:
    """The entity id claiming this `unique_id` suffix, or None if nothing does.

    The suffix is the 1.4.5 key wherever one survives, which is what an upgraded
    install's registry rows are keyed on.
    """
    return registry.async_get_entity_id(platform, DOMAIN, f"{entry.entry_id}_{suffix}")


def lookup_device(
    hass: HomeAssistant, entry, kind: str | None = None
) -> dr.DeviceEntry | None:
    """The registry entry for one equipment kind, or the hub when `kind` is None."""
    suffix = f"_{kind}" if kind else ""
    return dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}{suffix}"), entry.entry_id
    )


def get_device(hass: HomeAssistant, entry, kind: str | None = None) -> dr.DeviceEntry:
    """As `lookup_device`, failing the test when the device is not registered."""
    found = lookup_device(hass, entry, kind)
    assert found is not None, f"no {kind or 'hub'} device"
    return found

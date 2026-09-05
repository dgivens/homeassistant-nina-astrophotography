"""The device model: a hub, one child per equipment type, metadata in the registry."""
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.nina_astrophotography import async_remove_config_entry_device
from custom_components.nina_astrophotography.const import DOMAIN


def _device(hass: HomeAssistant, entry, kind: str | None = None):
    """The registry entry for one equipment kind, or the hub when `kind` is None."""
    suffix = f"_{kind}" if kind else ""
    return dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, f"{entry.entry_id}{suffix}"), entry.entry_id
    )


async def test_each_equipment_type_is_its_own_device(
    hass: HomeAssistant, loaded_entry
) -> None:
    registry = dr.async_get(hass)
    names = {
        device.name
        for device in dr.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    }
    assert {
        "N.I.N.A. Camera",
        "N.I.N.A. Mount",
        "N.I.N.A. Focuser",
        "N.I.N.A. Filter Wheel",
        "N.I.N.A. Flat Panel",
    } <= names


async def test_children_hang_off_the_hub(hass: HomeAssistant, loaded_entry) -> None:
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, loaded_entry.entry_id)
    hub = _device(hass, loaded_entry)
    assert {device.via_device_id for device in devices if device is not hub} == {hub.id}


async def test_the_hub_carries_the_nina_version(
    hass: HomeAssistant, loaded_entry
) -> None:
    assert _device(hass, loaded_entry).sw_version == "3.2.0.9001"


async def test_driver_metadata_lands_in_the_registry_not_entity_attributes(
    hass: HomeAssistant, loaded_entry
) -> None:
    """`DriverVersion` is the `sw_version` and `Name` the model (§5.1).

    The focuser rather than the camera: this camera reports no `DriverVersion`
    at all, so it cannot show that the field is carried.
    """
    focuser = _device(hass, loaded_entry, "focuser")
    assert (focuser.model, focuser.sw_version) == ("ASCOM.ToupTek.AAF1", "6.5")


async def test_a_device_never_observed_is_not_created(
    hass: HomeAssistant, loaded_entry
) -> None:
    """First sight, not first poll: this rig has never had a dome."""
    assert _device(hass, loaded_entry, "dome") is None


async def test_equipment_seen_for_the_first_time_gets_its_device(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """The guider is down at setup, so its device arrives on a later poll."""
    assert _device(hass, loaded_entry, "guider") is None
    await advance("imaging_guiding")
    assert _device(hass, loaded_entry, "guider").model == "PHD2"


async def test_a_disconnected_device_keeps_its_registry_metadata(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """A down driver reports no identity at all; the registry keeps the last one."""
    await advance("equipment_disconnected")
    assert _device(hass, loaded_entry, "camera").model == "ZWO ASI2600MM Pro"


async def test_a_swapped_driver_updates_the_registry(
    hass: HomeAssistant, loaded_entry, advance
) -> None:
    """The weather source can change under a running rig (§5.2.2)."""
    await advance("weather_openmeteo")
    assert _device(hass, loaded_entry, "weather").model == "OpenMeteo"


@pytest.mark.parametrize(
    ("suffix", "removable"),
    [("_camera", False), ("_dome", True), ("", False), (":camera", True)],
    ids=["still reported", "no longer reported", "the hub", "an older scheme"],
)
async def test_only_equipment_the_rig_no_longer_reports_can_be_deleted(
    hass: HomeAssistant, loaded_entry, suffix: str, removable: bool
) -> None:
    """Gold stale-devices: dynamic creation is paired with removal.

    `entry_id:kind` was `wip/v2.0`'s identifier scheme; nothing will ever claim
    one again, so an upgrade can clear it.
    """
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=loaded_entry.entry_id,
        identifiers={(DOMAIN, f"{loaded_entry.entry_id}{suffix}")},
    )
    assert await async_remove_config_entry_device(hass, loaded_entry, device) is removable

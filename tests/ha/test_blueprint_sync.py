"""The integration installs its blueprints, keeps them current, and flags an
automation still on a copy imported from GitHub.
"""

from pathlib import Path

from homeassistant.components.automation import EVENT_AUTOMATION_RELOADED
from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import SERVICE_RELOAD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
)
import yaml

from custom_components.nina_astrophotography.blueprint_sync import SHIPPED, SHIPPED_DIR
from custom_components.nina_astrophotography.const import DOMAIN
from helpers import state_of
from tests.ha.conftest import MANAGED

FLIP = "meridian_flip_warning.yaml"
FLIP_INPUTS = {
    "flip_sensor": "sensor.rig_mount_time_to_meridian_flip",
    "notify_target": ["notify.phone"],
}
OURS = (
    "https://github.com/dgivens/homeassistant-nina-astrophotography/blob/"
    "bd800b2/blueprints/automation/nina_astrophotography/meridian_flip_warning.yaml"
)


def _shipped(name: str) -> str:
    return (SHIPPED_DIR / name).read_text(encoding="utf-8")


def _stale(name: str) -> str:
    """An earlier version of a blueprint: the same inputs, another mode."""
    return _shipped(name).replace("mode: queued", "mode: single")


def _imported(source_url: str) -> str:
    """An earlier flip warning, as Home Assistant saves an import from
    `source_url`.
    """
    return _stale(FLIP).replace(
        "  domain: automation\n", f"  domain: automation\n  source_url: {source_url}\n"
    )


def _write(hass: HomeAssistant, path: str, content: str) -> None:
    target = Path(hass.config.path("blueprints/automation", path))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _automation(path: str) -> dict:
    return {
        "alias": "Flip warning",
        "use_blueprint": {"path": path, "input": FLIP_INPUTS},
    }


def _configure(hass: HomeAssistant, path: str) -> dict:
    """Write the flip warning on `path` into `configuration.yaml`, which an
    automation reload reads.
    """
    config = {AUTOMATION_DOMAIN: [_automation(path)]}
    Path(hass.config.path("configuration.yaml")).write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    return config


async def _automations(hass: HomeAssistant, path: str) -> None:
    assert await async_setup_component(hass, AUTOMATION_DOMAIN, _configure(hass, path))
    await hass.async_block_till_done()


async def _set_up(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_installs_every_blueprint(
    hass: HomeAssistant, loaded_entry
) -> None:
    managed = Path(hass.config.path(MANAGED))

    assert {name: (managed / name).read_text(encoding="utf-8") for name in SHIPPED} == {
        name: (SHIPPED_DIR / name).read_text(encoding="utf-8") for name in SHIPPED
    }


async def test_a_stale_copy_is_replaced_under_a_running_automation(
    hass: HomeAssistant, config_entry, rig
) -> None:
    _write(hass, f"{DOMAIN}/{FLIP}", _stale(FLIP))
    await _automations(hass, f"{DOMAIN}/{FLIP}")

    await _set_up(hass, config_entry)

    assert state_of(hass, "automation.flip_warning").attributes["mode"] == "queued"


async def test_a_current_copy_reloads_nothing(
    hass: HomeAssistant, config_entry, rig
) -> None:
    for name in SHIPPED:
        _write(hass, f"{DOMAIN}/{name}", _shipped(name))
    await _automations(hass, f"{DOMAIN}/{FLIP}")
    reloads = async_capture_events(hass, EVENT_AUTOMATION_RELOADED)

    await _set_up(hass, config_entry)

    assert reloads == []


async def test_a_failed_install_still_sets_the_rig_up(
    hass: HomeAssistant, config_entry, rig
) -> None:
    # A file where the folder should be: the install cannot create it.
    _write(hass, DOMAIN, "")

    await _set_up(hass, config_entry)

    assert config_entry.state is ConfigEntryState.LOADED


@pytest.mark.parametrize(
    ("source_url", "raised"),
    [(OURS, True), ("https://github.com/someone/else/blob/main/flip.yaml", False)],
    ids=["ours", "another-repository"],
)
async def test_an_automation_on_an_imported_copy_raises_a_repair(
    hass: HomeAssistant, config_entry, rig, source_url: str, raised: bool
) -> None:
    _write(hass, f"dgivens/{FLIP}", _imported(source_url))
    await _automations(hass, f"dgivens/{FLIP}")

    await _set_up(hass, config_entry)

    issue = ir.async_get(hass).async_get_issue(
        DOMAIN, "imported_blueprint_dgivens_meridian_flip_warning_yaml"
    )
    assert (issue is not None) is raised


async def test_the_repair_clears_once_the_automation_uses_the_managed_copy(
    hass: HomeAssistant, config_entry, rig
) -> None:
    _write(hass, f"dgivens/{FLIP}", _imported(OURS))
    await _automations(hass, f"dgivens/{FLIP}")
    await _set_up(hass, config_entry)

    _configure(hass, f"{DOMAIN}/{FLIP}")
    await hass.services.async_call(AUTOMATION_DOMAIN, SERVICE_RELOAD, blocking=True)
    await hass.async_block_till_done()

    assert not [
        issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN
    ]

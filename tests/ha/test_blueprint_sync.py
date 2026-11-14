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

from custom_components.nina_astrophotography.blueprint_sync import (
    MANAGED_FOLDER,
    SHIPPED,
    SHIPPED_DIR,
)
from custom_components.nina_astrophotography.const import DOMAIN
from helpers import state_of
from tests.ha.conftest import MANAGED

FLIP = "meridian_flip_warning.yaml"
MANAGED_FLIP = f"{MANAGED_FOLDER}/{FLIP}"
IMPORTED_FLIP = f"dgivens/{FLIP}"
OURS = (
    "https://github.com/dgivens/homeassistant-nina-astrophotography/blob/"
    "bd800b2/blueprints/automation/nina_astrophotography/meridian_flip_warning.yaml"
)


def _repairs(hass: HomeAssistant) -> list[str]:
    """The imported paths an open repair names."""
    return [
        issue.translation_placeholders["imported"]
        for issue in ir.async_get(hass).issues.values()
        if issue.domain == DOMAIN
        and issue.translation_key == "imported_blueprint"
        and issue.translation_placeholders
    ]


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


def _configure(hass: HomeAssistant, path: str) -> dict:
    """Write the flip warning on `path` into `configuration.yaml`, which an
    automation reload reads.
    """
    inputs = {
        "flip_sensor": "sensor.rig_mount_time_to_meridian_flip",
        "notify_target": ["notify.phone"],
    }
    config = {
        AUTOMATION_DOMAIN: [
            {"alias": "Flip warning", "use_blueprint": {"path": path, "input": inputs}}
        ]
    }
    Path(hass.config.path("configuration.yaml")).write_text(
        yaml.safe_dump(config), encoding="utf-8"
    )
    return config


async def _set_up_automation(hass: HomeAssistant, path: str) -> None:
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
        name: _shipped(name) for name in SHIPPED
    }


async def test_a_stale_copy_is_replaced_under_a_loaded_automation(
    hass: HomeAssistant, config_entry, rig
) -> None:
    _write(hass, MANAGED_FLIP, _stale(FLIP))
    await _set_up_automation(hass, MANAGED_FLIP)

    await _set_up(hass, config_entry)

    assert state_of(hass, "automation.flip_warning").attributes["mode"] == "queued"


async def test_a_copy_that_is_not_text_is_replaced(
    hass: HomeAssistant, config_entry, rig
) -> None:
    damaged = Path(hass.config.path(MANAGED, FLIP))
    damaged.parent.mkdir(parents=True)
    damaged.write_bytes(b"\xff\xfe")

    await _set_up(hass, config_entry)

    assert damaged.read_text(encoding="utf-8") == _shipped(FLIP)


async def test_a_current_copy_reloads_nothing(
    hass: HomeAssistant, config_entry, rig
) -> None:
    for name in SHIPPED:
        _write(hass, f"{MANAGED_FOLDER}/{name}", _shipped(name))
    await _set_up_automation(hass, MANAGED_FLIP)
    reloads = async_capture_events(hass, EVENT_AUTOMATION_RELOADED)

    await _set_up(hass, config_entry)

    assert reloads == []


async def test_a_failed_install_still_sets_the_rig_up(
    hass: HomeAssistant, config_entry, rig
) -> None:
    # A file where the folder should be: the install cannot create it.
    _write(hass, MANAGED_FOLDER, "")

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
    _write(hass, IMPORTED_FLIP, _imported(source_url))
    await _set_up_automation(hass, IMPORTED_FLIP)

    await _set_up(hass, config_entry)

    assert _repairs(hass) == ([IMPORTED_FLIP] if raised else [])


async def test_the_repair_clears_once_the_automation_uses_the_managed_copy(
    hass: HomeAssistant, config_entry, rig
) -> None:
    _write(hass, IMPORTED_FLIP, _imported(OURS))
    await _set_up_automation(hass, IMPORTED_FLIP)
    await _set_up(hass, config_entry)

    _configure(hass, MANAGED_FLIP)
    await hass.services.async_call(AUTOMATION_DOMAIN, SERVICE_RELOAD, blocking=True)
    await hass.async_block_till_done()

    assert _repairs(hass) == []

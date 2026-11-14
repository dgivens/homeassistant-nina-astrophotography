"""Install the shipped automation blueprints, and keep them current.

Home Assistant never updates a blueprint once it is in the config directory,
so an automation would otherwise run the version from the day it was added,
whatever the integration has since fixed. The managed folder belongs to the
integration: a local edit there is overwritten on the next start that ships a
different version, and **Take control** on an automation is how to customise
one.
"""

import asyncio
import hashlib
import logging
from pathlib import Path

from homeassistant.components.automation import (
    EVENT_AUTOMATION_RELOADED,
    blueprint_in_automation,
)
from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.const import SERVICE_RELOAD
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util.file import write_utf8_file

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SHIPPED_DIR = Path(__file__).parent / "blueprints"
# Home Assistant imports an integration in the executor, so this glob does not
# block the event loop.
SHIPPED = frozenset(path.name for path in SHIPPED_DIR.glob("*.yaml"))
# The folder under `<config>/blueprints/automation/`, and so the prefix of
# every managed blueprint's path.
MANAGED_FOLDER = DOMAIN

# The repository a copy imported from GitHub names in its `source_url`,
# whichever ref and host the import used.
_IMPORTED_FROM = "dgivens/homeassistant-nina-astrophotography/"
_ISSUE_PREFIX = "imported_blueprint_"


def _install(target: Path, written: list[str]) -> None:
    """Copy each shipped blueprint into `target`, rewriting only a file whose
    bytes differ, and append each name written to `written`, which holds them
    even if a later file fails.
    """
    target.mkdir(parents=True, exist_ok=True)
    for name in sorted(SHIPPED):
        content = (SHIPPED_DIR / name).read_bytes()
        installed = target / name
        if installed.is_file() and installed.read_bytes() == content:
            continue
        write_utf8_file(str(installed), content, mode="wb")
        written.append(name)


async def async_install_blueprints(hass: HomeAssistant) -> None:
    """Bring the managed blueprints up to the shipped ones, and reload the
    automations if any changed.

    A failure is logged, not raised: the rig is still worth setting up.
    """
    target = Path(hass.config.path("blueprints", AUTOMATION_DOMAIN, MANAGED_FOLDER))
    written: list[str] = []
    try:
        await hass.async_add_executor_job(_install, target, written)
    except (OSError, HomeAssistantError) as err:
        _LOGGER.warning("Could not install the blueprints in %s: %s", target, err)
    if not written:
        return
    # A copy placed here by hand, edits included, is among these.
    _LOGGER.info("Updated the blueprints %s in %s", ", ".join(written), target)
    # The reload empties Home Assistant's blueprint cache, so the automations
    # rebuild from the new files; one whose result is unchanged keeps running.
    if hass.services.has_service(AUTOMATION_DOMAIN, SERVICE_RELOAD):
        await hass.services.async_call(AUTOMATION_DOMAIN, SERVICE_RELOAD)


async def async_track_imported_copies(hass: HomeAssistant) -> None:
    """Raise a repair for each imported copy an automation still uses, now and
    whenever the automations reload, which is also when one is saved.
    """

    # Serialised, so a check from an earlier reload cannot finish last.
    lock = asyncio.Lock()

    async def _check(_: Event | None = None) -> None:
        async with lock:
            await _async_raise_imported_copy_issues(hass)

    hass.bus.async_listen(EVENT_AUTOMATION_RELOADED, _check)
    await _check()


async def _async_raise_imported_copy_issues(hass: HomeAssistant) -> None:
    """Raise a repair for each imported copy an automation uses, naming the
    managed copy to move it onto.

    The automation is never rewritten: the user changes its blueprint path.
    Home Assistant keeps an automation whose substituted config is unchanged,
    and with it the path it was built from, so moving one onto a copy that
    differs only in metadata or comments clears its repair, and lets the old
    copy be deleted, only at the next restart.
    """
    users: dict[str, list[str]] = {}
    for entity_id in hass.states.async_entity_ids(AUTOMATION_DOMAIN):
        path = blueprint_in_automation(hass, entity_id)
        if path is None or path.startswith(f"{MANAGED_FOLDER}/"):
            continue
        if Path(path).name in SHIPPED:
            users.setdefault(path, []).append(entity_id)

    blueprints = async_get_blueprints(hass)
    imported: dict[str, list[str]] = {}
    for path, entity_ids in users.items():
        try:
            blueprint = await blueprints.async_get_blueprint(path)
        except HomeAssistantError:  # a copy that no longer loads
            continue
        if _IMPORTED_FROM in (blueprint.metadata.get("source_url") or ""):
            imported[path] = entity_ids

    _sync_issues(hass, imported)


@callback
def _sync_issues(hass: HomeAssistant, imported: dict[str, list[str]]) -> None:
    """Make the open imported-copy repairs exactly the ones for `imported`."""
    wanted = {_issue_id(path): path for path in imported}
    registry = ir.async_get(hass)
    for domain, issue_id in list(registry.issues):
        if (
            domain == DOMAIN
            and issue_id.startswith(_ISSUE_PREFIX)
            and issue_id not in wanted
        ):
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue_id, path in wanted.items():
        names = [
            state.name if (state := hass.states.get(entity_id)) else entity_id
            for entity_id in imported[path]
        ]
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="imported_blueprint",
            translation_placeholders={
                "automations": ", ".join(sorted(names)),
                "imported": path,
                "managed": f"{MANAGED_FOLDER}/{Path(path).name}",
            },
        )


def _issue_id(path: str) -> str:
    """An id per path; a hash, since paths differing only in case or
    punctuation are distinct files.
    """
    return _ISSUE_PREFIX + hashlib.sha256(path.encode()).hexdigest()[:16]

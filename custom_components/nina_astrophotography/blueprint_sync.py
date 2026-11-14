"""Install the shipped automation blueprints, and keep them current.

Home Assistant never updates a blueprint once it is in the config directory,
so an automation would otherwise run the version from the day it was added,
whatever the integration has since fixed. The managed folder belongs to the
integration: a local edit there is overwritten on the next start that ships a
different version, and **Take control** on an automation is how to customise
one.
"""

import logging
from pathlib import Path
import re

from homeassistant.components.automation import (
    EVENT_AUTOMATION_RELOADED,
    blueprint_in_automation,
)
from homeassistant.components.automation.const import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.components.automation.helpers import async_get_blueprints
from homeassistant.components.blueprint.errors import BlueprintException
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
_IMPORTED_FROM = re.compile(r"\bdgivens/homeassistant-nina-astrophotography/")
_ISSUE_PREFIX = "imported_blueprint_"


def _install(source: Path, target: Path) -> bool:
    """Copy each blueprint in `source` into `target`, rewriting only a file
    whose content differs. Returns whether anything was written.
    """
    changed = False
    for name in sorted(SHIPPED):
        content = (source / name).read_text(encoding="utf-8")
        installed = target / name
        if installed.is_file() and installed.read_text(encoding="utf-8") == content:
            continue
        target.mkdir(parents=True, exist_ok=True)
        write_utf8_file(str(installed), content)
        changed = True
    return changed


async def async_install_blueprints(hass: HomeAssistant) -> None:
    """Bring the managed blueprints up to the shipped ones, and reload the
    automations if any changed.

    A failure is logged, not raised: the rig is still worth setting up.
    """
    target = Path(hass.config.path("blueprints", AUTOMATION_DOMAIN, MANAGED_FOLDER))
    try:
        changed = await hass.async_add_executor_job(_install, SHIPPED_DIR, target)
    except (OSError, HomeAssistantError) as err:
        _LOGGER.warning("Could not install the blueprints in %s: %s", target, err)
        return
    # The reload empties Home Assistant's blueprint cache, so the automations
    # rebuild from the new files; one whose result is unchanged keeps running.
    if changed and hass.services.has_service(AUTOMATION_DOMAIN, SERVICE_RELOAD):
        await hass.services.async_call(AUTOMATION_DOMAIN, SERVICE_RELOAD)


async def async_track_imported_copies(hass: HomeAssistant) -> None:
    """Raise a repair for each imported copy an automation still uses, now and
    whenever the automations reload, which is also when one is saved.
    """

    async def _check(_: Event | None = None) -> None:
        await _async_raise_imported_copy_issues(hass)

    hass.bus.async_listen(EVENT_AUTOMATION_RELOADED, _check)
    await _check()


async def _async_raise_imported_copy_issues(hass: HomeAssistant) -> None:
    """Point every automation on an imported copy at the managed one.

    The automation is never rewritten: the user changes its blueprint path.
    Home Assistant keeps an automation whose substituted config is unchanged,
    and with it the path it was built from, so moving one onto a copy of
    identical content clears its repair only at the next restart.
    """
    users: dict[str, list[str]] = {}
    for entity_id in hass.states.async_entity_ids(AUTOMATION_DOMAIN):
        path = blueprint_in_automation(hass, entity_id)
        if path is None or path.startswith(f"{MANAGED_FOLDER}/"):
            continue
        if Path(path).name in SHIPPED:
            users.setdefault(path, []).append(entity_id)

    imported: dict[str, list[str]] = {}
    for path, entity_ids in users.items():
        try:
            blueprint = await async_get_blueprints(hass).async_get_blueprint(path)
        except BlueprintException:
            continue
        if _IMPORTED_FROM.search(blueprint.metadata.get("source_url") or ""):
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
    return _ISSUE_PREFIX + re.sub(r"[^a-z0-9]+", "_", path.lower()).strip("_")

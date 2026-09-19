"""Serve the bundled Lovelace cards and register them as dashboard resources.

Deliberately NOT under `api/`: same reasoning as `views.py` — this imports
`homeassistant`, and `api/` is the HA-free seam.
"""

import logging
from pathlib import Path

from homeassistant.components.http.server import StaticPathConfig
from homeassistant.components.lovelace.const import CONF_RESOURCE_TYPE_WS, LOVELACE_DATA
from homeassistant.components.lovelace.resources import (
    ResourceStorageCollection,
    ResourceYAMLCollection,
)
from homeassistant.const import CONF_ID, CONF_URL
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# A distinct static-file prefix, not bare `/nina_astrophotography/*` — that
# namespace is reserved for whatever else the integration serves later, like
# a sidebar panel.
URL_PREFIX = "/nina_astrophotography_static"
WWW_DIR = Path(__file__).parent / "www"
# Fixed rather than a directory listing: a wrong or half-written file in
# `www/` must not silently become an installable Lovelace resource.
CARD_FILENAMES = (
    "nina-autofocus-card.js",
    "nina-frame-stats-card.js",
    "nina-image-panel-card.js",
    "nina-observatory-card.js",
    "nina-sky-map-card.js",
    "nina-weather-card.js",
)
CARD_URLS = tuple(f"{URL_PREFIX}/{filename}" for filename in CARD_FILENAMES)

# `hass.data` key: set when a config entry's removal deletes the registered
# resources, so the next entry to set up knows to redo it. `async_setup` only
# runs once per Home Assistant process — a rig removed and then re-added
# without a restart would otherwise never see its cards registered again,
# since the domain is already marked set up and `async_setup` is not re-run.
_RESOURCES_REMOVED = "nina_astrophotography_frontend_resources_removed"


async def _async_ensure_loaded(resources: ResourceStorageCollection) -> None:
    """A storage collection answers `async_items()` empty until it has read
    its store, which would make every card look unregistered — duplicating
    them on registration, or hiding them from removal — each restart. Home
    Assistant's own ensure-loaded step is private.
    """
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True


async def async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve `www/` and register each card as a Lovelace resource — cosmetic,
    unlike the actions and the image proxy `async_setup` also registers, so
    nothing in here is allowed to fail the integration: a corrupt
    `.storage/lovelace_resources`, or a future HA schema change rejecting our
    payload, must cost a dashboard card, not every sensor and action.
    """
    try:
        await _async_register_frontend_resources(hass)
    except Exception:  # Broad on purpose: see the docstring.
        _LOGGER.exception("Could not register the bundled Lovelace cards")


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve `www/` and register each card as a Lovelace resource, once,
    before any entry is set up — mirrors `async_register_views`.

    Static routes carry no auth — a browser fetches a resource module with no
    token, same as `/local/` — so this, like `/local/`, is public. Only
    `CARD_FILENAMES` becomes a Lovelace resource; every file physically under
    `www/` is served regardless, so nothing non-public belongs in it.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_PREFIX, str(WWW_DIR), False)]
    )

    # `after_dependencies` in `manifest.json` orders us after `lovelace` when
    # it's present, but lovelace is itself optional — normally absent only on
    # a `configuration.yaml` built without `default_config`. The cards are
    # still served; nothing can add them to a dashboard automatically.
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        _LOGGER.warning(
            "Lovelace isn't set up, so the bundled cards can't register "
            "themselves as dashboard resources. Add `default_config:` or "
            "`lovelace:` to configuration.yaml, or add them under "
            "Resources yourself."
        )
        return
    resources = lovelace_data.resources

    # Checked, and returned, before anything storage-only: a YAML collection
    # has no `async_load` to narrow to below it.
    if isinstance(resources, ResourceYAMLCollection):
        registered = {item[CONF_URL] for item in resources.async_items()}
        if missing := [url for url in CARD_URLS if url not in registered]:
            _LOGGER.warning(
                "Lovelace resources are managed through YAML "
                "(`lovelace: mode: yaml` in configuration.yaml), so the "
                "bundled cards can't register themselves. Add these under "
                "the `resources:` key of your `lovelace:` config, or switch "
                "to `resource_mode: storage` to keep YAML dashboards while "
                "letting resources register automatically:\n%s",
                "\n".join(f'  - url: "{url}"\n    type: module' for url in missing),
            )
        return

    await _async_ensure_loaded(resources)

    registered = {item[CONF_URL] for item in resources.async_items()}
    for url in CARD_URLS:
        if url in registered:
            continue
        await resources.async_create_item(
            {CONF_RESOURCE_TYPE_WS: "module", CONF_URL: url}
        )
        _LOGGER.debug("Registered %s as a Lovelace resource", url)


async def async_unregister_frontend_resources(hass: HomeAssistant) -> None:
    """Delete the bundled Lovelace resources, once the last config entry for
    this integration is removed.

    Cosmetic, like registration: nothing here is allowed to fail the entry
    removal, so a corrupt store or a future HA schema change costs stale
    resource rows, not the removal itself.
    """
    try:
        await _async_unregister_frontend_resources(hass)
    except Exception:  # Broad on purpose: see the docstring.
        _LOGGER.exception("Could not remove the bundled Lovelace cards")


async def _async_unregister_frontend_resources(hass: HomeAssistant) -> None:
    """Delete each card's Lovelace resource, storage collections only.

    A YAML collection has no delete — those resources are the operator's
    file to edit, same reasoning as the warning in registration — so this
    returns before touching anything storage-only.
    """
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return
    resources = lovelace_data.resources
    if isinstance(resources, ResourceYAMLCollection):
        return

    await _async_ensure_loaded(resources)

    for item in resources.async_items():
        if item[CONF_URL] in CARD_URLS:
            await resources.async_delete_item(item[CONF_ID])
    hass.data[_RESOURCES_REMOVED] = True


async def async_ensure_frontend_resources(hass: HomeAssistant) -> None:
    """Re-register the bundled cards if a previous entry's removal deleted
    them, so a rig removed and re-added without a restart still gets its
    dashboard cards back. A no-op the rest of the time.
    """
    if hass.data.pop(_RESOURCES_REMOVED, False):
        await async_register_frontend_resources(hass)

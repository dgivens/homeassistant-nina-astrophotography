"""Serve the bundled Lovelace cards and register them as dashboard resources."""

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

URL_PREFIX = "/nina_astrophotography_static"
WWW_DIR = Path(__file__).parent / "www"
# Listed, so no other file in `www/` becomes a Lovelace resource.
CARD_FILENAMES = (
    "nina-autofocus-card.js",
    "nina-frame-stats-card.js",
    "nina-image-panel-card.js",
    "nina-observatory-card.js",
    "nina-sky-map-card.js",
    "nina-weather-card.js",
)
CARD_URLS = tuple(f"{URL_PREFIX}/{filename}" for filename in CARD_FILENAMES)

# Set when removing the last entry deletes the resources, so the next entry
# set up re-registers them: `async_setup` runs once per process.
_RESOURCES_REMOVED = "nina_astrophotography_frontend_resources_removed"


async def _async_ensure_loaded(resources: ResourceStorageCollection) -> None:
    """Load the collection, which answers `async_items()` empty until then.

    Home Assistant's own ensure-loaded step is private.
    """
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True


async def async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve `www/` and register each card as a Lovelace resource.

    Never fails the integration: a broken resource store costs the cards,
    not the entities and actions.
    """
    try:
        await _async_register_frontend_resources(hass)
    except Exception:  # Broad on purpose: see the docstring.
        _LOGGER.exception("Could not register the bundled Lovelace cards")


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Serve `www/` and register each card as a Lovelace resource.

    Like `/local/`, the static route is public, as a browser fetches a module
    with no token; nothing private belongs in `www/`.
    """
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_PREFIX, str(WWW_DIR), False)]
    )

    # Lovelace is absent from a configuration without `default_config`.
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

    # A YAML collection cannot be written to.
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
    """Delete the bundled Lovelace resources. Never fails the entry removal."""
    try:
        await _async_unregister_frontend_resources(hass)
    except Exception:  # Broad on purpose: see the docstring.
        _LOGGER.exception("Could not remove the bundled Lovelace cards")


async def _async_unregister_frontend_resources(hass: HomeAssistant) -> None:
    """Delete each card's Lovelace resource; YAML resources are the user's."""
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
    """Re-register the bundled cards if removing an entry deleted them."""
    if hass.data.pop(_RESOURCES_REMOVED, False):
        await async_register_frontend_resources(hass)

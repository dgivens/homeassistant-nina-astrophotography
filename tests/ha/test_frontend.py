"""The bundled Lovelace cards: served statically and self-registered.

The byte-for-byte check below is only to prove `URL_PREFIX` and `WWW_DIR`
actually point at each other — not a test of Home Assistant's static route
itself. What's ours beyond that: which files are exposed, that registering
them is idempotent, that it degrades gracefully without lovelace, and that a
failure in it can't take the rest of the integration down with it.
"""

import re

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import CONF_HOST, CONF_PORT, DOMAIN
from custom_components.nina_astrophotography.frontend import (
    CARD_FILENAMES,
    CARD_URLS,
    URL_PREFIX,
    WWW_DIR,
    async_register_frontend_resources,
)

FRONTEND_LOGGER = "custom_components.nina_astrophotography.frontend"


@pytest.fixture
async def lovelace_entry(hass, config_entry, nina_responses) -> None:
    """The entry set up on an instance that has lovelace.

    Lovelace first: registration happens in `async_setup`, which is the
    ordering `after_dependencies` buys us on a real instance.
    """
    assert await async_setup_component(hass, "lovelace", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


@pytest.fixture
async def yaml_lovelace_entry(hass, config_entry, nina_responses) -> None:
    """The entry set up on an instance whose dashboards are YAML-managed."""
    assert await async_setup_component(
        hass, "lovelace", {"lovelace": {"resource_mode": "yaml", "resources": []}}
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


def _resource_urls(hass) -> list[str]:
    return [item["url"] for item in hass.data["lovelace"].resources.async_items()]


async def test_a_card_is_served_byte_for_byte_at_its_url(
    hass, loaded_entry, hass_client
) -> None:
    client = await hass_client()
    resp = await client.get(f"{URL_PREFIX}/nina-observatory-card.js")
    assert resp.status == 200
    assert "javascript" in resp.content_type
    assert await resp.read() == (WWW_DIR / "nina-observatory-card.js").read_bytes()


async def test_whatever_a_card_imports_is_served_at_that_path(
    hass, loaded_entry, hass_client
) -> None:
    """A card's `import "./x.js"` is a plain browser fetch against this same
    static route, and a module that fails to load takes its importer down with
    it — so a 404 here is a blank card, not a missing helper.

    The specifier is read out of the card because the point is that the two
    agree.
    """
    card = (WWW_DIR / "nina-observatory-card.js").read_text(encoding="utf-8")
    imported = re.findall(r'^import .*? from "\./([\w.-]+\.js)";$', card, re.MULTILINE)
    assert imported, "the card no longer imports anything — drop this test"

    client = await hass_client()
    for filename in imported:
        resp = await client.get(f"{URL_PREFIX}/{filename}")
        assert resp.status == 200, filename
        assert "javascript" in resp.content_type


async def test_setup_does_not_crash_when_lovelace_is_not_set_up(
    hass, loaded_entry
) -> None:
    """The default, HA-free-of-lovelace test instance is the case this
    guards: `async_setup` must not raise just because nothing configured
    dashboards.
    """
    assert "lovelace" not in hass.data
    assert loaded_entry.state is ConfigEntryState.LOADED


async def test_a_registration_failure_does_not_sink_the_integration(
    hass, config_entry, nina_responses, monkeypatch, caplog
) -> None:
    """Registering a Lovelace resource is cosmetic; the entry, its devices
    and its entities are not. A storage read that raises — a corrupt
    `.storage/lovelace_resources`, say — must not fail `async_setup`.
    """
    assert await async_setup_component(hass, "lovelace", {})

    async def _boom(self):
        raise OSError("corrupt store")

    monkeypatch.setattr(
        "homeassistant.components.lovelace.resources.ResourceStorageCollection.async_load",
        _boom,
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert any(
        record.levelname == "ERROR" and record.name == FRONTEND_LOGGER
        for record in caplog.records
    )


async def test_each_card_is_registered_as_a_lovelace_resource(
    hass, lovelace_entry
) -> None:
    assert set(_resource_urls(hass)) == set(CARD_URLS)


async def test_registering_twice_does_not_duplicate_resources(
    hass, lovelace_entry
) -> None:
    """Guards a second call in the same run, e.g. two config entries each
    triggering `async_setup` — not the restart case, which needs the
    collection to start unloaded (`test_a_restart_does_not_duplicate...`
    below); by this point `lovelace_entry` has already loaded it.
    """
    await async_register_frontend_resources(hass)

    assert sorted(_resource_urls(hass)) == sorted(CARD_URLS)


async def test_a_restart_does_not_duplicate_persisted_resources(
    hass, hass_storage, config_entry, nina_responses
) -> None:
    """The real restart case: the store already has every card from a
    previous run, and `resources.loaded` starts `False` again — a fresh
    `ResourceStorageCollection`, same as a real Home Assistant start. Without
    the `resources.loaded` check in `async_register_frontend_resources`,
    `async_items()` would read empty before the store loads and duplicate
    all six.
    """
    hass_storage["lovelace_resources"] = {
        "version": 1,
        "minor_version": 1,
        "key": "lovelace_resources",
        "data": {
            "items": [
                {"id": f"seeded{i}", "type": "module", "url": url}
                for i, url in enumerate(CARD_URLS)
            ]
        },
    }
    assert await async_setup_component(hass, "lovelace", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert sorted(_resource_urls(hass)) == sorted(CARD_URLS)


async def test_yaml_managed_resources_are_left_to_the_operator(
    hass, config_entry, nina_responses, caplog
) -> None:
    """A YAML-mode collection has no create: the resources live in the
    operator's file, so the cards are named in one warning instead.

    Set up inline rather than through `yaml_lovelace_entry`: `caplog` has to
    be active before setup runs, and a fixture dependency executes before the
    test body regardless of parameter order.
    """
    assert await async_setup_component(
        hass, "lovelace", {"lovelace": {"resource_mode": "yaml", "resources": []}}
    )
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _resource_urls(hass) == []
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING" and record.name == FRONTEND_LOGGER
    ]
    assert len(warnings) == 1
    assert all(url in warnings[0] for url in CARD_URLS)


def test_every_shipped_card_file_is_in_card_filenames() -> None:
    """`CARD_FILENAMES` is a fixed allowlist, not a directory listing — this
    is what keeps it from silently drifting out of sync with `www/`.

    A module the cards import is not a card and stays out of the allowlist: it
    defines no custom element, so registering it would load it on every
    dashboard to no effect. Naming those here rather than widening
    `CARD_FILENAMES` means a new file in `www/` still has to be declared one
    thing or the other.
    """
    assert {path.name for path in WWW_DIR.glob("*.js")} == set(CARD_FILENAMES) | {
        "nina-card-config.js",
        "nina-entity-resolver.js",
    }


# ─── Removal (#70) ───────────────────────────────────────────────────────────


async def test_removing_the_last_entry_deletes_its_resources(
    hass, config_entry, lovelace_entry
) -> None:
    assert set(_resource_urls(hass)) == set(CARD_URLS)

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert _resource_urls(hass) == []


async def test_removing_the_entry_does_not_crash_when_lovelace_was_never_set_up(
    hass, loaded_entry
) -> None:
    assert "lovelace" not in hass.data

    await hass.config_entries.async_remove(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_removing_one_of_two_entries_keeps_the_resources(
    hass, config_entry, nina_responses
) -> None:
    """A multi-rig install shouldn't lose its cards just because one rig was
    uninstalled — only the last entry going should take the resources with it.
    """
    assert await async_setup_component(hass, "lovelace", {})
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)

    second_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Second Rig",
        data={CONF_HOST: "other.local", CONF_PORT: 1888},
        unique_id="other.local:1888",
        entry_id="01JTESTENTRY0000000000001",
    )
    second_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second_entry.entry_id)
    await hass.async_block_till_done()
    assert set(_resource_urls(hass)) == set(CARD_URLS)

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert set(_resource_urls(hass)) == set(CARD_URLS)

    await hass.config_entries.async_remove(second_entry.entry_id)
    await hass.async_block_till_done()
    assert _resource_urls(hass) == []


async def test_removing_the_entry_leaves_yaml_managed_resources_alone(
    hass, config_entry, yaml_lovelace_entry
) -> None:
    """A YAML collection has no delete, mirroring the registration side."""
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []


async def test_re_adding_after_the_last_entry_was_removed_reregisters_resources(
    hass, config_entry, lovelace_entry
) -> None:
    """`async_setup` only runs once per Home Assistant process — a rig
    removed and then re-added without a restart must still get its cards
    back, or every card silently 404s until the next restart.
    """
    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _resource_urls(hass) == []

    second_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Re-added Rig",
        data={CONF_HOST: "nina.local", CONF_PORT: 1888},
        unique_id="nina.local:1888",
        entry_id="01JTESTENTRY0000000000002",
    )
    second_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second_entry.entry_id)
    await hass.async_block_till_done()

    assert set(_resource_urls(hass)) == set(CARD_URLS)


async def test_a_removal_failure_does_not_block_entry_removal(
    hass, config_entry, lovelace_entry, monkeypatch, caplog
) -> None:
    """Deleting a Lovelace resource is cosmetic, same as registering one — a
    corrupt store here must not leave the config entry stuck.
    """

    async def _boom(self, item_id):
        raise OSError("corrupt store")

    monkeypatch.setattr(
        "homeassistant.components.lovelace.resources.ResourceStorageCollection"
        ".async_delete_item",
        _boom,
    )

    await hass.config_entries.async_remove(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    assert any(
        record.levelname == "ERROR" and record.name == FRONTEND_LOGGER
        for record in caplog.records
    )

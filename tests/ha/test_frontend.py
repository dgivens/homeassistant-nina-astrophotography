"""The bundled Lovelace cards: served statically and self-registered.

The byte-for-byte check below is only to prove `URL_PREFIX` and `WWW_DIR`
actually point at each other — not a test of Home Assistant's static route
itself. What's ours beyond that: which files are exposed, that registering
them is idempotent, that it degrades gracefully without lovelace, and that a
failure in it can't take the rest of the integration down with it.
"""

from homeassistant.config_entries import ConfigEntryState
from homeassistant.setup import async_setup_component
import pytest

from custom_components.nina_astrophotography.frontend import (
    CARD_FILENAMES,
    URL_PREFIX,
    WWW_DIR,
    async_register_frontend_resources,
)

CARD_URLS = {f"{URL_PREFIX}/{filename}" for filename in CARD_FILENAMES}
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
    assert set(_resource_urls(hass)) == CARD_URLS


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
    """
    assert {path.name for path in WWW_DIR.glob("*.js")} == set(CARD_FILENAMES)

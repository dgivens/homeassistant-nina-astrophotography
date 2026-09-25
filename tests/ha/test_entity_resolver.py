"""`www/nina-entity-resolver.js` against real registries from the fake rig.

The module runs in a browser, so `resolve_entities.mjs` runs the shipped file
under node over a snapshot of what Home Assistant would send one. A Python
reimplementation would only prove itself right.

The snapshot's entity half comes from core's own
`config/entity_registry/list_for_display`, so the trimming and the `disabled_by`
filter are core's rather than this file's — which is what lets these tests pin
the claim that a disabled entity can never resolve.
"""

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from cards import INSTANCE, lookups, resolving_cards
from custom_components.nina_astrophotography.const import CONF_HOST, CONF_PORT, DOMAIN
from helpers import needs_node, run_node

DRIVER = Path(__file__).parent / "resolve_entities.mjs"

pytestmark = needs_node


async def _snapshot(hass: HomeAssistant, hass_ws_client) -> dict:
    """The registries as the frontend holds them, in `hass.entities`/`.devices`.

    Only the three entity fields the resolver reads are expanded from core's
    compact keys, with the long names `frontend`'s `connection-mixin.ts` gives
    them: `ei` -> `entity_id`, `di` -> `device_id`, `tk` -> `translation_key`.
    Devices are sent whole and keyed by id, so they need no expansion.
    """
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "config/entity_registry/list_for_display"})
    entities = (await client.receive_json())["result"]["entities"]
    await client.send_json_auto_id({"type": "config/device_registry/list"})
    devices = (await client.receive_json())["result"]

    return {
        "entities": {
            entity["ei"]: {
                "entity_id": entity["ei"],
                "device_id": entity.get("di"),
                "translation_key": entity.get("tk"),
            }
            for entity in entities
        },
        "devices": {device["id"]: device for device in devices},
    }


async def _resolve(
    hass: HomeAssistant, snapshot: dict, device_id: str | None = None
) -> dict[str, str]:
    """`resolveEntities(hass, device_id)`, as the shipped module computes it."""
    return await hass.async_add_executor_job(
        run_node, DRIVER, snapshot, device_id or ""
    )


def _templated(domain: str, suffix: str, instance: str = INSTANCE) -> str:
    """The prefix-templated id, which is the fallback `_eid` computes."""
    return f"{domain}.{instance}_{suffix}"


async def _set_up_guiding(hass: HomeAssistant, entry, rig) -> None:
    """Set the entry up with every piece of equipment this card reads present.

    An entity exists only once its equipment has been observed, and no guider is
    connected in the default state. The state has to be in force before setup,
    not advanced on to — see `_set_up_at` in `test_binary_sensor.py`.
    """
    rig.goto("imaging_guiding")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# Per card, the lookups that cannot resolve and why. Asserted as an exact set so
# that nothing joins one unnoticed; a card whose every lookup resolves has an
# empty entry rather than none, so a newly converted card has to be listed.
CANNOT_RESOLVE: dict[str, dict[tuple[str, str], str]] = {
    "nina-observatory-card.js": {
        # Takes the guider device's own name (`name=None`), so it has no key.
        ("switch", "guider"): "no translation key",
        # No dome on any captured rig, so the device is never observed and its
        # entities never created. A real dome's would ship disabled, and disabled
        # entities are absent from the payload — unresolvable either way (#93).
        ("binary_sensor", "dome_at_park"): "no dome device (#93)",
        ("sensor", "dome_shutter_status"): "no dome device (#93)",
        # Present and disabled, which is the case the test below pins.
        ("sensor", "sequence_progress"): "ships disabled",
    },
    "nina-sky-map-card.js": {},
    "nina-autofocus-card.js": {
        # Diagnostic and disabled by default, and the card only reads it when a
        # report carried no fits to take the worst R² from.
        ("sensor", "autofocus_r_squared"): "ships disabled",
    },
    "nina-weather-card.js": {
        # A channel the station reports as "NaN" gets no entity at all, so
        # neither path names one — the cell reads `—` either way.
        ("sensor", "cloud_cover"): "channel is NaN on this station",
        ("sensor", "sky_quality"): "channel is NaN on this station",
        ("sensor", "star_fwhm"): "channel is NaN on this station",
    },
    "nina-frame-stats-card.js": {},
    "nina-image-panel-card.js": {},
}

RESOLVING = resolving_cards()


def test_every_resolving_card_is_accounted_for() -> None:
    """The two tests below are only as wide as this table. A card converted to
    the registry without an entry here would be covered by neither.
    """
    assert {card.name for card in RESOLVING} == set(CANNOT_RESOLVE)


@pytest.mark.parametrize("card", RESOLVING, ids=lambda p: p.name)
async def test_every_card_lookup_resolves_to_the_id_it_used_to_template(
    hass: HomeAssistant,
    config_entry,
    nina_responses,
    rig,
    hass_ws_client,
    card: Path,
) -> None:
    """On a rig carrying the ids the committed list records, every resolved
    lookup must equal its prefix-templated form. A mismatch means the card reads
    a *different* entity, which no fallback catches.

    This is what pins the lookups whose key is not its suffix: a wrong slug on
    one of those shows up as a mismatch, not as a blank reading.
    """
    await _set_up_guiding(hass, config_entry, rig)

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    wrong = {
        f"{domain}.{key}": (resolved[f"{domain}.{key}"], _templated(domain, suffix))
        for domain, key, suffix in lookups(card)
        if f"{domain}.{key}" in resolved
        and resolved[f"{domain}.{key}"] != _templated(domain, suffix)
    }

    assert not wrong, f"resolved to a different entity than it templated: {wrong}"


@pytest.mark.parametrize("card", RESOLVING, ids=lambda p: p.name)
async def test_only_the_entities_that_cannot_resolve_fall_back(
    hass: HomeAssistant,
    config_entry,
    nina_responses,
    rig,
    hass_ws_client,
    card: Path,
) -> None:
    """The companion to the test above, which would pass just as well if
    nothing resolved at all.

    Catches a new silent fallback: one more entity shipped disabled, or a
    dropped `translation_key`, costs rename-survival and reports nothing.
    """
    await _set_up_guiding(hass, config_entry, rig)

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    fell_back = {
        (domain, key)
        for domain, key, _ in lookups(card)
        if f"{domain}.{key}" not in resolved
    }

    assert fell_back == set(CANNOT_RESOLVE[card.name])


async def test_a_disabled_entity_is_absent_from_what_the_frontend_sees(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """A disabled entity has a registry row and is still left out of the payload
    a dashboard receives, so no card can resolve one — which is why the dome
    section needs a device probe (#93).

    `sequence_progress` is the only read this card makes that is both disabled
    and present; no captured rig creates the dome entities at all.
    """
    progress = f"sensor.{INSTANCE}_sequence_progress"
    assert er.async_get(hass).async_get(progress) is not None, "row should exist"

    snapshot = await _snapshot(hass, hass_ws_client)

    assert progress not in snapshot["entities"]


async def test_two_rigs_resolve_nothing_until_one_is_named(
    hass: HomeAssistant, config_entry, nina_responses, hass_ws_client
) -> None:
    """Discovery is only unambiguous for one rig. Guessing between two would
    give a dashboard the wrong rig's readings, so the map is empty instead and
    every lookup falls back to the configured prefix.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second Rig",
        data={CONF_HOST: "other.local", CONF_PORT: 1888},
        unique_id="other.local:1888",
        entry_id="01JTESTENTRY0000000000001",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    assert resolved == {}


async def test_naming_a_child_device_resolves_its_whole_rig(
    hass: HomeAssistant, config_entry, nina_responses, hass_ws_client
) -> None:
    """`device_id` may name any one of a rig's devices, not just its hub — a
    device selector makes a child the likelier pick. Resolution has to cover the
    whole rig from there, including entities hanging off the hub itself.
    """
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Second Rig",
        data={CONF_HOST: "other.local", CONF_PORT: 1888},
        unique_id="other.local:1888",
        entry_id="01JTESTENTRY0000000000001",
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    camera = registry.async_get_device_by_identifier(
        (DOMAIN, f"{config_entry.entry_id}_camera"), config_entry.entry_id
    )
    assert camera is not None
    snapshot = await _snapshot(hass, hass_ws_client)

    resolved = await _resolve(hass, snapshot, device_id=camera.id)

    rig = {config_entry.entry_id} | {
        device.id
        for device in dr.async_entries_for_config_entry(registry, config_entry.entry_id)
    }
    assert resolved, "naming one of its devices should identify the rig"
    assert {
        snapshot["entities"][entity_id]["device_id"] for entity_id in resolved.values()
    } <= rig
    # A hub-level entity: it hangs off the hub, not off any equipment.
    assert "sensor.sequence_target" in resolved


async def test_renaming_a_device_does_not_break_resolution(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """A renamed entity id is what a prefix-built lookup cannot survive. The
    `translation_key` the resolver keys on is untouched by the rename.
    """
    renamed = er.async_get(hass).async_update_entity(
        f"sensor.{INSTANCE}_mount_right_ascension",
        new_entity_id="sensor.pier_two_mount_right_ascension",
    )
    await hass.async_block_till_done()

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    assert resolved["sensor.mount_right_ascension"] == renamed.entity_id

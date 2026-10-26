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
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from cards import INSTANCE, lookups, resolving_cards
from custom_components.nina_astrophotography.const import CONF_HOST, CONF_PORT, DOMAIN
from helpers import needs_node, run_node

DRIVER = Path(__file__).parent / "resolve_entities.mjs"


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


async def _link(
    hass: HomeAssistant, hass_ws_client, *, identified: bool = True
) -> dict:
    """`linkState` as a card computes it: `since` in epoch ms, and `lost`.

    Unless `identified`, the registries are withheld, as from a card that cannot
    tell which rig it shows, so it reads the ids its prefix templates.
    """
    snapshot = await _snapshot(hass, hass_ws_client)
    snapshot["states"] = {
        state.entity_id: {
            "state": state.state,
            "attributes": {"restored": bool(state.attributes.get("restored"))},
            "last_changed": state.last_changed.isoformat(),
        }
        for state in hass.states.async_all()
        if state.entity_id in snapshot["entities"]
    }
    snapshot["prefix"] = INSTANCE
    if not identified:
        del snapshot["entities"], snapshot["devices"]
    return await hass.async_add_executor_job(
        run_node, DRIVER, snapshot, "", "linkState"
    )


def _ms() -> int:
    return int(dt_util.utcnow().timestamp() * 1000)


async def _miss_a_poll(advance) -> int:
    """N.I.N.A. stops answering; returns that moment, in ms."""
    await advance("nina_unreachable")
    return _ms()


def _templated(domain: str, suffix: str, instance: str = INSTANCE) -> str:
    """The prefix-templated id, which is the fallback `_eid` computes."""
    return f"{domain}.{instance}_{suffix}"


# Per card, the lookups that cannot resolve and why. Asserted as an exact set so
# that nothing joins one unnoticed; a card whose every lookup resolves has an
# empty entry rather than none, so a newly converted card has to be listed.
CANNOT_RESOLVE: dict[str, dict[tuple[str, str], str]] = {
    "nina-observatory-card.js": {
        # Takes the guider device's own name (`name=None`), so it has no key.
        ("switch", "guider"): "no translation key",
        # No dome on the reference rig, so the device is never observed and its
        # entities never created; they resolve on the simulator's (below).
        ("sensor", "dome_shutter_status"): "no dome on this rig",
        ("button", "dome_open"): "no dome on this rig",
        ("button", "dome_close"): "no dome on this rig",
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


@needs_node
@pytest.mark.parametrize("card", RESOLVING, ids=lambda p: p.name)
async def test_every_card_lookup_resolves_to_the_id_it_used_to_template(
    hass: HomeAssistant,
    config_entry,
    rig,
    hass_ws_client,
    card: Path,
    set_up_at,
) -> None:
    """On a rig carrying the ids the committed list records, every resolved
    lookup must equal its prefix-templated form. A mismatch means the card reads
    a *different* entity, which no fallback catches.

    This is what pins the lookups whose key is not its suffix: a wrong slug on
    one of those shows up as a mismatch, not as a blank reading.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    wrong = {
        f"{domain}.{key}": (resolved[f"{domain}.{key}"], _templated(domain, suffix))
        for domain, key, suffix in lookups(card)
        if f"{domain}.{key}" in resolved
        and resolved[f"{domain}.{key}"] != _templated(domain, suffix)
    }

    assert not wrong, f"resolved to a different entity than it templated: {wrong}"


@needs_node
@pytest.mark.parametrize("card", RESOLVING, ids=lambda p: p.name)
async def test_only_the_entities_that_cannot_resolve_fall_back(
    hass: HomeAssistant,
    config_entry,
    rig,
    hass_ws_client,
    card: Path,
    set_up_at,
) -> None:
    """The companion to the test above, which would pass just as well if
    nothing resolved at all.

    Catches a new silent fallback: one more entity shipped disabled, or a
    dropped `translation_key`, costs rename-survival and reports nothing.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    fell_back = {
        (domain, key)
        for domain, key, _ in lookups(card)
        if f"{domain}.{key}" not in resolved
    }

    assert fell_back == set(CANNOT_RESOLVE[card.name])


@needs_node
async def test_every_dome_read_resolves_on_a_rig_with_a_dome(
    hass: HomeAssistant, config_entry, rig, hass_ws_client, set_up_at
) -> None:
    """Each dome entity the observatory card reads ships enabled, so none is
    left out of what a dashboard receives.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client))

    card = next(card for card in RESOLVING if card.name == "nina-observatory-card.js")
    dome = {f"{domain}.{key}" for domain, key, _ in lookups(card) if "dome" in key}
    assert dome
    assert dome <= resolved.keys()


async def test_a_disabled_entity_is_absent_from_what_the_frontend_sees(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """A disabled entity has a registry row and is still left out of the payload
    a dashboard receives, so no card can resolve one.

    `sequence_progress` is the only read this card makes that is both disabled
    and present on the reference rig.
    """
    progress = f"sensor.{INSTANCE}_sequence_progress"
    assert er.async_get(hass).async_get(progress) is not None, "row should exist"

    snapshot = await _snapshot(hass, hass_ws_client)

    assert progress not in snapshot["entities"]


@needs_node
async def test_two_rigs_resolve_nothing_until_one_is_named(
    hass: HomeAssistant, config_entry, rig, hass_ws_client
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


@needs_node
async def test_naming_a_child_device_resolves_its_whole_rig(
    hass: HomeAssistant, config_entry, rig, hass_ws_client
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


@needs_node
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


@needs_node
async def test_drivers_dropping_after_they_were_seen_is_not_a_lost_link(
    hass: HomeAssistant, advance, hass_ws_client
) -> None:
    """Their rows go `unavailable`; the hub's do not."""
    await advance("equipment_disconnected")

    assert await _link(hass, hass_ws_client) == {"since": None, "lost": False}


@needs_node
@pytest.mark.usefixtures("freezer")
async def test_a_missed_poll_is_quiet_but_not_lost(
    hass: HomeAssistant, advance, hass_ws_client
) -> None:
    """Inside the grace the readings are held: not answering, not yet lost."""
    quiet_at = await _miss_a_poll(advance)

    assert await _link(hass, hass_ws_client) == {"since": quiet_at, "lost": False}


@needs_node
@pytest.mark.parametrize("rig_state", ["imaging", "equipment_disconnected"])
async def test_past_the_grace_the_link_is_lost_since_the_first_missed_poll(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    outage,
    hass_ws_client,
    rig_state: str,
) -> None:
    """With no equipment ever seen too: the rows that tell it are the hub's."""
    await set_up_at(hass, config_entry, rig, rig_state)
    quiet_at = _ms()

    await outage()

    assert await _link(hass, hass_ws_client) == {"since": quiet_at, "lost": True}


@needs_node
@pytest.mark.usefixtures("freezer")
async def test_an_entry_that_is_not_loaded_has_lost_its_link(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """Its rows restored, `reachable` among them, since the unload."""
    unloaded_at = _ms()
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert await _link(hass, hass_ws_client) == {"since": unloaded_at, "lost": True}


@needs_node
@pytest.mark.parametrize("lost", [False, True], ids=["answering", "lost"])
async def test_an_unidentified_rig_is_read_through_the_card_s_own_ids(
    hass: HomeAssistant, loaded_entry, outage, hass_ws_client, lost: bool
) -> None:
    """Two rigs and no `device_id:` leave nothing to resolve."""
    if lost:
        await outage()

    assert (await _link(hass, hass_ws_client, identified=False))["lost"] is lost

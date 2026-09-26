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

from freezegun.api import FrozenDateTimeFactory
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

    Only the four entity fields the resolver reads are expanded from core's
    compact keys, with the long names `frontend`'s `connection-mixin.ts` gives
    them: `ei` -> `entity_id`, `di` -> `device_id`, `pl` -> `platform`,
    `tk` -> `translation_key`.
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
                "platform": entity.get("pl"),
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


async def _link_lost_since(
    hass: HomeAssistant, hass_ws_client, fallback: list[str] | None = None
) -> int | None:
    """`linkLostSince` as a card computes it, in epoch ms.

    With `fallback`, the registries are withheld and those ids read instead, as
    by a card that cannot identify its rig.
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
    if fallback is not None:
        snapshot = {"states": snapshot["states"], "fallback": fallback}
    return await hass.async_add_executor_job(
        run_node, DRIVER, snapshot, "", "linkLostSince"
    )


async def _lose_the_link(advance, freezer: FrozenDateTimeFactory) -> int:
    """N.I.N.A. stops answering a minute on; returns that moment in ms."""
    freezer.tick(60)
    await advance("nina_unreachable")
    return int(dt_util.utcnow().timestamp() * 1000)


def _hub_row(hass: HomeAssistant, entry, platform: str) -> er.RegistryEntry:
    """A registry row on the hub device, with no entity behind it."""
    hub = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    )
    assert hub is not None
    return er.async_get(hass).async_get_or_create(
        "sensor", platform, f"{entry.entry_id}_retired", device_id=hub.id
    )


def _orphan_a_hub_row(hass: HomeAssistant, entry) -> None:
    """A hub registry row no entity claims, under core's placeholder."""
    _hub_row(hass, entry, DOMAIN).write_unavailable_state(hass)


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


@needs_node
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


@needs_node
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


@needs_node
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


@needs_node
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
@pytest.mark.parametrize("rig_state", ["site_configured", "equipment_disconnected"])
async def test_a_rig_that_answers_has_not_lost_its_link(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    hass_ws_client,
    rig_state: str,
) -> None:
    """Every driver down is not a lost link: the hub's rows stay available."""
    await set_up_at(hass, config_entry, rig, rig_state)

    assert await _link_lost_since(hass, hass_ws_client) is None


@needs_node
async def test_a_failed_poll_loses_the_link_from_that_moment(
    hass: HomeAssistant, advance, hass_ws_client, freezer: FrozenDateTimeFactory
) -> None:
    """The cards' grace period runs from this, so it must be the failed poll."""
    failed_at = await _lose_the_link(advance, freezer)

    assert await _link_lost_since(hass, hass_ws_client) == failed_at


@needs_node
async def test_an_entry_that_is_not_loaded_has_lost_its_link(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """Every hub row restored, as an entry that failed to load leaves them."""
    assert await hass.config_entries.async_unload(loaded_entry.entry_id)
    await hass.async_block_till_done()

    assert await _link_lost_since(hass, hass_ws_client) is not None


@needs_node
async def test_an_orphaned_hub_row_does_not_lose_the_link(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """It reads `unavailable` for ever beside rows that answer."""
    _orphan_a_hub_row(hass, loaded_entry)

    assert await _link_lost_since(hass, hass_ws_client) is None


@needs_node
async def test_an_orphaned_hub_row_does_not_date_a_lost_link(
    hass: HomeAssistant,
    loaded_entry,
    advance,
    hass_ws_client,
    freezer: FrozenDateTimeFactory,
) -> None:
    """It changed when core restored it: dating the loss from that would skip
    the cards' grace period.
    """
    _orphan_a_hub_row(hass, loaded_entry)

    failed_at = await _lose_the_link(advance, freezer)

    assert await _link_lost_since(hass, hass_ws_client) == failed_at


@needs_node
async def test_another_integration_s_row_on_the_hub_does_not_lose_the_link(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """A helper linked to the hub, such as a template sensor, can be
    `unavailable` on its own.
    """
    helper = _hub_row(hass, loaded_entry, "template")
    hass.states.async_set(helper.entity_id, "unavailable")

    assert await _link_lost_since(hass, hass_ws_client) is None


@needs_node
@pytest.mark.parametrize("lost", [False, True], ids=["answering", "lost"])
async def test_an_unidentified_rig_is_read_through_the_card_s_own_ids(
    hass: HomeAssistant,
    advance,
    hass_ws_client,
    freezer: FrozenDateTimeFactory,
    lost: bool,
) -> None:
    """Two rigs and no `device_id:` leave no hub to walk."""
    failed_at = await _lose_the_link(advance, freezer) if lost else None

    assert (
        await _link_lost_since(
            hass,
            hass_ws_client,
            fallback=[
                _templated("binary_sensor", "sequencer_running"),
                _templated("sensor", "session_image_count"),
            ],
        )
        == failed_at
    )

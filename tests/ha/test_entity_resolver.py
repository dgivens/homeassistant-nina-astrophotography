"""`www/nina-entity-resolver.js` against real registries from the fake rig.

The module is JavaScript and runs in a browser, so this drives the shipped file
with node (`resolve_entities.mjs`) over a snapshot of what Home Assistant would
send that browser. Reimplementing the resolver in Python would prove nothing
about the file users load.

What makes the snapshot worth taking from here rather than hand-writing: the
entity half comes from core's own `config/entity_registry/list_for_display`, so
the trimming and the `disabled_by` filter are core's, not ours — which is what
lets these tests pin the claim that a disabled entity can never resolve.
"""

import json
from pathlib import Path
import shutil
import subprocess

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from cards import INSTANCE, WWW_DIR, lookups
from custom_components.nina_astrophotography.const import CONF_HOST, CONF_PORT, DOMAIN

CARD = WWW_DIR / "nina-observatory-card.js"
DRIVER = Path(__file__).parent / "resolve_entities.mjs"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="needs node to run the shipped card module"
)


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
    hass: HomeAssistant, snapshot: dict, tmp_path: Path, device_id: str | None = None
) -> dict[str, str]:
    """`resolveEntities(hass, device_id)`, as the shipped module computes it."""

    def _run() -> str:
        payload = tmp_path / "registries.json"
        payload.write_text(json.dumps(snapshot), encoding="utf-8")
        return subprocess.run(
            ["node", str(DRIVER), str(payload), device_id or ""],
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    return json.loads(await hass.async_add_executor_job(_run))


def _templated(domain: str, suffix: str, instance: str = INSTANCE) -> str:
    """The id the card built by hand before it resolved anything."""
    return f"{domain}.{instance}_{suffix}"


async def _set_up_guiding(hass: HomeAssistant, entry, rig) -> None:
    """Set the entry up with every piece of equipment this card reads present.

    An entity exists only once its equipment has been observed, and the default
    state connects no guider — so on it the guiding lookups would be absent for
    a reason that has nothing to do with resolution. `imaging_guiding` has to be
    in force before setup, not advanced on to (`_set_up_at`, test_binary_sensor).
    """
    rig.goto("imaging_guiding")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


# The card's lookups that cannot resolve, with the reason each one cannot.
# Nothing here is a defect in the resolver; the point of asserting the exact set
# is that nothing else joins it unnoticed.
CANNOT_RESOLVE = {
    # Takes the guider device's own name (`name=None`), so it has no key at all.
    ("switch", "guider"): "no translation key",
    # No dome on any captured rig, so the device is never observed and its
    # entities are never created. Were there one they would ship disabled, and
    # core omits a disabled entity from the payload — so either way, #93.
    ("binary_sensor", "dome_at_park"): "no dome device (#93)",
    ("sensor", "dome_shutter_status"): "no dome device (#93)",
    # Exists here, and disabled: the case that proves resolution cannot reach a
    # disabled entity. See the test below.
    ("sensor", "sequence_progress"): "ships disabled",
}


async def test_every_card_lookup_resolves_to_the_id_it_used_to_template(
    hass: HomeAssistant,
    config_entry,
    nina_responses,
    rig,
    hass_ws_client,
    tmp_path: Path,
) -> None:
    """The single-rig default case, which is now the resolved path: on a rig
    whose ids are the ones the snapshot records, resolution has to agree with
    the prefix it replaced, lookup for lookup — otherwise the card silently
    reads a *different* entity than it did before, which no fallback catches.

    This is also what pins the two lookups whose key is not its suffix: a wrong
    slug on `select.filter` or `sensor.guider_rms_dec` shows up here as a
    mismatch rather than as a blank reading nobody notices.
    """
    await _set_up_guiding(hass, config_entry, rig)

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client), tmp_path)

    wrong = {
        f"{domain}.{key}": (resolved[f"{domain}.{key}"], _templated(domain, suffix))
        for domain, key, suffix in lookups(CARD)
        if f"{domain}.{key}" in resolved
        and resolved[f"{domain}.{key}"] != _templated(domain, suffix)
    }

    assert not wrong, f"resolved to a different entity than it templated: {wrong}"


async def test_only_the_entities_that_cannot_resolve_fall_back(
    hass: HomeAssistant,
    config_entry,
    nina_responses,
    rig,
    hass_ws_client,
    tmp_path: Path,
) -> None:
    """The companion to the test above, which would pass just as well if
    nothing resolved at all. Every lookup but the four that provably cannot
    resolve must be in the map.

    New silent fallbacks are the thing to catch: one more entity shipped
    disabled, or a `translation_key` dropped, costs the rename-survival this
    plan bought and reports nothing at runtime.
    """
    await _set_up_guiding(hass, config_entry, rig)

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client), tmp_path)

    fell_back = {
        (domain, key)
        for domain, key, _ in lookups(CARD)
        if f"{domain}.{key}" not in resolved
    }

    assert fell_back == set(CANNOT_RESOLVE)


async def test_a_disabled_entity_is_absent_from_what_the_frontend_sees(
    hass: HomeAssistant, loaded_entry, hass_ws_client
) -> None:
    """Why a disabled entity can never be resolved, and so why the dome section
    needs #93's device probe rather than this plan — asserted against core
    rather than taken on trust. The registry row exists; core still leaves it
    out of the payload a dashboard receives.

    `sequence_progress` stands in for the dome reads, which no captured rig can
    create at all: it is the one read this card makes that ships disabled *and*
    exists here.
    """
    progress = f"sensor.{INSTANCE}_sequence_progress"
    assert er.async_get(hass).async_get(progress) is not None, "row should exist"

    snapshot = await _snapshot(hass, hass_ws_client)

    assert progress not in snapshot["entities"]


async def test_two_rigs_resolve_nothing_until_one_is_named(
    hass: HomeAssistant, config_entry, nina_responses, hass_ws_client, tmp_path: Path
) -> None:
    """Discovery is only unambiguous for one rig. With two, guessing would give
    half a dashboard the wrong rig's readings, so the map is empty and every
    lookup falls back to the configured prefix — which is what 1.4.5-era
    two-rig configs already rely on.
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

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client), tmp_path)

    assert resolved == {}


async def test_naming_a_child_device_resolves_its_whole_rig(
    hass: HomeAssistant, config_entry, nina_responses, hass_ws_client, tmp_path: Path
) -> None:
    """`device_id` may name any one of a rig's devices, not just its hub — the
    camera is what a user picking from a device selector is most likely to
    choose. Resolution still has to cover the whole rig from there, including
    the hub-level entities that hang off no equipment at all.
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

    resolved = await _resolve(hass, snapshot, tmp_path, device_id=camera.id)

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
    hass: HomeAssistant, loaded_entry, hass_ws_client, tmp_path: Path
) -> None:
    """The failure this plan exists to remove. Renaming a device is what Home
    Assistant offers to rewrite entity ids for, and a prefix-built id cannot
    survive it — the `translation_key` the resolver keys on is untouched.
    """
    renamed = er.async_get(hass).async_update_entity(
        f"sensor.{INSTANCE}_mount_right_ascension",
        new_entity_id="sensor.pier_two_mount_right_ascension",
    )
    await hass.async_block_till_done()

    resolved = await _resolve(hass, await _snapshot(hass, hass_ws_client), tmp_path)

    assert resolved["sensor.mount_right_ascension"] == renamed.entity_id

"""The `hass` a dashboard holds, dumped for `tools/card-harness/`.

The cards run in a browser, so nothing in either suite renders one. The harness
does, and it needs the object Home Assistant hands a card: the states, and the
two registries a card resolves entity ids from.

Derived rather than written by hand, for the reason `test_entity_resolver.py`
drives node over a real registry instead of a mock — values invented to suit a
card only prove the card right about itself. Everything here comes out of the
fake rig, so it is the captured corpus one mapper and one platform table later.

Regenerating is part of the snapshot commit, the same as `entity_ids.txt`.
"""

import json
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util.unit_system import (
    METRIC_SYSTEM,
    US_CUSTOMARY_SYSTEM,
    UnitSystem,
)
import pytest

from custom_components.nina_astrophotography.const import DOMAIN
from helpers import needs_node, run_node

SNAPSHOTS = Path(__file__).parent / "snapshots"
DUMP = SNAPSHOTS / "card_states.json"
DRIVER = Path(__file__).parent / "resolve_entities.mjs"

# Each dump: the rig state it is set up at, the conftest fixture that sets its
# clock — `None` to leave the real one running — and Home Assistant's unit
# system.
#
# `site_configured` rather than the `imaging_guiding` it derives from: it is the
# same rig with every endpoint captured and the guider up, plus the observing
# site, so it is a superset and a card that wants no site drops one entity.
# `equipment_disconnected` is the degraded half — what a card shows with the
# drivers down.
#
# Neither holds a session: the fold measures the noon rollover against the
# clock, and their frames are from a night long past. `dawn_flats` is dumped from
# inside its own night, so it carries the whole session — 55 lights over four
# targets and five filters, with the dawn flats after them.
#
# `site_configured_us_customary` is `site_configured` on a US customary
# instance: Home Assistant's own conversion of the same readings, which is what
# a card that assumed the integration's units would mislabel.
DUMPS: dict[str, tuple[str, str | None, UnitSystem]] = {
    "site_configured": ("site_configured", None, METRIC_SYSTEM),
    "equipment_disconnected": ("equipment_disconnected", None, METRIC_SYSTEM),
    "dawn_flats": ("dawn_flats", "inside_the_dawn_session", METRIC_SYSTEM),
    "site_configured_us_customary": ("site_configured", None, US_CUSTOMARY_SYSTEM),
}

# Home Assistant mints these per run, so they are the one thing here that is not
# reproducible — and a token is not something to commit either way.
VOLATILE = ("access_token", "entity_picture")


def _attributes(attributes: Any) -> dict:
    return {
        key: "<per run>" if key in VOLATILE else value
        for key, value in sorted(attributes.items())
    }


def _pseudonyms(devices, entry) -> dict[str, str]:
    """Each device's registry id mapped to a stable name.

    Home Assistant mints a fresh `device_id` per run, and entities point at it,
    so the raw ids make the dump differ from itself. The integration's own
    identifier says which device it is — `<entry_id>` for the hub and
    `<entry_id>_<kind>` for its equipment — and that is reproducible.
    """
    names = {}
    for device in devices:
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier.startswith(entry.entry_id):
                names[device.id] = (
                    identifier[len(entry.entry_id) :].lstrip("_") or "hub"
                )
    return names


def _link(named: dict[str, str], device_id: str | None) -> str | None:
    """A device's pseudonym. A hub has no parent, and an entity need not have a
    device, so either side of a link can be absent.
    """
    return named.get(device_id) if device_id else None


def _entity(named: dict[str, str], row: er.RegistryEntry) -> dict:
    """A registry row as the frontend holds it. `display_precision` is present
    only when core sends one, and is core's own figure for the unit the state
    is shown in, read from the payload it sends.
    """
    entity = {
        "entity_id": row.entity_id,
        "device_id": _link(named, row.device_id),
        "translation_key": row.translation_key,
    }
    if (precision := json.loads(row.display_json_repr or b"{}").get("dp")) is not None:
        entity["display_precision"] = precision
    return entity


def _hass_for_a_card(hass: HomeAssistant, entry) -> dict:
    """The states and registries, under the names the frontend gives them.

    The compact keys core sends and the long names the frontend expands them to
    are pinned in `test_entity_resolver.py`; this writes the long ones, which is
    what a card reads.
    """
    entities = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    # This entry's entities only. Home Assistant's own — `sun.sun` above all —
    # move with the clock, and a card never reads them.
    ours = {row.entity_id for row in entities}
    named = _pseudonyms(devices, entry)
    return {
        "states": {
            state.entity_id: {
                "state": state.state,
                "attributes": _attributes(state.attributes),
            }
            for state in sorted(hass.states.async_all(), key=lambda s: s.entity_id)
            if state.entity_id in ours
        },
        # A disabled entity is absent from what a dashboard receives, which is
        # what makes one unresolvable — so it is absent here too.
        "entities": {
            row.entity_id: _entity(named, row)
            for row in sorted(entities, key=lambda r: r.entity_id)
            if row.disabled_by is None
        },
        "devices": {
            named[device.id]: {
                "id": named[device.id],
                "name": device.name,
                # `[domain, id]`, as the frontend holds it: the resolver reads
                # the domain first, so sorting inside a pair — an entry id sorts
                # before `nina_astrophotography` — would hide every hub.
                "identifiers": sorted(list(pair) for pair in device.identifiers),
                "via_device_id": _link(named, device.via_device_id),
            }
            for device in sorted(devices, key=lambda d: named[d.id])
        },
    }


@pytest.mark.parametrize(
    ("dump", "rig_state", "clock", "units"),
    [(name, *setup) for name, setup in DUMPS.items()],
    ids=DUMPS,
)
async def test_the_card_harness_dump_is_current(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    request: pytest.FixtureRequest,
    dump: str,
    rig_state: str,
    clock: str | None,
    units: UnitSystem,
) -> None:
    """One dump per run, merged into the committed file.

    Parametrized rather than looped because each state needs its own `hass`:
    a tier-polled endpoint latches at setup and will not be advanced on to.
    """
    if clock:
        request.getfixturevalue(clock)
    hass.config.units = units
    await set_up_at(hass, config_entry, rig, rig_state)

    current = json.loads(DUMP.read_text(encoding="utf-8")) if DUMP.exists() else {}
    # Round-tripped before comparing: an attribute Home Assistant holds as a
    # tuple comes back from the committed file as a list and is otherwise
    # unequal to itself for ever.
    fresh = json.loads(json.dumps(_hass_for_a_card(hass, config_entry)))
    if current.get(dump) == fresh:
        return

    DUMP.write_text(
        json.dumps({**current, dump: fresh}, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pytest.fail(f"card_states.json regenerated for {dump} — review and commit it")


@needs_node
@pytest.mark.parametrize("dump", DUMPS)
def test_every_keyed_entity_in_the_dump_resolves(dump: str) -> None:
    """The harness checks a conversion by rendering a card off resolved ids and
    again off templated ones. A dump whose registry resolved nothing would make
    both the fallback, and that comparison would pass while proving nothing.
    """
    state = json.loads(DUMP.read_text(encoding="utf-8"))[dump]
    resolved = run_node(DRIVER, state)
    assert sorted(resolved.values()) == sorted(
        entity_id
        for entity_id, row in state["entities"].items()
        if row["translation_key"]
    )

"""The Lovelace cards name entities the integration creates, and build their
own image URLs.

They read `hass.states` and call the Advanced API directly from the browser
rather than going through the integration, so a renamed entity or a corrected
path leaves them behind — which is how the image-history endpoint stayed broken
in `nina-image-panel-card.js` for a release after it was fixed everywhere else.

Source checks only: these read the card files as text. A card names an entity
either by templating its configured prefix onto a suffix, or by asking the
registry for a `translation_key` (`_eid`); both are checked here against the
committed entity list. `tests/ha/test_entity_resolver.py` covers the resolver
itself, against a live registry.
"""

from functools import cache
import json
from pathlib import Path

import pytest
import yaml

from cards import (
    COMPONENT,
    INSTANCE,
    INVOCATION,
    LITERAL,
    RESOLVED,
    ROOT,
    TEMPLATED,
    WWW_DIR,
    lookups,
)

CARDS = sorted(WWW_DIR.glob("*.js"))
assert CARDS, "no cards found"

# Lookups that name an entity with no `translation_key` and so can only ever
# take the prefix fallback. The guider switch is the guider device's one
# function, so it takes that device's name (`name=None`) and has no key of its
# own; the entity id is still what the suffix says.
UNRESOLVABLE = {("switch", "guider")}

# Entities the reference rig cannot produce, so the snapshot cannot carry them
# (docs/2.0-renames.md): every dome entity, since nobody involved has the
# hardware, and the three weather channels this source reports as "NaN".
ABSENT_FROM_THE_SNAPSHOT = {
    "weather_cloud_cover",
    "weather_sky_quality",
    "weather_star_fwhm",
}


def _known(suffix: str) -> bool:
    return suffix.startswith("dome_") or suffix in _entity_suffixes()


@cache
def _entity_suffixes() -> frozenset[str]:
    """Every entity the integration creates, less its instance prefix.

    Read from the plain committed list rather than scraped out of syrupy's
    `.ambr`, which is a snapshot serialization and not a stable interface.
    """
    listed = ROOT / "tests" / "ha" / "snapshots" / "entity_ids.txt"
    return (
        frozenset(
            entity.split(".", 1)[1].removeprefix(f"{INSTANCE}_")
            for entity in listed.read_text(encoding="utf-8").split()
        )
        | ABSENT_FROM_THE_SNAPSHOT
    )


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_reads_an_entity_that_2_0_does_not_create(card: Path) -> None:
    """Every 1.4.5 card named entities phases B and C renamed or deleted.

    Existence only: the snapshot lists registry rows whether or not they are
    enabled, so this cannot catch a card probing an entity that ships disabled
    and therefore has no state.
    """
    named = set(TEMPLATED.findall(card.read_text(encoding="utf-8")))
    unknown = {suffix for suffix in named if not _known(suffix)}

    assert not unknown, f"{card.name} reads removed entities: {sorted(unknown)}"


@cache
def _translation_keys(domain: str) -> frozenset[str]:
    """Every `translation_key` this domain has a name for.

    `en.json` rather than the descriptor tables: the weather channels come from
    a factory that passes `translation_key=key`, so the tables hold no literal
    for any of them. A key missing here has no name and no entity; a name no
    descriptor uses is caught by the suffix half of the assertion instead.

    Switch-device channels are absent either way — they take driver-supplied
    names at runtime, so a card cannot resolve one.
    """
    names = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    return frozenset(names["entity"].get(domain, {}))


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_every_registry_lookup_is_one_this_suite_can_read(card: Path) -> None:
    """A lookup built from anything but literals is checked by nothing: the
    test below can only read the calls this regex matches.
    """
    source = card.read_text(encoding="utf-8")

    assert len(RESOLVED.findall(source)) == len(INVOCATION.findall(source))


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_every_registry_lookup_names_a_real_key_and_a_real_entity(card: Path) -> None:
    """Both halves of a lookup have to hold, and neither reports itself.

    A wrong key resolves nothing and falls back to the prefix; a wrong suffix
    makes that fallback name an entity which does not exist. Either way the card
    reads blank with no error. They are easy to get out of step: the suffix is
    the device name plus the entity name, and the key is neither.
    """
    wrong = []
    for domain, key, suffix in lookups(card):
        if key not in _translation_keys(domain) and (domain, key) not in UNRESOLVABLE:
            wrong.append(f"{domain}.{key} is not a translation key")
        if not _known(suffix):
            wrong.append(f"{domain}.{INSTANCE}_{suffix} is not an entity")

    assert not wrong, f"{card.name}: {wrong}"


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_hardcodes_an_entity_id(card: Path) -> None:
    """2.0 ids carry the instance name, so an id without one is wrong on every
    install — and silently, since a missing entity just reads as no data.
    """
    hardcoded = set(LITERAL.findall(card.read_text(encoding="utf-8")))

    assert not hardcoded, f"{card.name} hardcodes: {sorted(hardcoded)}"


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_asks_for_the_stretch_by_the_wrong_name(card: Path) -> None:
    """`useAutoStretch` is not a parameter on /image/{index}; `autoPrepare` is."""
    assert "useAutoStretch" not in card.read_text(encoding="utf-8")


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_puts_the_image_index_in_the_query_string(card: Path) -> None:
    """/image is not a route — the index is a path segment, /image/{index}."""
    assert "/image?" not in card.read_text(encoding="utf-8")


def test_the_documented_action_fields_are_the_translated_ones() -> None:
    """`services.yaml` is what the UI reads, `strings.json` is what it labels
    them with, and a field in one and not the other is invisible or unlabelled.
    Phase D renamed three user-facing fields across both.
    """
    component = ROOT / "custom_components" / "nina_astrophotography"
    services = yaml.safe_load((component / "services.yaml").read_text(encoding="utf-8"))
    strings = json.loads((component / "strings.json").read_text(encoding="utf-8"))

    documented = {
        name: set(spec.get("fields") or {}) for name, spec in services.items()
    }
    translated = {
        name: set(spec.get("fields") or {})
        for name, spec in strings["services"].items()
    }

    assert documented == translated

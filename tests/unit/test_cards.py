"""The Lovelace cards name entities the integration creates, and build their
own image URLs.

They read `hass.states` and call the Advanced API directly from the browser
rather than going through the integration, so a renamed entity or a corrected
path leaves them behind — which is how the image-history endpoint stayed broken
in `nina-image-panel-card.js` for a release after it was fixed everywhere else.

Source checks: there is no JavaScript test harness here, and adding one to pin
a handful of string literals would cost more than it returns. A card names an
entity in one of two ways and both are checked against the same snapshot — by
templating the configured prefix onto a suffix, or by asking the registry for a
`translation_key` (`_eid`, `www/nina-entity-resolver.js`).
"""

import ast
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
    """Every `translation_key` a platform's descriptor table sets literally.

    Parsed rather than imported, to keep this suite free of Home Assistant. The
    switch-device channels are absent by construction — they take their names
    from the driver at runtime — so a card cannot resolve one of those.
    """
    module = ast.parse((COMPONENT / f"{domain}.py").read_text(encoding="utf-8"))
    return frozenset(
        keyword.value.value
        for node in ast.walk(module)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "translation_key"
        and isinstance(keyword.value, ast.Constant)
        and isinstance(keyword.value.value, str)
    )


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_every_registry_lookup_is_one_this_suite_can_read(card: Path) -> None:
    """`_eid` moved the entity ids out of reach of `TEMPLATED`, so a lookup
    built from anything but literals would be checked by nothing at all —
    passing tests on the strings most likely to hold a typo.
    """
    source = card.read_text(encoding="utf-8")

    assert len(RESOLVED.findall(source)) == len(INVOCATION.findall(source))


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_every_registry_lookup_names_a_real_key_and_a_real_entity(card: Path) -> None:
    """Both halves of a lookup have to hold, and neither reports itself.

    A wrong `translation_key` resolves nothing and silently falls back to the
    prefix; a wrong suffix makes that fallback name an entity which does not
    exist. Either way the card reads blank with no error, which is the whole
    failure this indirection exists to remove — and the two halves are easy to
    get out of step, since the suffix is the device name plus the entity name
    and the key is neither.
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

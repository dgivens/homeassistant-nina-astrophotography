"""The Lovelace cards name entities the integration creates, and build their
own image URLs.

They read `hass.states` and call the Advanced API directly from the browser
rather than going through the integration, so a renamed entity or a corrected
path leaves them behind — which is how the image-history endpoint stayed broken
in `nina-image-panel-card.js` for a release after it was fixed everywhere else.

Source checks: there is no JavaScript test harness here, and adding one to pin
a handful of string literals would cost more than it returns.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CARDS = sorted((ROOT / "www").glob("*.js"))
assert CARDS, "no cards found"

DOMAINS = ("sensor", "binary_sensor", "switch", "light", "number", "select",
           "button", "image", "event")
# A card builds its ids from the instance prefix it is configured with:
# `sensor.${prefix}_mount_altitude`.
TEMPLATED = re.compile(
    rf"(?:{'|'.join(DOMAINS)})\.\$\{{[\w.]+\}}_([a-z0-9_]+)\b")
LITERAL = re.compile(rf"[\"\'](?:{'|'.join(DOMAINS)})\.[a-z][a-z0-9_]*[\"\']")

# The instance name the registry snapshot was taken under, slugified.
INSTANCE = "n_i_n_a"

# Entities the reference rig cannot produce, so the snapshot cannot carry them:
# the dome nobody involved has hardware for, and the three weather channels
# this source reports as "NaN" (docs/2.0-renames.md).
ABSENT_FROM_THE_SNAPSHOT = {
    "dome_shutter_status", "weather_cloud_cover", "weather_sky_quality",
    "weather_star_fwhm",
}


def _entity_suffixes() -> set[str]:
    """Every entity the integration creates, less its instance prefix.

    Read from the plain committed list rather than scraped out of syrupy's
    `.ambr`, which is a snapshot serialization and not a stable interface.
    """
    listed = (ROOT / "tests" / "ha" / "snapshots" / "entity_ids.txt")
    return {
        entity.split(".", 1)[1].removeprefix(f"{INSTANCE}_")
        for entity in listed.read_text(encoding="utf-8").split()
    } | ABSENT_FROM_THE_SNAPSHOT


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_reads_an_entity_that_2_0_does_not_create(card: Path) -> None:
    """Every 1.4.5 card named entities phases B and C renamed or deleted."""
    named = set(TEMPLATED.findall(card.read_text(encoding="utf-8")))
    unknown = named - _entity_suffixes()

    assert not unknown, f"{card.name} reads removed entities: {sorted(unknown)}"


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_hardcodes_an_entity_id(card: Path) -> None:
    """2.0 ids carry the instance name, so an id without one is wrong on every
    install — and silently, since a missing entity just reads as no data."""
    hardcoded = set(LITERAL.findall(card.read_text(encoding="utf-8")))

    assert not hardcoded, f"{card.name} hardcodes: {sorted(hardcoded)}"


def test_the_weather_card_tells_an_absent_channel_from_a_reading() -> None:
    """A channel the active source cannot provide reads `unavailable`, and two
    sources on one rig are disjoint in both directions — so this is the normal
    case, not a fault to render as a zero."""
    card = (ROOT / "www" / "nina-weather-card.js").read_text(encoding="utf-8")

    assert "unavailable" in card


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_asks_for_the_stretch_by_the_wrong_name(card: Path) -> None:
    """`useAutoStretch` is not a parameter on /image/{index}; `autoPrepare` is."""
    assert "useAutoStretch" not in card.read_text()


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_puts_the_image_index_in_the_query_string(card: Path) -> None:
    """/image is not a route — the index is a path segment, /image/{index}."""
    assert "/image?" not in card.read_text()

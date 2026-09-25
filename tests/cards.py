"""Reading entity names back out of the Lovelace card sources.

Both suites parse the cards the same way and must not disagree about it:
`tests/unit/test_cards.py` checks the names against the committed entity list,
`tests/ha/test_entity_resolver.py` against a live registry.

Free of Home Assistant, because the unit suite imports it — which is why this
is not in `tests/helpers.py`.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "nina_astrophotography"
WWW_DIR = COMPONENT / "www"

DOMAINS = (
    "sensor",
    "binary_sensor",
    "switch",
    "light",
    "number",
    "select",
    "button",
    "image",
    "event",
)

# A card builds its ids from the instance prefix it is configured with:
# `sensor.${prefix}_mount_altitude`.
TEMPLATED = re.compile(rf"(?:{'|'.join(DOMAINS)})\.\$\{{[\w.]+\}}_([a-z0-9_]+)\b")
LITERAL = re.compile(rf"([\"'`])(?:{'|'.join(DOMAINS)})\.[a-z][a-z0-9_]*\1")
# A registry lookup: `_eid("<domain>", "<key>")`, or with a third argument where
# the entity-id suffix is not the translation key.
RESOLVED = re.compile(
    rf"_eid\(\"({'|'.join(DOMAINS)})\", \"([a-z0-9_]+)\"(?:, \"([a-z0-9_]+)\")?\)"
)
# Every way a card can invoke one, so a call the regex above cannot read is
# caught rather than silently unchecked.
INVOCATION = re.compile(r"\._eid\(")

# The instance name the registry snapshot was taken under, slugified.
INSTANCE = "n_i_n_a"


def lookups(card: Path) -> list[tuple[str, str, str]]:
    """Every registry lookup in one card as `(domain, key, suffix)`.

    The suffix is the third argument where the card passes one, else the key —
    which is what `_eid`'s own default does.
    """
    return [
        (domain, key, slug or key)
        for domain, key, slug in RESOLVED.findall(card.read_text(encoding="utf-8"))
    ]

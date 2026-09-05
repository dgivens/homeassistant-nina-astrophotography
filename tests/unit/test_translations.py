"""translations/en.json mirrors strings.json."""
import json
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "nina_astrophotography"


def test_the_english_translation_is_the_strings_file() -> None:
    """hassfest generates translations/ from strings.json for core integrations
    only; Home Assistant reads a custom integration's entity names from
    translations/<lang>.json alone, so the two must be kept identical by hand.
    """
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((COMPONENT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert english == strings

"""translations/en.json mirrors strings.json, and its actions services.yaml."""

import json
from pathlib import Path

import yaml

COMPONENT = (
    Path(__file__).resolve().parents[2] / "custom_components" / "nina_astrophotography"
)


def test_the_english_translation_is_the_strings_file() -> None:
    """Hassfest generates translations/ from strings.json for core integrations
    only; Home Assistant reads a custom integration's entity names from
    translations/<lang>.json alone, so the two must be kept identical by hand.
    """
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    english = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert english == strings


def _action_text(services: dict) -> dict:
    """Every action's and field's `name` and `description`, keyed by path."""
    text = {}
    for action, spec in services.items():
        for key in ("name", "description"):
            text[(action, key)] = spec.get(key)
        for field, field_spec in spec.get("fields", {}).items():
            for key in ("name", "description"):
                text[(action, field, key)] = field_spec.get(key)
    return text


def test_the_action_text_is_the_services_file() -> None:
    """The action editor shows the translation and falls back to
    `services.yaml` only where the translation has no text, so text edited in
    one alone never reaches the UI or reaches only part of it.
    """
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text(encoding="utf-8"))
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    assert _action_text(strings["services"]) == _action_text(services)

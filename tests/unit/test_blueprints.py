"""Checks that blueprint inputs are usable from templates, and fail safe.

`!input` is a YAML tag that substitutes a whole node, so it cannot appear
inside a template string. An input referenced from `{{ }}` must first be
bound in a `variables:` block, or it renders empty and fails silently.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

BLUEPRINTS = sorted(
    (Path(__file__).resolve().parents[2] / "blueprints").rglob("*.yaml")
)
assert BLUEPRINTS, "no blueprints found"


def load(path: Path) -> tuple[dict, list[tuple[str, int]]]:
    """Parse a blueprint, recording each `!input` name and the line it sits on."""
    referenced: list[tuple[str, int]] = []

    class Loader(yaml.SafeLoader):
        pass

    def construct(loader: yaml.SafeLoader, node: yaml.Node) -> str:
        """Record the reference, and stand the input's own name in for it, so a
        `variables:` block reads as the mapping it is."""
        name = loader.construct_scalar(node)
        referenced.append((name, node.start_mark.line))
        return name

    Loader.add_constructor("!input", construct)
    return yaml.load(path.read_text(), Loader=Loader), referenced


def declared(doc: dict) -> set[str]:
    """Every input name, flattened through sections.

    A section is an input entry that itself holds an `input:` map. `!input`
    names the leaf whichever section it sits in — sections are display only.
    """
    names: set[str] = set()
    for name, spec in (doc["blueprint"].get("input") or {}).items():
        nested = spec.get("input") if isinstance(spec, dict) else None
        names |= set(nested) if nested else {name}
    return names


def bound(doc: dict) -> set[str]:
    """Names a template can resolve.

    `trigger_variables` is included because a template *trigger* sees only
    that block, not `variables:` — no blueprint uses one yet, but the next
    one to add a template trigger needs this to be right.
    """
    return set(doc.get("variables") or {}) | set(doc.get("trigger_variables") or {})


def bindings(doc: dict) -> dict[str, str]:
    """Variable name -> the input it binds, for both variables blocks."""
    both = {**(doc.get("variables") or {}), **(doc.get("trigger_variables") or {})}
    return {alias: source for alias, source in both.items()
            if source in declared(doc)}


def binding_lines(raw: str) -> set[int]:
    """Lines inside a top-level variables: or trigger_variables: block."""
    inside: set[int] = set()
    keep = False
    for n, line in enumerate(raw.splitlines()):
        if re.match(r"^(variables|trigger_variables):", line):
            keep = True
            continue
        if keep and line[:1].strip():
            keep = False
        if keep:
            inside.add(n)
    return inside


def templates(raw: str) -> str:
    """Everything inside {{ }} and {% %}, concatenated."""
    return " ".join(re.findall(r"\{\{.*?\}\}|\{%.*?%\}", raw, re.S))


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_inputs_used_in_templates_are_bound(path: Path) -> None:
    doc, _ = load(path)
    text = templates(path.read_text())
    used = {
        name for name in declared(doc) if re.search(rf"\b{re.escape(name)}\b", text)
    }
    unbound = used - bound(doc)

    assert not unbound, (
        f"{sorted(unbound)} referenced from a template but not bound; "
        "add a `variables:` entry"
    )


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_every_declared_input_is_read(path: Path) -> None:
    """An input nothing reads renders a control that does nothing.

    Binding an input in `variables:` is not itself a read — the test above
    already requires that binding, so counting it would let the two tests
    satisfy each other and pass a knob wired to nothing. Using the bound
    variable in a template is.
    """
    raw = path.read_text()
    doc, referenced = load(path)
    skip = binding_lines(raw)
    text = templates(raw)

    read = {name for name, line in referenced if line not in skip} | {
        name for name in declared(doc) if re.search(rf"\b{re.escape(name)}\b", text)
    } | {
        source for alias, source in bindings(doc).items()
        if re.search(rf"\b{re.escape(alias)}\b", text)
    }
    unused = declared(doc) - read

    assert not unused, f"declared but never read: {sorted(unused)}"


# The lookbehind keeps `trigger.event.data` — a template path, not an id —
# out of the match.
ENTITY_ID = re.compile(
    r"(?<![\w.])(?:sensor|binary_sensor|switch|light|number|select|button"
    r"|image|event)\.[a-z0-9_]+\b"
)


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_no_blueprint_names_an_entity_id(path: Path) -> None:
    """Every 2.0 entity id carries the instance name, so a hardcoded one is
    wrong on every install but the author's — and the five shipped blueprints
    hardcoded ids that phases B and C renamed or deleted outright."""
    named = set(ENTITY_ID.findall(path.read_text()))

    assert not named, f"{path.name} hardcodes entity ids: {sorted(named)}"


def _blueprint(name: str) -> dict:
    doc, _ = load(next(p for p in BLUEPRINTS if p.name == name))
    return doc


def test_the_abort_fires_on_unsafe_not_on_safe() -> None:
    """Home Assistant's SAFETY device class is on = problem, so an abort
    triggering on `to: "off"` fires when the sky CLEARS. The failure is silent
    and its cost is an open roof under cloud."""
    unsafe = [t for t in _blueprint("weather_abort.yaml")["triggers"]
              if t.get("id") == "unsafe"]

    assert unsafe and unsafe[0]["to"] == "on"


def test_the_abort_also_fires_when_the_monitor_itself_disappears() -> None:
    """A separate trigger, not a merged state set: `unavailable` on the safety
    entity fires on every Home Assistant restart."""
    assert any(t.get("id") == "monitor_lost"
               for t in _blueprint("weather_abort.yaml")["triggers"])


def test_the_abort_triggers_on_no_weather_channel() -> None:
    """Weather is telemetry, not an abort authority: a forecast-backed source
    reads 0% cloud while you sit under a cloud."""
    triggers = _blueprint("weather_abort.yaml")["triggers"]

    assert all(t["trigger"] == "state" for t in triggers)


def test_the_meridian_warning_triggers_on_the_flip_event() -> None:
    """The flip fires when the reading reaches (Max - Min), not zero, and both
    bounds are per-profile — so N.I.N.A.'s own event is the reliable signal."""
    events = {t.get("event_type")
              for t in _blueprint("meridian_flip_warning.yaml")["triggers"]}

    assert "nina_mount_before_flip" in events

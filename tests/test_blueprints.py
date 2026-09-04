"""Checks that blueprint inputs are usable from templates.

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
    (Path(__file__).resolve().parents[1] / "blueprints").rglob("*.yaml")
)
assert BLUEPRINTS, "no blueprints found"


def load(path: Path) -> tuple[dict, list[tuple[str, int]]]:
    """Parse a blueprint, recording each `!input` name and the line it sits on."""
    referenced: list[tuple[str, int]] = []

    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor(
        "!input",
        lambda loader, node: referenced.append(
            (loader.construct_scalar(node), node.start_mark.line)
        ),
    )
    return yaml.load(path.read_text(), Loader=Loader), referenced


def declared(doc: dict) -> set[str]:
    return set(doc["blueprint"].get("input") or {})


def bound(doc: dict) -> set[str]:
    """Names a template can resolve.

    `trigger_variables` is included because a template *trigger* sees only
    that block, not `variables:` — no blueprint uses one yet, but the next
    one to add a template trigger needs this to be right.
    """
    return set(doc.get("variables") or {}) | set(doc.get("trigger_variables") or {})


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
def test_every_input_reference_names_a_declared_input(path: Path) -> None:
    """A typo'd `!input` makes Home Assistant reject the blueprint outright."""
    doc, referenced = load(path)
    unknown = {name for name, _ in referenced} - declared(doc)

    assert not unknown, f"!input names no such input: {sorted(unknown)}"


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.name)
def test_every_declared_input_is_read(path: Path) -> None:
    """An input nothing reads renders a control that does nothing.

    Binding an input in `variables:` does not count as reading it. The test
    above already requires that binding, so counting it here would let the two
    tests satisfy each other and pass a knob wired to nothing.
    """
    raw = path.read_text()
    doc, referenced = load(path)
    skip = binding_lines(raw)
    text = templates(raw)

    read = {name for name, line in referenced if line not in skip} | {
        name for name in declared(doc) if re.search(rf"\b{re.escape(name)}\b", text)
    }
    unused = declared(doc) - read

    assert not unused, f"declared but never read: {sorted(unused)}"

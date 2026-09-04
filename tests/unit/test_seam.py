"""The seam holds: nothing HA-free imports Home Assistant.

Static, not runtime. Once pytest-homeassistant-custom-component is installed its
pytest11 entry point imports Home Assistant before collection, so a sys.modules
check can never pass.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "nina_astrophotography"
)

SEAM_ROOTS = ("api", "derive.py", "session.py", "const.py")


def _seam_files() -> set[Path]:
    """Every seam module plus the transitive closure of its own imports."""
    pending = set()
    for root in SEAM_ROOTS:
        target = COMPONENT / root
        pending.update(target.rglob("*.py") if target.is_dir() else {target})

    seen: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in seen or not path.exists():
            continue
        seen.add(path)
        for name in _first_party_imports(path):
            candidate = COMPONENT / (name.replace(".", "/") + ".py")
            package = COMPONENT / name.replace(".", "/") / "__init__.py"
            pending.update(p for p in (candidate, package) if p.exists())
    return seen


def _first_party_imports(path: Path) -> set[str]:
    """Relative-import targets, resolved to dotted paths under the component."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = path.relative_to(COMPONENT).parent.as_posix().replace("/", ".")
    package = "" if package == "." else package
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            parts = package.split(".") if package else []
            parts = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
            base = ".".join(p for p in [*parts, node.module or ""] if p)
            found.add(base)
            found.update(f"{base}.{alias.name}" if base else alias.name
                         for alias in node.names)
    return found


@pytest.mark.parametrize("path", sorted(_seam_files()), ids=lambda p: p.name)
def test_seam_module_does_not_import_homeassistant(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names = [node.module or ""]
        else:
            continue
        assert not any(n == "homeassistant" or n.startswith("homeassistant.")
                       for n in names), f"{path.name} imports Home Assistant"


def test_seam_guard_sees_the_modules_it_claims_to() -> None:
    """A guard that collects nothing passes vacuously."""
    assert {"const.py"} <= {p.name for p in _seam_files()}


WIRE_MODULES = ("api.v2.mapper", "api.v2.schema")
WIRE_PACKAGE = "api.v2"
WIRE_NAMES = {"mapper", "schema"}


def _ends_at(module: str, candidates: tuple[str, ...]) -> bool:
    """True when a dotted import path ends at one of `candidates`."""
    return any(module == c or module.endswith("." + c) for c in candidates)


def _imports_the_wire_layer(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(_ends_at(alias.name, WIRE_MODULES) for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            # `node.module` is the path as written; relative depth does not
            # change which module it ends at, so the tail is enough.
            module = node.module or ""
            if _ends_at(module, WIRE_MODULES):
                return True
            if (_ends_at(module, (WIRE_PACKAGE,))
                    and any(alias.name in WIRE_NAMES for alias in node.names)):
                return True
    return False


def test_nothing_above_the_seam_imports_the_wire_layer() -> None:
    """The client TYPE may be imported; the mapper and the generated schema may
    not. Holding a NinaClientV2 is not knowing a wire format — calling
    map_equipment_info, or naming a TypedDict, is.

    Read from the import statements, not from the file's text: `from .api.v2
    import mapper` names the wire layer without ever spelling `api.v2.mapper`.
    """
    above = [p for p in COMPONENT.rglob("*.py")
             if "api" not in p.relative_to(COMPONENT).parts]
    offenders = [p.name for p in above if _imports_the_wire_layer(p)]
    assert not offenders, f"wire layer imported above the seam: {offenders}"

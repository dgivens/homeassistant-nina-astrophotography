"""Pure walks over the `/sequence/json` tree.

Not in `derive.py`, which is version-independent maths: the tree's shape is
partly a Target Scheduler fact, so the mapper normalizes it into `SequenceNode`
and the walk lives here.

**Node `Status` is not read.** It persists from the loaded sequence file and
from prior runs, so an idle rig reports `RUNNING` nodes with nothing happening
(§6.2) — which is why `binary_sensor.sequence_running` comes from the activity
heuristic instead. What is read here is `Iterations` and `TargetName`, which a
node carries only when it actually has them.

**A Target Scheduler rig produces neither**, so on the reference rig both walks
return `None` and `sensor.sequence_target` falls back to `TS-TARGETSTART`
(`session.latest_target`). That is the truth about what this API exposes, not a
failure to handle.

**Neither walk has been run against a captured plain sequence.** Both
`/sequence/json` captures are from the Target Scheduler rig and contain no
`TargetName` and no `Iterations` at all, so what these functions do on the rigs
they exist for is unverified — and `/sequence/state` nests `TargetName` inside
a `Target` object, which `map_sequence` drops along with every other
dict-valued key. If `/sequence/json` nests it the same way, `target_name`
returns `None` everywhere and the fallback is dead code. A capture of a loaded
Advanced Sequencer run is what settles it; until then treat both as provisional
and do not build on them.
"""
from __future__ import annotations

import logging
from collections.abc import Iterator

from .api.models import SequenceNode

_LOGGER = logging.getLogger(__name__)


def _walk(root: SequenceNode | None) -> Iterator[SequenceNode]:
    """Every node, parents before children."""
    if root is None:
        return
    yield root
    for child in root.children:
        yield from _walk(child)


def target_name(root: SequenceNode | None) -> str | None:
    """The `TargetName` of the LAST node carrying one, in pre-order.

    Last rather than deepest: a sequence's targets are siblings under one
    container, so depth does not order them and pre-order at least follows the
    order they are written in. On a tree with one target the two agree; on a
    multi-target sequence this reports the last one in the file, which is not
    necessarily the one being shot — see the module docstring, this whole path
    is unverified against a captured plain sequence.
    """
    names = [str(node.attributes["TargetName"]) for node in _walk(root)
             if node.attributes.get("TargetName")]
    return names[-1] if names else None


def progress_percent(root: SequenceNode | None) -> float | None:
    """How far through its iterations the innermost counting node is.

    `Iterations` is the wire's own progress text, `"3/10"`. The innermost
    counting node is the answer, or there is none: falling outward to an
    enclosing container would report the night's progress as this target's,
    which is plausible enough to be believed and wrong.

    Clamped to 0–100. `-1` is a live sentinel elsewhere in this API and the
    sensor carries `state_class: measurement`, so an out-of-range value would
    enter long-term statistics and stay there.
    """
    counts = [node.iterations for node in _walk(root) if node.iterations]
    if not counts:
        return None
    text = counts[-1]
    done, _, total = text.partition("/")
    try:
        completed, expected = int(done.strip()), int(total.strip())
    except ValueError:
        _LOGGER.debug("Unparseable sequence Iterations %r; reporting none", text)
        return None
    if expected <= 0:
        return None
    return min(max(completed / expected * 100.0, 0.0), 100.0)

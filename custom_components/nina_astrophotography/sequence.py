"""Pure walks over the `/sequence/json` tree.

Not in `derive.py`, which is version-independent maths: the tree's shape is
partly a Target Scheduler fact, so the mapper normalizes it into `SequenceNode`
and the walk lives here.

**Node `Status` is not read.** It persists from the loaded sequence file and
from prior runs, so an idle rig reports `RUNNING` nodes with nothing happening
(§6.2) — which is why `binary_sensor.sequence_running` comes from the activity
heuristic instead. What is read here is `Iterations` and `TargetName`, which a
node carries only when it actually has them.

**A Target Scheduler rig produces neither.** Its imaging container holds the
target list internally, so the tree it publishes names no target and counts no
iterations. That is not a failure to handle: the target comes from
`TS-TARGETSTART` instead (`session.latest_target`), and the progress sensor
reads `unknown`, which is the truth about what this API exposes.
"""
from __future__ import annotations

from collections.abc import Iterator

from .api.models import SequenceNode


def _walk(root: SequenceNode | None) -> Iterator[SequenceNode]:
    """Every node, parents before children."""
    if root is None:
        return
    yield root
    for child in root.children:
        yield from _walk(child)


def target_name(root: SequenceNode | None) -> str | None:
    """The `TargetName` of the deepest node carrying one.

    Deepest, because a sequence nests its targets inside the container that
    holds them all: the innermost is the one being shot.
    """
    names = [str(node.attributes["TargetName"]) for node in _walk(root)
             if node.attributes.get("TargetName")]
    return names[-1] if names else None


def progress_percent(root: SequenceNode | None) -> float | None:
    """How far through its iterations the innermost counting node is.

    `Iterations` is the wire's own progress text, `"3/10"`. Anything else —
    absent, unparseable, or a zero total — is `None`: a percentage invented
    from a shape we did not recognise is worse than no reading.
    """
    counts = [node.iterations for node in _walk(root) if node.iterations]
    for text in reversed(counts):
        done, _, total = text.partition("/")
        try:
            completed, expected = int(done.strip()), int(total.strip())
        except ValueError:
            continue
        if expected > 0:
            return completed / expected * 100.0
    return None

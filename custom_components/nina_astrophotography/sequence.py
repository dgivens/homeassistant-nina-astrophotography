"""Pure walks over the `/sequence/json` tree.

**Only the root containers' `Status` is read.** Deeper status persists from
the loaded file and earlier runs; a stop resets the root that was running.

**A Target Scheduler rig carries no `TargetName` or `Iterations`**, so there
`target_name` and `progress_percent` return `None`, and the target comes from
`TS-TARGETSTART` instead. Neither walk has been checked against a captured
plain sequence: `/sequence/state` nests `TargetName` in a `Target` object,
which the mapper drops, and if `/sequence/json` does too, `target_name` never
finds one.
"""

from collections.abc import Iterable, Iterator
import logging

from .api.models import NinaEvent, SequenceNode

_LOGGER = logging.getLogger(__name__)

# A run, not a night: `SEQUENCE-FINISHED` also fires on a manual stop.
_SEQUENCE_STARTED = "SEQUENCE-STARTING"
_SEQUENCE_BRACKET = frozenset({_SEQUENCE_STARTED, "SEQUENCE-FINISHED"})


def _walk(root: SequenceNode | None) -> Iterator[SequenceNode]:
    """Every node, parents before children."""
    if root is None:
        return
    yield root
    for child in root.children:
        yield from _walk(child)


def running(
    root: SequenceNode | None, events: Iterable[NinaEvent], generation: str | None
) -> bool:
    """Whether the sequencer is executing, which is not whether it is imaging:
    it runs through Target Scheduler's waits and safety loops.

    A running root container says yes. Otherwise the newest `SEQUENCE-*`
    event decides, a start outranking a finish at the same instant. Neither
    suffices alone: the roots still read CREATED just after
    `SEQUENCE-STARTING`, and a run started before the event history's window
    has no event at all.
    """
    if root is not None and any(child.status == "RUNNING" for child in root.children):
        return True
    bracketing = [
        event
        for event in events
        if event.name in _SEQUENCE_BRACKET and event.generation == generation
    ]
    if not bracketing:
        return False
    newest = max(
        bracketing, key=lambda event: (event.time, event.name == _SEQUENCE_STARTED)
    )
    return newest.name == _SEQUENCE_STARTED


def target_name(root: SequenceNode | None) -> str | None:
    """The `TargetName` of the LAST node carrying one, in pre-order.

    Targets are siblings, so depth does not order them. With several, this
    is the last in the file, not necessarily the one being shot.
    """
    names = [node.target_name for node in _walk(root) if node.target_name]
    return names[-1] if names else None


def progress_percent(root: SequenceNode | None) -> float | None:
    """How far through its iterations the innermost counting node is.

    Parses `Iterations` (`"3/10"`), clamped to 0–100 to keep sentinels out
    of long-term statistics.
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

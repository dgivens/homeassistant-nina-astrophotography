"""Pure walks over the `/sequence/json` tree.

Not in `derive.py`, which is version-independent maths: the tree's shape is
partly a Target Scheduler fact, so the mapper normalizes it into `SequenceNode`
and the walk lives here.

**Only the ROOT containers' `Status` is read**, by `running`. Deeper status
persists from the loaded sequence file and from prior runs, so a node reads
`RUNNING` long after its run (§6.2); the roots do not, because a stop resets
the container that was running. What else is read here is `Iterations` and
`TargetName`, which a node carries only when it actually has them.

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
from collections.abc import Iterable, Iterator
import logging

from .api.models import NinaEvent, SequenceNode

_LOGGER = logging.getLogger(__name__)

# `SEQUENCE-FINISHED` fires on a manual stop as well as at end of night, so the
# pair brackets a run rather than a night.
_SEQUENCE_STARTED = "SEQUENCE-STARTING"
_SEQUENCE_BRACKET = frozenset({_SEQUENCE_STARTED, "SEQUENCE-FINISHED"})


def _walk(root: SequenceNode | None) -> Iterator[SequenceNode]:
    """Every node, parents before children."""
    if root is None:
        return
    yield root
    for child in root.children:
        yield from _walk(child)


def running(root: SequenceNode | None,
            events: Iterable[NinaEvent],
            generation: str | None) -> bool:
    """Whether the sequencer is executing — which is not whether it is imaging.

    A sequence spends hours not imaging and still running: Target Scheduler
    waiting out a target's start window, a safety loop waiting for conditions,
    a wait for full dark. `imaging` (§6.2) answers the other question.

    The ROOT containers seed it, and neither source suffices alone:

    - Ten seconds after `SEQUENCE-STARTING` every root still reads CREATED, so
      the tree is blind on the leading edge of a run.
    - A sequence started before the event history's window leaves no
      `SEQUENCE-*` event at all, so the ledger is blind to it entirely.

    The tree is asked first and the events only break a tie, which is what
    keeps a stale `SEQUENCE-FINISHED` from an earlier run in the same process
    from overriding a tree that says a container is RUNNING right now.

    Only the TOP-LEVEL nodes are read, never the nodes below them: deep status
    persists from the loaded file and from prior runs (§6.2), and a stop resets
    the container that was RUNNING while leaving its finished siblings
    FINISHED. `/sequence/json` sits on the sequence tier, so the tree is up to
    five minutes stale while idle; both `SEQUENCE-*` events queue a refetch, so
    only a rig whose socket is down waits that long.

    On the same timestamp a start outranks a finish: a run observed starting at
    the instant another ended is the live one.
    """
    if root is not None and any(child.status == "RUNNING" for child in root.children):
        return True
    bracketing = [event for event in events
                  if event.name in _SEQUENCE_BRACKET and event.generation == generation]
    if not bracketing:
        return False
    newest = max(bracketing,
                 key=lambda event: (event.time, event.name == _SEQUENCE_STARTED))
    return newest.name == _SEQUENCE_STARTED


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

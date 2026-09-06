"""The `/sequence/json` walks.

Node `Status` is deliberately not read (§6.2), so nothing here asserts on it.
"""
from __future__ import annotations

import pytest
from helpers import load_fixture

from nina_astrophotography.api.models import SequenceNode
from nina_astrophotography.api.v2.mapper import map_sequence
from nina_astrophotography.sequence import progress_percent, target_name


def _node(name: str, *children: SequenceNode, **own) -> SequenceNode:
    return SequenceNode(
        name=name,
        status=own.pop("status", "RUNNING"),
        iterations=own.pop("iterations", None),
        children=children,
        attributes=own,
    )


@pytest.mark.parametrize(
    "fixture",
    ["imaging_guiding_sequence_json.json", "dawn_sequence_complete.json"],
    ids=["running", "complete"],
)
def test_a_target_scheduler_tree_names_no_target_and_counts_nothing(
    fixture: str,
) -> None:
    """Its imaging container holds the target list internally. `None` is the
    truth about what this API exposes, not a parse that failed."""
    tree = map_sequence(load_fixture(fixture))
    assert target_name(tree) is None
    assert progress_percent(tree) is None


def test_the_last_named_target_in_pre_order_wins() -> None:
    """Last, not deepest — depth does not order sibling targets. Pinned so the
    ordering is a decision rather than an accident of the walk."""
    tree = _node("Sequence", _node("Targets", TargetName="M31"),
                 TargetName="Tonight")
    assert target_name(tree) == "M31"


def test_a_deeper_target_does_not_outrank_a_later_shallow_one() -> None:
    """The behaviour the docstring used to claim the opposite of."""
    tree = _node("Sequence",
                 _node("A", _node("B", TargetName="deep")),
                 _node("C", TargetName="shallow"))
    assert target_name(tree) == "shallow"


def test_progress_is_the_innermost_counting_nodes_own_fraction() -> None:
    tree = _node("Sequence", _node("Target", iterations="3/10"), iterations="1/2")
    assert progress_percent(tree) == 30.0


@pytest.mark.parametrize("innermost", ["0/0", "many/10", "3.0/10"], ids=repr)
def test_an_unusable_innermost_count_does_not_fall_out_to_its_container(
    innermost: str,
) -> None:
    """Reporting the enclosing container's fraction would present the night's
    progress as this target's — plausible, unlogged, and wrong."""
    tree = _node("Sequence", _node("Target", iterations=innermost),
                 iterations="1/2")
    assert progress_percent(tree) is None


@pytest.mark.parametrize(
    ("iterations", "expected"), [("-1/10", 0.0), ("12/10", 100.0)], ids=repr
)
def test_a_count_outside_its_own_range_is_clamped(
    iterations: str, expected: float
) -> None:
    """`-1` is a live sentinel elsewhere in this API, and the sensor carries
    `state_class: measurement` — an out-of-range value would enter long-term
    statistics and stay there."""
    assert progress_percent(_node("Sequence", iterations=iterations)) == expected


@pytest.mark.parametrize(
    "iterations", ["", "3", "3/0", "many/10", None], ids=repr
)
def test_an_iteration_count_that_is_not_a_fraction_reads_nothing(
    iterations: str | None,
) -> None:
    """A percentage invented from a shape we did not recognise is worse than no
    reading — a zero total included."""
    assert progress_percent(_node("Sequence", iterations=iterations)) is None


def test_no_sequence_at_all_is_no_reading() -> None:
    """`/sequence/json` answers 409 until a sequence is loaded."""
    assert target_name(None) is None
    assert progress_percent(None) is None

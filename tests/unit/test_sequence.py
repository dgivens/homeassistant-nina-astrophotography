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


def test_the_innermost_named_target_wins() -> None:
    """A sequence nests its targets inside the container holding them all."""
    tree = _node("Sequence", _node("Targets", TargetName="M31"),
                 TargetName="Tonight")
    assert target_name(tree) == "M31"


def test_progress_is_the_innermost_counting_nodes_own_fraction() -> None:
    tree = _node("Sequence", _node("Target", iterations="3/10"), iterations="1/2")
    assert progress_percent(tree) == 30.0


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

"""The test VM's sequences are saved with no progress.

N.I.N.A. writes each instruction's progress into a sequence file. One saved
after a run loads with its loops already complete, and skips them.
"""

import json
from pathlib import Path

import pytest

RIG = Path(__file__).resolve().parents[1] / "fixtures" / "rig"
_PROGRESS = ("CompletedIterations", "ExposureCount")


def _progress(node: object) -> list[int]:
    if isinstance(node, dict):
        own = [node[key] for key in _PROGRESS if key in node]
        return own + [n for value in node.values() for n in _progress(value)]
    if isinstance(node, list):
        return [n for item in node for n in _progress(item)]
    return []


@pytest.mark.parametrize("sequence", sorted(RIG.glob("*.json")), ids=lambda p: p.name)
def test_a_rig_sequence_is_saved_with_no_progress(sequence: Path) -> None:
    assert not any(_progress(json.loads(sequence.read_text(encoding="utf-8"))))

"""Properties of the fold, sampled from the 122 real captured frames.

Every generated input is real wire data — hypothesis samples the corpus rather
than inventing frames, so a passing property says something about N.I.N.A.
"""
from __future__ import annotations

import json
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nina_astrophotography.api.v2.mapper import map_frame
from nina_astrophotography.session import fold

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_document = json.loads(
    (FIXTURES / "dawn_image_history_with_flats.json").read_text(encoding="utf-8")
)
_document.pop("_meta", None)
FRAMES = [map_frame(f, generation="g1") for f in _document["Response"]]

settings.register_profile("nina", max_examples=50, deadline=None, derandomize=True,
                          suppress_health_check=[HealthCheck.function_scoped_fixture])
settings.load_profile("nina")


@given(st.lists(st.sampled_from(FRAMES), min_size=1, max_size=30))
def test_fold_is_idempotent(sample) -> None:
    assert fold(sample + sample, [], "g1") == fold(sample, [], "g1")


@given(st.permutations(FRAMES[:20]))
def test_fold_is_order_independent(shuffled) -> None:
    assert fold(shuffled, [], "g1") == fold(FRAMES[:20], [], "g1")


@given(st.sampled_from(FRAMES))
def test_the_same_frame_by_any_path_folds_to_one_entry(frame) -> None:
    """Push, poll and replay are one idempotent operation."""
    assert fold([frame, frame, frame], [], "g1").image_count == 1

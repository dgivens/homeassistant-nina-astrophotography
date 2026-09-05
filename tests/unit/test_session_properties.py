"""Properties of the fold, sampled from the 122 real captured frames.

Every generated input is real wire data — hypothesis samples the corpus rather
than inventing frames, so a passing property says something about N.I.N.A.
"""
from __future__ import annotations

from helpers import load_fixture
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nina_astrophotography.api.v2.mapper import map_frame
from nina_astrophotography.session import fold

FRAMES = [map_frame(f, generation="g1")
          for f in load_fixture("dawn_image_history_with_flats.json")]
# Frames 50-69 straddle the LIGHT → FLAT transition (5 lights, then flats), so
# a permutation reorders calibration frames among lights, which is where an
# order-dependent aggregate would show.
STRADDLE = FRAMES[50:70]

settings.register_profile("nina", max_examples=50, deadline=None, derandomize=True,
                          suppress_health_check=[HealthCheck.function_scoped_fixture])
settings.load_profile("nina")


@given(st.lists(st.sampled_from(FRAMES), min_size=1, max_size=30))
def test_fold_is_idempotent(sample) -> None:
    assert fold(sample + sample, [], "g1") == fold(sample, [], "g1")


@given(st.permutations(STRADDLE))
def test_fold_is_order_independent(shuffled) -> None:
    assert fold(shuffled, [], "g1") == fold(STRADDLE, [], "g1")


@given(st.sampled_from(FRAMES))
def test_folding_one_frame_repeatedly_counts_it_once(frame) -> None:
    """Identity is (date, filename), so the same frame arriving three times is
    one frame. True push-vs-poll path equivalence — the same frame carried by
    an IMAGE-SAVE event and by /image-history — needs phase B's event-carried
    frame to reach the fold.
    """
    assert fold([frame, frame, frame], [], "g1").image_count == 1

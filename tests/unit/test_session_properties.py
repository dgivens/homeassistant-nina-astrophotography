"""Properties of the fold, sampled from the 122 real captured frames.

Every generated input is real wire data — hypothesis samples the corpus rather
than inventing frames, so a passing property says something about N.I.N.A.
"""

from hypothesis import HealthCheck, example, given, settings, strategies as st
from nina_astrophotography.api.v2.mapper import map_frame
from nina_astrophotography.session import fold, recent_frames

from helpers import load_fixture

FRAMES = [
    map_frame(f, generation="g1")
    for f in load_fixture("dawn_image_history_with_flats.json")
]
# Frames 50-69 straddle the LIGHT → FLAT transition (5 lights, then flats), so
# a permutation reorders calibration frames among lights, which is where an
# order-dependent aggregate would show.
STRADDLE = FRAMES[50:70]

settings.register_profile(
    "nina",
    max_examples=50,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
settings.load_profile("nina")


@given(st.lists(st.sampled_from(FRAMES), min_size=1, max_size=30))
def test_fold_is_idempotent(sample) -> None:
    assert fold(sample + sample, [], "g1") == fold(sample, [], "g1")


@given(st.permutations(STRADDLE))
def test_fold_is_order_independent(shuffled) -> None:
    assert fold(shuffled, [], "g1") == fold(STRADDLE, [], "g1")


def _some(frames: list) -> st.SearchStrategy:
    """Any number of `frames`: hypothesis's own lists stay too short to hold
    more than 20 lights.
    """
    return st.tuples(st.permutations(frames), st.integers(0, len(frames))).map(
        lambda drawn: drawn[0][: drawn[1]]
    )


# Drawn apart: every light predates every flat, so only a sample with fewer
# than 20 flats puts lights among the newest 20, and only one with more than
# 20 lights leaves some out.
LIGHTS = [f for f in FRAMES if f.image_type == "LIGHT"]
FLATS = [f for f in FRAMES if f.image_type != "LIGHT"]


@given(_some(LIGHTS), _some(FLATS))
# The edges of the newest 20, which a draw reaches only by chance.
@example(LIGHTS[-25:], FLATS[:19])  # lights at ages 19 and 20
@example(LIGHTS, FLATS[:20])  # every light behind exactly 20 flats
@example(LIGHTS[:20], [])  # exactly 20 frames
@example([], [])
def test_recent_frames_are_the_newest_twenty_and_the_newest_twenty_lights(
    lights, flats
) -> None:
    """Checked against the corpus's own saved order. The image proxy fetches a
    frame by its age, so a kept light carries its place among every frame, not
    among the ones kept.
    """
    sample = lights + flats
    held = {f.identity for f in sample}
    newest = [f for f in reversed(FRAMES) if f.identity in held]
    lights = [f for f in newest if f.image_type == "LIGHT"][:20]
    expected = [(age, f) for age, f in enumerate(newest) if age < 20 or f in lights]
    assert [(r.age, r.frame) for r in recent_frames(sample, "g1")] == expected

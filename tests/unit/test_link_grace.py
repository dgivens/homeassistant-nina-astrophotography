"""`LinkGrace` in `www/nina-entity-resolver.js`, run under node on a fake clock.

Each case is a script of `hold(since)` calls; each call yields `[held, armed]`:
whether the card keeps its view, and the delay of the redraw it armed.
"""

from pathlib import Path

import pytest

from helpers import needs_node, run_node

DRIVER = Path(__file__).parent / "link_grace.mjs"
GRACE = 30_000
T = 1_000_000  # an arbitrary moment on the fake clock

LIVE = {"at": T - 1, "hold": None}  # a render with the link up
RENDERED = [False, None]  # nothing held, nothing armed


def _lost(since: int, at: int = T) -> dict:
    return {"at": at, "hold": since}


CASES = {
    "a fresh card holds nothing": ([_lost(T - 10_000)], [RENDERED]),
    "a live card holds a blip": (
        [LIVE, _lost(T - 10_000)],
        [RENDERED, [True, GRACE - 10_000]],
    ),
    "a live card shows a link lost past the grace": (
        [LIVE, _lost(T - 45_000)],
        [RENDERED, RENDERED],
    ),
    "the lost link stays once the grace has run out": (
        [
            LIVE,
            _lost(T - 10_000),
            _lost(T - 10_000, at=T + 25_000),
            _lost(T - 10_000, at=T + 26_000),
        ],
        [RENDERED, [True, GRACE - 10_000], RENDERED, RENDERED],
    ),
    "a reset card holds nothing": (
        [LIVE, {"at": T, "reset": True}, _lost(T - 10_000)],
        [RENDERED, RENDERED],
    ),
    # Home Assistant's clock five minutes ahead.
    "a browser clock behind holds no longer than the grace": (
        [LIVE, _lost(T + 300_000)],
        [RENDERED, [True, GRACE]],
    ),
}


@pytest.fixture(scope="module")
def results() -> dict[str, list]:
    """Every case in one node run, each on a fresh `LinkGrace`."""
    return run_node(DRIVER, {name: steps for name, (steps, _) in CASES.items()})


@needs_node
@pytest.mark.parametrize("case", CASES)
def test_link_grace(results: dict[str, list], case: str) -> None:
    assert results[case] == CASES[case][1]

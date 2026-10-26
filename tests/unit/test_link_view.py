"""`LinkView` in `www/nina-entity-resolver.js`, run under node.

Each case is a script of the rig states a card is handed; each read yields
`[drawn, since, lost, stale]`: which state the card draws its readings from,
when N.I.N.A. stopped answering, whether the grace has run out, and whether
the readings drawn are not current.
"""

from datetime import datetime
from pathlib import Path

import pytest

from helpers import needs_node, run_node

DRIVER = Path(__file__).parent / "link_view.mjs"
QUIET_AT = int(datetime.fromisoformat("2026-10-26T02:00:00+00:00").timestamp() * 1000)

LIVE = ["live", None, False, False]

CASES = {
    "a live rig is drawn as it is": (["live"], [LIVE]),
    "a missed poll draws the held readings, stale": (
        ["live", "quiet"],
        [LIVE, ["quiet", QUIET_AT, False, True]],
    ),
    "past the grace the last live view stands in": (
        ["live", "quiet", "lost"],
        [LIVE, ["quiet", QUIET_AT, False, True], ["quiet", QUIET_AT, True, True]],
    ),
    "a card that never saw the link up draws the lost link": (
        ["lost"],
        [["lost", QUIET_AT, True, False]],
    ),
    "an answer ends the stale view": (
        ["live", "lost", "live"],
        [LIVE, ["live", QUIET_AT, True, True], LIVE],
    ),
    "a reset forgets the last live view": (
        ["live", "reset", "lost"],
        [LIVE, ["lost", QUIET_AT, True, False]],
    ),
    "without the reachable row the held rows still lose the link": (
        ["live", "lost_unreported"],
        [LIVE, ["live", None, True, True]],
    ),
    "a restored reachable row is an entry that failed to load": (
        ["failed"],
        [["failed", QUIET_AT, True, False]],
    ),
}


@pytest.fixture(scope="module")
def results() -> dict[str, list]:
    """Every case in one node run, each on a fresh `LinkView`."""
    return run_node(DRIVER, {name: steps for name, (steps, _) in CASES.items()})


@needs_node
@pytest.mark.parametrize("case", CASES)
def test_link_view(results: dict[str, list], case: str) -> None:
    assert results[case] == CASES[case][1]

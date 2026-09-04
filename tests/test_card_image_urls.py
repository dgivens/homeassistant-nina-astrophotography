"""The Lovelace cards build their own image URLs, and drift from api.py.

They call the Advanced API directly from the browser rather than going through
the integration, so a path or parameter corrected in `api.py` leaves them
behind — which is how the image-history endpoint stayed broken in
`nina-image-panel-card.js` for a release after it was fixed everywhere else.

Source checks: there is no JavaScript test harness here, and adding one to pin
a couple of string literals would cost more than it returns.
"""
from __future__ import annotations

from pathlib import Path

import pytest

CARDS = sorted((Path(__file__).resolve().parents[1] / "www").glob("*.js"))
assert CARDS, "no cards found"


@pytest.mark.parametrize("card", CARDS, ids=lambda p: p.name)
def test_no_card_asks_for_the_stretch_by_the_wrong_name(card: Path) -> None:
    """`useAutoStretch` is not a parameter on /image/{index}; `autoPrepare` is."""
    assert "useAutoStretch" not in card.read_text()

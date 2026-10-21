"""Captures land where `--out` says, never in the committed corpus by default."""

from pathlib import Path
import sys
from typing import Self

import pytest

from helpers import FakeSession, ok

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import capture_fixtures


class _OpenedSession(FakeSession):
    """A FakeSession that `async with aiohttp.ClientSession()` can open."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


async def test_a_capture_writes_only_into_the_directory_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = _OpenedSession({"version": ok("2.2.15.2")})
    monkeypatch.setattr(capture_fixtures.aiohttp, "ClientSession", lambda: session)

    assert (
        await capture_fixtures.capture("rig", 1888, "sim_night", False, tmp_path) == 0
    )

    written = sorted(path.name for path in tmp_path.iterdir())
    assert len(written) == len(capture_fixtures.ENDPOINTS)
    assert "sim_night_equipment_info.json" in written
    assert not list(capture_fixtures.FIXTURES.glob("sim_night_*"))

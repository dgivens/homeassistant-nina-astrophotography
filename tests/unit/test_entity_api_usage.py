"""The Entity method is singular — schedule_update_ha_state / async_write_ha_state.

A source check rather than a behavioural one, because the entity modules
import Home Assistant and this suite deliberately does not.

The plural spelling raises AttributeError inside a store or WebSocket
callback, where it is caught and logged rather than propagated, so the entity
stops updating while the traceback repeats once per frame. In
frame_stats_sensor.py that callback is the sole update path for all 25
sensors, which set should_poll False and take no coordinator.
"""
from __future__ import annotations

import re
from pathlib import Path

COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "nina_astrophotography"
)


def test_no_plural_schedule_update_ha_states() -> None:
    pattern = re.compile(r"\.schedule_update_ha_states\s*\(")
    offenders = [
        f"{path.name}:{i}"
        for path in sorted(COMPONENT.glob("*.py"))
        for i, line in enumerate(path.read_text().splitlines(), 1)
        if pattern.search(line)
    ]
    assert not offenders, (
        "schedule_update_ha_states() does not exist; use schedule_update_ha_state() "
        f"or async_write_ha_state(). Found at: {', '.join(offenders)}"
    )

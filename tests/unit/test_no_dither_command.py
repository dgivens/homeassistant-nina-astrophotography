"""Dithering is observable but not commandable, so nothing may offer it.

The Advanced API 2.2.15 specification has no dither route on the guider or
anywhere else — dithering happens inside a sequence and the only way it
surfaces is the GUIDER-DITHER WebSocket event, which stays. A service that
cannot ever succeed is worse than an absent one: it appears in the service
picker, an automation is written against it, and the failure only shows up
mid-session.

A source check rather than a behavioural one, because the service registry
lives in `__init__.py`, which imports Home Assistant, and this suite
deliberately does not.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from nina_astrophotography.api import NinaApiClient

COMPONENT = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "nina_astrophotography"
)


def test_the_client_offers_no_dither_call() -> None:
    assert not hasattr(NinaApiClient, "dither")


def test_no_dither_service_is_declared() -> None:
    services = yaml.safe_load((COMPONENT / "services.yaml").read_text())
    assert "guider_dither" not in services


def test_no_dither_service_is_translated() -> None:
    strings = json.loads((COMPONENT / "strings.json").read_text())
    assert "guider_dither" not in strings.get("services", {})


def test_the_dither_event_is_still_listened_for() -> None:
    """Removing the command must not lose the notification that it happened."""
    assert "GUIDER-DITHER" in (COMPONENT / "websocket.py").read_text()

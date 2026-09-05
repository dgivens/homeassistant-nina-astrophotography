"""The coordinator's error branches and clock, through public state.

`config_entry.runtime_data` and the `NinaData` it publishes are the contract
entities read, so reading them here is reading the public surface — not the
coordinator's internals.
"""
import logging
from datetime import datetime, timedelta, timezone

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.api.errors import (
    NinaConnectionError,
    NinaRequestError,
)

CLIENT = "custom_components.nina_astrophotography.api.v2.client.NinaClientV2"
LIGHT = "light.n_i_n_a_flat_panel_light"


def _raising(error: Exception):
    async def get_equipment(self):
        raise error

    return get_equipment


async def test_the_session_boundary_is_the_rigs_local_noon(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses, freezer
) -> None:
    """Frame dates carry the rig's offset (-5 h on the dawn capture), so the
    noon rollover must be the rig's noon. At 12:30 UTC — 07:30 on the rig, in
    the middle of its dawn flats — a UTC noon would start a new session and
    Home Assistant's own zone (US/Pacific here) would start it at 19:00 UTC."""
    freezer.move_to("2026-09-04T12:30:00+00:00")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    session = config_entry.runtime_data.coordinator.data.session
    assert session.session_start == datetime(
        2026, 9, 3, 12, 0, tzinfo=timezone(timedelta(hours=-5))
    )


async def test_an_unreachable_rig_makes_the_entities_unavailable(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, monkeypatch
) -> None:
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    monkeypatch.setattr(NinaClientV2, "get_equipment", _raising(NinaConnectionError("down")))
    await loaded_entry.runtime_data.coordinator.async_refresh()
    assert hass.states.get(LIGHT).state == "unavailable"


async def test_a_rejected_request_keeps_the_previous_state_and_logs_once(
    hass: HomeAssistant, loaded_entry: MockConfigEntry, monkeypatch, caplog
) -> None:
    """A rejection does not become right by retrying: every entity going
    unavailable and an error per poll would be noise about one condition."""
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    before = hass.states.get(LIGHT).state
    monkeypatch.setattr(NinaClientV2, "get_equipment", _raising(NinaRequestError("400")))
    with caplog.at_level(logging.ERROR):
        await loaded_entry.runtime_data.coordinator.async_refresh()
        await loaded_entry.runtime_data.coordinator.async_refresh()
    errors = [r for r in caplog.records
              if r.levelno == logging.ERROR
              and r.name.startswith("custom_components.nina_astrophotography")]
    assert hass.states.get(LIGHT).state == before
    assert len(errors) == 1


async def test_a_rejected_first_refresh_fails_the_entry_rather_than_retrying(
    hass: HomeAssistant, config_entry: MockConfigEntry, nina_responses, monkeypatch
) -> None:
    """With nothing to fall back on, a permanent rejection is ConfigEntryError:
    ConfigEntryNotReady would retry a condition that never clears."""
    from custom_components.nina_astrophotography.api.v2.client import NinaClientV2

    monkeypatch.setattr(NinaClientV2, "get_equipment", _raising(NinaRequestError("400")))
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR

"""Availability level 2, the grace before level 1, and `log-when-unavailable`.

Level 1 — `CoordinatorEntity.available` propagating `last_update_success` — is
Home Assistant's own and is not tested here (§8.2); it is pinned once, through
this integration's entity, by
`test_coordinator.test_an_unreachable_rig_makes_the_entities_unavailable`.

Level 3 — a sentinel reading as `unknown` rather than `unavailable` — is a
value concern of the sensor platforms and is pinned in their tests.
"""

import logging

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nina_astrophotography.const import DEFAULT_OUTAGE_GRACE
from custom_components.nina_astrophotography.coordinator import SOCKET_QUIET
from helpers import state_of

LIGHT = "light.n_i_n_a_flat_panel_light"
SOCKET_DOWN = "event socket has been down"


async def test_a_disconnected_device_makes_its_entities_unavailable(
    hass: HomeAssistant, set_up_with_flat_device
) -> None:
    """Level 2 alone, isolated from the panel's own range condition.

    On the wire a disconnected block maps to a zero range, which the platform's
    own condition also turns `unavailable`. Only `connected` is varied here, so
    with the captured range and `SupportsOnOff` true nothing else can.
    """
    await set_up_with_flat_device(connected=False)
    assert state_of(hass, LIGHT).state == "unavailable"


async def test_a_missed_poll_long_after_the_last_answer_keeps_the_last_data(
    hass: HomeAssistant, freezer, loaded_entry, advance
) -> None:
    """A 60 s poll interval puts every first failure past the grace period."""
    freezer.tick(2 * DEFAULT_OUTAGE_GRACE)
    await advance("nina_unreachable")
    assert state_of(hass, LIGHT).state != "unavailable"


@pytest.mark.parametrize(
    ("down_for", "available"),
    [(DEFAULT_OUTAGE_GRACE - 1, True), (DEFAULT_OUTAGE_GRACE, False)],
    ids=["inside the grace", "past it"],
)
async def test_failures_keep_the_last_data_until_the_grace_runs_out(
    hass: HomeAssistant, freezer, loaded_entry, advance, down_for, available
) -> None:
    await advance("nina_unreachable")
    freezer.tick(down_for)
    await advance("nina_unreachable")
    assert (state_of(hass, LIGHT).state != "unavailable") is available


async def test_failing_polls_do_not_extend_the_grace(
    hass: HomeAssistant, freezer, loaded_entry, advance
) -> None:
    await advance("nina_unreachable")
    for _ in range(3):
        freezer.tick(DEFAULT_OUTAGE_GRACE / 3)
        await advance("nina_unreachable")
    assert state_of(hass, LIGHT).state == "unavailable"


async def test_every_answer_restarts_the_grace(
    hass: HomeAssistant, freezer, loaded_entry, advance
) -> None:
    await advance("nina_unreachable")
    freezer.tick(DEFAULT_OUTAGE_GRACE - 1)
    await advance("imaging")
    await advance("nina_unreachable")
    freezer.tick(DEFAULT_OUTAGE_GRACE - 1)
    await advance("nina_unreachable")
    assert state_of(hass, LIGHT).state != "unavailable"


def _levels(caplog, text: str) -> list[int]:
    """The level of every record whose message contains `text`."""
    return [r.levelno for r in caplog.records if text in r.getMessage()]


async def test_an_outage_is_logged_once_at_info(
    hass: HomeAssistant, outage, loaded_entry: MockConfigEntry, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    await outage()
    await outage()
    assert _levels(caplog, "is unavailable") == [logging.INFO]


async def test_a_recovery_is_logged_once_at_info(
    hass: HomeAssistant, outage, loaded_entry: MockConfigEntry, advance, caplog
) -> None:
    await outage()
    caplog.set_level(logging.DEBUG)
    await advance("imaging")
    await advance("imaging")
    assert _levels(caplog, "is back online") == [logging.INFO]


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("states", "message"),
    [
        (["equipment_disconnected"] * 2, "Flat Panel disconnected"),
        (["equipment_disconnected", "imaging", "imaging"], "Flat Panel reconnected"),
    ],
    ids=["disconnection", "reconnection"],
)
async def test_a_device_transition_is_logged_once_at_info(
    hass: HomeAssistant,
    loaded_entry: MockConfigEntry,
    advance,
    caplog,
    states: list[str],
    message: str,
) -> None:
    """Per device, under the label the device registry shows.

    No capture holds the flat panel down, so its disconnected block is derived
    by the rule the corpus does show.
    """
    caplog.set_level(logging.DEBUG)
    for state in states:
        await advance(state)
    assert _levels(caplog, message) == [logging.INFO]


@pytest.mark.parametrize(
    ("down_for", "levels"),
    [(SOCKET_QUIET - 1, []), (SOCKET_QUIET, [logging.WARNING])],
    ids=["inside the threshold", "past it"],
)
async def test_a_socket_down_while_polls_succeed_is_warned_once(
    hass: HomeAssistant,
    freezer,
    loaded_entry: MockConfigEntry,
    socket_state,
    advance,
    caplog,
    down_for: int,
    levels: list[int],
) -> None:
    """The socket's own attempts log at `debug`, so without this a socket that
    cannot reconnect while the rig answers leaves pushed state stale unexplained.
    """
    socket_state(loaded_entry, connected=True)
    socket_state(loaded_entry, connected=False)
    caplog.set_level(logging.DEBUG)
    freezer.tick(down_for)
    await advance("imaging")
    await advance("imaging")
    assert _levels(caplog, SOCKET_DOWN) == levels


async def test_a_rig_outage_does_not_count_toward_the_socket_warning(
    hass: HomeAssistant,
    freezer,
    outage,
    loaded_entry: MockConfigEntry,
    socket_state,
    advance,
    caplog,
) -> None:
    """The poll logs the outage itself, and a socket waiting out its backoff
    after the rig returns is not a socket fault.
    """
    socket_state(loaded_entry, connected=True)
    socket_state(loaded_entry, connected=False)
    caplog.set_level(logging.DEBUG)
    await outage()
    freezer.tick(SOCKET_QUIET)
    await outage()
    await advance("imaging")
    assert _levels(caplog, SOCKET_DOWN) == []


async def test_a_socket_reconnecting_after_the_warning_is_logged_at_info(
    hass: HomeAssistant,
    freezer,
    loaded_entry: MockConfigEntry,
    socket_state,
    advance,
    caplog,
) -> None:
    socket_state(loaded_entry, connected=True)
    socket_state(loaded_entry, connected=False)
    freezer.tick(SOCKET_QUIET)
    await advance("imaging")
    caplog.set_level(logging.DEBUG)
    socket_state(loaded_entry, connected=True)
    await hass.async_block_till_done()
    assert _levels(caplog, "event socket at nina.local is back") == [logging.INFO]


async def test_first_sight_of_a_device_is_not_a_reconnection(
    hass: HomeAssistant, config_entry: MockConfigEntry, rig, caplog, set_up_at
) -> None:
    """Equipment routinely connects long after Home Assistant starts. Only a
    slot that has been seen connected and gone down has anything to recover
    from, so a first connection is not a transition.
    """
    caplog.set_level(logging.INFO)
    await set_up_at(hass, config_entry, rig, "partial_equipment_connection")

    rig.goto("imaging")
    await config_entry.runtime_data.coordinator.async_refresh()
    assert "reconnected" not in caplog.text

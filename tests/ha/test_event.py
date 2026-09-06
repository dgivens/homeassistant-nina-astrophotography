"""event.nina_error: discrete occurrences with no state to hold.

Best-effort and solver-specific (§3.4). What is asserted here is the mapping
from a wire event to the type an automation triggers on, and the one rule that
is easy to get wrong: replay must not re-fire the night's failures at whatever
is listening.
"""
from homeassistant.core import HomeAssistant

ERROR = "event.n_i_n_a_error"


def _wire(name: str) -> dict:
    """A bare `{Event, Time}` push, which is every ERROR-* event's shape."""
    return {"Event": name, "Time": "2026-09-04T03:15:00"}


async def test_a_platesolve_error_fires_the_event_entity(
    hass: HomeAssistant, loaded_entry, push
) -> None:
    push(_wire("ERROR-PLATESOLVE"))
    await hass.async_block_till_done()
    assert hass.states.get(ERROR).attributes["event_type"] == "platesolve_failed"


async def test_a_camera_download_timeout_fires_it_too(
    hass: HomeAssistant, loaded_entry, push
) -> None:
    """Named from the plugin's source and never seen in a capture: if the name
    is wrong this row costs nothing, and if it is right it is the one warning a
    stalled camera gives."""
    push(_wire("CAMERA-DOWNLOAD-TIMEOUT"))
    await hass.async_block_till_done()
    assert hass.states.get(ERROR).attributes["event_type"] == "camera_download_timeout"


async def test_an_event_the_entity_has_no_type_for_fires_nothing(
    hass: HomeAssistant, loaded_entry, push
) -> None:
    """A night pushes hundreds of events through the same subscription."""
    push(_wire("GUIDER-DITHER"))
    await hass.async_block_till_done()
    assert hass.states.get(ERROR).state == "unknown"


async def test_the_nights_replayed_failures_do_not_fire_at_startup(
    hass: HomeAssistant, loaded_entry
) -> None:
    """The dawn `/event-history` holds an ERROR-PLATESOLVE. Replay folds into
    the coordinator without reaching subscribers, so a Home Assistant restart
    does not re-announce hours-old failures."""
    assert hass.states.get(ERROR).state == "unknown"


async def test_the_error_entity_ships_diagnostic(
    hass: HomeAssistant, loaded_entry, entity_registry
) -> None:
    assert entity_registry.async_get(ERROR).entity_category == "diagnostic"


async def test_a_hung_autofocus_fires_when_the_fold_first_calls_it_failed(
    hass: HomeAssistant, inside_the_dawn_session, loaded_entry, push
) -> None:
    """There is no autofocus-failed event to subscribe to: a failure is a start
    with no finish, so the rising edge of the fold's verdict is the signal.

    The start is pushed an hour and a half before the frozen clock, newer than
    every AUTOFOCUS-FINISHED the dawn history holds, so nothing answers it.
    """
    push({"Event": "AUTOFOCUS-STARTING", "Time": "2026-09-04T11:00:00+00:00"})
    await hass.async_block_till_done()
    assert hass.states.get(ERROR).attributes["event_type"] == "autofocus_timeout"


async def test_a_failure_that_predates_home_assistant_is_history_not_an_alarm(
    hass: HomeAssistant, config_entry, rig, inside_the_dawn_session
) -> None:
    """Set up with the verdict already true: seeding from the first published
    fold is what keeps a restart from announcing last night's hung run."""
    rig.goto("autofocus_timed_out")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ERROR).state == "unknown"

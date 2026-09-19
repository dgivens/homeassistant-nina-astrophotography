"""The stall alert's gates and clocks, run rather than schema-checked.

`test_blueprints.py` proves Home Assistant ACCEPTS this blueprint. It cannot
prove the config does anything, and two defects here were valid YAML that suite
was happy with: gates written inside a `choose` branch, where a failing
condition aborts only the branch and the parent sequence alerts anyway, and
clocks that started before the sequence did. Both made the blueprint alert
every minute of every night while the suite stayed green.

So these tests fire the triggers and read the notification that comes out.

The inputs are this file's own, and every tuning input is left at its shipped
default, read from the blueprint itself. Borrowing `test_blueprints.py`'s map
made cases silently vacuous: it pins `night_only` off, so the default that
mutes the twelve-hour daytime wait was never once executed.
"""
import asyncio
from datetime import timedelta

from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    async_fire_time_changed,
    async_mock_service,
)
import yaml

from tests.ha.conftest import BLUEPRINTS

BLUEPRINT = "imaging_stall_alert.yaml"
FILE = BLUEPRINTS / "automation/nina_astrophotography" / BLUEPRINT
T0 = dt_util.parse_datetime("2026-09-17T01:00:00+00:00")


def _defaults() -> dict:
    """Every input's shipped default, flattened through the sections.

    Read from the blueprint rather than restated here: a threshold copied into
    a test stops matching the moment the default moves, and the test goes quiet
    instead of failing.
    """
    class Loader(yaml.SafeLoader):
        pass

    Loader.add_constructor("!input", lambda l, n: l.construct_scalar(n))
    doc = yaml.load(FILE.read_text(), Loader=Loader)
    leaves: dict = {}
    for name, spec in doc["blueprint"]["input"].items():
        leaves.update(spec.get("input") or {name: spec})
    return {n: s["default"] for n, s in leaves.items() if "default" in s}


DEFAULTS = _defaults()
QUIET_MINUTES = DEFAULTS["imaging_quiet_minutes"]
SETTLE_MINUTES = DEFAULTS["settle_minutes"]

# Enough past the quiet threshold to alert, and still short of the frame-age
# threshold, so these cases turn on the gate under test rather than on which
# threshold happened to trip first.
STALLED = timedelta(minutes=QUIET_MINUTES + 5)

SAFETY = "binary_sensor.rig_safety_monitor_unsafe"

INPUTS = {
    "nina_rig": "device-id",
    "sequencer_running": "binary_sensor.rig_sequencer_running",
    "imaging": "binary_sensor.rig_imaging",
    "scheduler_waiting": "binary_sensor.rig_scheduler_waiting",
    "mount_at_park": "binary_sensor.rig_mount_at_park",
    "last_frame_at": "sensor.rig_last_frame_at",
    "camera_state": "sensor.rig_camera_state",
    "last_image_target": "sensor.rig_last_image_target",
    "sequence_target": "sensor.rig_sequence_target",
    "camera_temperature": "sensor.rig_camera_temperature",
    "camera_cooler_power": "sensor.rig_camera_cooler_power",
    "safety_unsafe": [SAFETY],
}

# A rig mid-night with nothing arriving. `last_frame_at` holds LAST night's
# frame: N.I.N.A. reports the newest frame it knows of, which survives across
# nights while it stays up, so this is what a real 20:00 start looks like.
RIG = {
    "binary_sensor.rig_sequencer_running": "off",
    "binary_sensor.rig_imaging": "off",
    "binary_sensor.rig_scheduler_waiting": "off",
    SAFETY: "off",
    "binary_sensor.rig_mount_at_park": "off",
    "sensor.rig_last_frame_at": "2026-09-16T10:00:00+00:00",
    "sensor.rig_camera_state": "Idle",
    "sensor.rig_last_image_target": "M31",
    "sensor.rig_sequence_target": "M31",
    "sensor.rig_camera_temperature": "-10.0",
    "sensor.rig_camera_cooler_power": "42",
}


def alert(hass: HomeAssistant) -> dict | None:
    """The blueprint's persistent notification, or None.

    Persistent notifications are not entities — `hass.states` never shows them.
    """
    raised = hass.data.get("persistent_notification") or {}
    return next(iter(raised.values()), None)


async def tick(hass: HomeAssistant, when) -> None:
    """Fire the quiet arm's minute tick and let the run finish.

    Zero-delay yields, never `asyncio.sleep(d)`: under `freezer` the event
    loop's monotonic clock is frozen too, so a real sleep never wakes.
    `async_block_till_done` is no good either — on a tick that DOES alert, the
    run parks in `wait_for_trigger` and never returns.
    """
    async_fire_time_changed(hass, when)
    for _ in range(2000):
        await asyncio.sleep(0)
        if alert(hass):
            return


@pytest.fixture
async def watching(hass: HomeAssistant, installed, freezer):
    """Set the blueprint up over a rig whose sequencer is not running yet.

    Returns the clock, and takes input overrides for the cases that turn on an
    input rather than on a state. `notify=False` leaves the notify integration
    unloaded, so `notify.send_message` does not exist.
    """
    async def _set_up(notify: bool = True, **overrides):
        freezer.move_to(T0)
        hass.states.async_set("sun.sun", "below_horizon")
        for entity, state in RIG.items():
            hass.states.async_set(entity, state)
        assert await async_setup_component(hass, "persistent_notification", {})
        if notify:
            assert await async_setup_component(hass, "notify", {})
        assert await async_setup_component(hass, AUTOMATION_DOMAIN, {
            AUTOMATION_DOMAIN: {"use_blueprint": {
                "path": f"nina_astrophotography/{BLUEPRINT}",
                "input": INPUTS | overrides}}})
        await hass.async_block_till_done()
        return freezer

    return _set_up


async def start_sequence(hass: HomeAssistant, clock, when=T0) -> None:
    """Start the sequencer at `when`, which is where every clock is floored."""
    clock.move_to(when)
    hass.states.async_set("binary_sensor.rig_sequencer_running", "on")
    await hass.async_block_till_done()


async def test_a_quiet_rig_is_reported(hass: HomeAssistant, watching) -> None:
    """The positive control: without it every silence below proves nothing."""
    clock = await watching()
    await start_sequence(hass, clock)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert alert(hass) is not None


@pytest.mark.parametrize(("entity", "state"), [
    ("binary_sensor.rig_sequencer_running", "off"),
    ("binary_sensor.rig_scheduler_waiting", "on"),
    (SAFETY, "on"),
    ("sun.sun", "above_horizon"),
], ids=["sequencer stopped", "scheduler waiting", "conditions unsafe",
        "daylight"])
async def test_a_gate_suppresses_the_alert(
    hass: HomeAssistant, watching, entity: str, state: str
) -> None:
    """Each gate must silence a rig that would otherwise alert.

    A stopped sequencer is not a stall, a target-window wait is hours of
    nothing, a safety hold belongs to the abort blueprint, and a daytime wait
    for darkness is the twelve-hour case `night_only` exists for.

    These fail if the gates move back inside a `choose` branch, where a failing
    condition aborts the branch and the run alerts regardless.
    """
    clock = await watching()
    await start_sequence(hass, clock)
    hass.states.async_set(entity, state)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert alert(hass) is None


async def test_a_wait_that_just_ended_is_still_settling(
    hass: HomeAssistant, watching
) -> None:
    """Slew, rotation, filter change and settle follow a scheduler wait, and
    none of them produces a frame.
    """
    clock = await watching()
    await start_sequence(hass, clock)

    # End a wait a minute ago: the state is what it was, the clock is not.
    clock.move_to(T0 + STALLED - timedelta(minutes=1))
    hass.states.async_set("binary_sensor.rig_scheduler_waiting", "on")
    hass.states.async_set("binary_sensor.rig_scheduler_waiting", "off")

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert alert(hass) is None


async def test_a_solar_imager_can_alert_in_daylight(
    hass: HomeAssistant, watching
) -> None:
    """`night_only` is the one gate a user is expected to turn off."""
    clock = await watching(night_only=False)
    await start_sequence(hass, clock)
    hass.states.async_set("sun.sun", "above_horizon")

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert alert(hass) is not None


@pytest.mark.parametrize(("wired", "state", "alerts"), [
    ([], "on", True),
    ([SAFETY], "on", False),
    ([SAFETY], "unknown", True),
], ids=["no monitor to wire", "monitor says unsafe", "monitor dropped out"])
async def test_the_safety_gate(
    hass: HomeAssistant, watching, wired: list, state: str, alerts: bool
) -> None:
    """Empty means no gate — a rig with no safety monitor has no such entity,
    and the earlier `not` over a state condition made that vacuously-true
    condition into a permanently-false gate that muted the blueprint.

    Wired, it reads "not `on`", never "is `off`": a monitor that has dropped
    out reads `unknown`, and that is not evidence the silence is legitimate.
    """
    clock = await watching(safety_unsafe=wired)
    await start_sequence(hass, clock)
    hass.states.async_set(SAFETY, state)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert (alert(hass) is not None) is alerts


@pytest.mark.parametrize(("sequencer", "alerts"), [("on", True), ("off", False)],
                         ids=["sequencer running", "sequencer stopped"])
async def test_a_mount_that_parked_itself(
    hass: HomeAssistant, watching, sequencer: str, alerts: bool
) -> None:
    """A park under a running sequencer has already ended the night. A park
    after it stopped is how every night ends.
    """
    clock = await watching()
    await start_sequence(hass, clock)
    hass.states.async_set("binary_sensor.rig_sequencer_running", sequencer)

    hass.states.async_set("binary_sensor.rig_mount_at_park", "on")
    for _ in range(2000):
        await asyncio.sleep(0)
        if alert(hass):
            break

    assert (alert(hass) is not None) is alerts


async def test_a_just_started_sequence_is_silent(
    hass: HomeAssistant, watching
) -> None:
    """No clock may start before the sequencer does.

    `imaging` has been off all day and `last_frame_at` holds last night's
    frame, so both thresholds read "hours quiet" the instant a sequence starts
    — during cool-down, slew, plate-solve and the first autofocus, before a
    frame is physically possible.
    """
    start = T0 + timedelta(hours=1)
    clock = await watching()
    await start_sequence(hass, clock, start)

    clock.move_to(start + timedelta(minutes=QUIET_MINUTES - 1))
    await tick(hass, start + timedelta(minutes=QUIET_MINUTES - 1))

    assert alert(hass) is None


async def test_the_first_alert_of_a_night_does_not_claim_a_frame_age(
    hass: HomeAssistant, watching
) -> None:
    """`quiet_seconds` is floored at the sequencer's uptime, so on a rig that
    has not framed since last night the figure is uptime, not frame age.
    Reported as frame age it would have a reader believing the rig went quiet
    minutes ago rather than hours.
    """
    clock = await watching()
    await start_sequence(hass, clock)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert "since the sequence started" in alert(hass)["message"]


async def test_an_unreachable_rig_reports_only_what_it_knows(
    hass: HomeAssistant, watching
) -> None:
    """Every entity is unavailable, so the field list would be a row of the
    same word — and a park state nothing can read must not be reported at
    all.
    """
    clock = await watching()
    await start_sequence(hass, clock)
    clock.move_to(T0 + timedelta(minutes=10))
    for entity in RIG:
        hass.states.async_set(entity, "unavailable")
    await hass.async_block_till_done()

    clock.move_to(T0 + timedelta(minutes=13))
    await tick(hass, T0 + timedelta(minutes=13))

    message = alert(hass)["message"]
    assert "Nothing further can be read" in message
    assert "mount" not in message


async def test_a_missing_sun_does_not_mute_the_alarm(
    hass: HomeAssistant, watching
) -> None:
    """With `sun.sun` gone, "is below the horizon" would be false forever and
    `night_only` would silence the quiet arm without a word.
    """
    clock = await watching()
    hass.states.async_remove("sun.sun")
    await start_sequence(hass, clock)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert alert(hass) is not None


async def test_an_alert_with_no_notify_target_still_clears(
    hass: HomeAssistant, watching
) -> None:
    """With no target and no notify integration, calling `notify.send_message`
    raises ServiceNotFound, which ends the run and strands the notification.
    """
    clock = await watching(notify=False)
    await start_sequence(hass, clock)
    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)
    assert alert(hass) is not None

    hass.states.async_set("sensor.rig_last_frame_at", (T0 + STALLED).isoformat())
    await hass.async_block_till_done()

    assert alert(hass) is None


@pytest.mark.parametrize("escalations", [0, 1])
async def test_reminders_stop_at_the_configured_count(
    hass: HomeAssistant, watching, escalations: int
) -> None:
    """Zero is a valid count: an operator can ask for one alert and no more."""
    sent = async_mock_service(hass, "notify", "send_message")
    clock = await watching(notify=False, notify_target=["notify.phone"],
                           escalations=escalations)
    await start_sequence(hass, clock)
    now = T0 + STALLED
    clock.move_to(now)
    await tick(hass, now)

    for _ in range(3):
        now += timedelta(minutes=DEFAULTS["escalate_minutes"] + 1)
        clock.move_to(now)
        async_fire_time_changed(hass, now)
        for _ in range(200):
            await asyncio.sleep(0)

    reminders = [c for c in sent if "still stalled" in c.data["title"]]
    assert len(reminders) == escalations

"""The stall alert's gates and clocks, run rather than schema-checked.

`test_blueprints.py` proves Home Assistant ACCEPTS this blueprint, not that the
config does anything. A gate written inside a `choose` branch, where a failing
condition aborts only the branch and the parent sequence alerts anyway, or a
clock that starts before the sequence does, is valid YAML that alerts every
minute of every night. So these tests fire the triggers and read the
notification that comes out.

The inputs are this file's own, and every tuning input is left at its shipped
default, read from the blueprint itself. `test_blueprints.py`'s map pins
`night_only` off, so the default that mutes the twelve-hour daytime wait would
never run under it.
"""

import asyncio
from datetime import datetime, timedelta

from astral import LocationInfo, SunDirection
from astral.sun import time_at_elevation
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
T0 = datetime.fromisoformat("2026-09-17T01:00:00+00:00")


def _defaults() -> dict:
    """Every input's shipped default, flattened through the sections.

    Read from the blueprint rather than restated here: a threshold copied into
    a test stops matching the moment the default moves, and the test goes quiet
    instead of failing.
    """

    class Loader(yaml.SafeLoader):
        pass

    def construct(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> str:
        return loader.construct_scalar(node)

    Loader.add_constructor("!input", construct)
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
        await installed(BLUEPRINT, INPUTS | overrides)
        return freezer

    return _set_up


async def start_sequence(hass: HomeAssistant, clock, when=T0) -> None:
    """Start the sequencer at `when`, which is where every clock is floored."""
    clock.move_to(when)
    hass.states.async_set("binary_sensor.rig_sequencer_running", "on")
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("overrides", "entity", "state", "alerts"),
    [
        # The positive control: without it every silence below proves nothing.
        ({}, SAFETY, "off", True),
        # A stopped sequencer is not a stall.
        ({}, "binary_sensor.rig_sequencer_running", "off", False),
        # A target-window wait is hours of nothing.
        ({}, "binary_sensor.rig_scheduler_waiting", "on", False),
        # A safety hold belongs to the abort blueprint.
        ({}, SAFETY, "on", False),
        # A daytime wait for darkness is the twelve-hour case `night_only` is for.
        ({}, "sun.sun", "above_horizon", False),
        # `night_only` is the one gate a user is expected to turn off.
        ({"night_only": False}, "sun.sun", "above_horizon", True),
        # Empty means no gate: a rig with no safety monitor has no such entity,
        # and a `not` over a state condition with no entities is a
        # permanently-false gate that mutes the blueprint.
        ({"safety_unsafe": []}, SAFETY, "on", True),
        # Wired, the gate reads "not `on`", never "is `off`": a monitor that has
        # dropped out reads `unknown`, which is not evidence the silence is
        # legitimate.
        ({}, SAFETY, "unknown", True),
        # With `sun.sun` gone, "is below the horizon" would be false forever and
        # `night_only` would silence the quiet arm without a word.
        ({}, "sun.sun", None, True),
    ],
    ids=[
        "quiet rig",
        "sequencer stopped",
        "scheduler waiting",
        "conditions unsafe",
        "daylight",
        "solar imager",
        "no monitor to wire",
        "monitor dropped out",
        "no sun entity",
    ],
)
async def test_a_gate_decides_whether_a_quiet_rig_alerts(
    hass: HomeAssistant,
    watching,
    overrides: dict,
    entity: str,
    state: str | None,
    alerts: bool,
) -> None:
    """These fail if a gate sits inside a `choose` branch, where a failing
    condition aborts the branch and the run alerts regardless.
    """
    clock = await watching(**overrides)
    await start_sequence(hass, clock)
    if state is None:
        hass.states.async_remove(entity)
    else:
        hass.states.async_set(entity, state)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert (alert(hass) is not None) is alerts


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


@pytest.mark.parametrize(
    ("sequencer", "alerts"),
    [("on", True), ("off", False)],
    ids=["sequencer running", "sequencer stopped"],
)
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


async def test_a_just_started_sequence_is_silent(hass: HomeAssistant, watching) -> None:
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

    raised = alert(hass)
    assert raised is not None
    assert "since the sequence started" in raised["message"]


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

    raised = alert(hass)
    assert raised is not None
    message = raised["message"]
    assert "Nothing further can be read" in message
    assert "mount" not in message


async def test_a_rig_with_a_reachable_sensor_is_reported_through_it(
    hass: HomeAssistant, watching
) -> None:
    """From the first missed poll, while every other row still holds its last
    value inside the integration's outage grace.
    """
    reachable = "binary_sensor.rig_reachable"
    hass.states.async_set(reachable, "on")
    clock = await watching(rig_reachable=[reachable])
    await start_sequence(hass, clock)
    hass.states.async_set(reachable, "off")
    await hass.async_block_till_done()

    clock.move_to(T0 + timedelta(minutes=3))
    await tick(hass, T0 + timedelta(minutes=3))

    raised = alert(hass)
    assert raised is not None
    assert "cannot reach N.I.N.A." in raised["message"]


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
    clock = await watching(
        notify=False, notify_target=["notify.phone"], escalations=escalations
    )
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


def _local(offset_minutes: int) -> str:
    """The wall-clock time `offset_minutes` from T0, in the test's time zone."""
    moment = dt_util.as_local(T0) + timedelta(minutes=offset_minutes)
    return moment.strftime("%H:%M:%S")


async def go_down(hass: HomeAssistant, clock, when=T0) -> None:
    """Lose the rig at `when`: the sequencer's row goes unavailable."""
    clock.move_to(when)
    hass.states.async_set("binary_sensor.rig_sequencer_running", "unavailable")
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("mode", "window", "alerts"),
    [
        ("fixed", (-60, 60), False),
        ("fixed", (-60, -30), True),
        ("fixed", (-30, -60), False),
        ("fixed", (60, -60), True),
        ("fixed", (0, 0), True),
        ("off", (-60, 60), True),
    ],
    ids=["inside", "past", "wrapped-inside", "wrapped-outside", "empty", "off"],
)
async def test_quiet_hours_mute_an_unreachable_rig(
    hass: HomeAssistant, watching, mode, window, alerts
) -> None:
    """The unreachable arm has no other gate, and a rig switched off by day is
    unreachable on purpose.
    """
    start, end = window
    clock = await watching(
        mute_mode=mode, mute_from=_local(start), mute_until=_local(end)
    )
    await go_down(hass, clock)

    await tick(hass, T0 + timedelta(minutes=3))

    assert (alert(hass) is not None) is alerts


async def test_quiet_hours_mute_a_quiet_rig(hass: HomeAssistant, watching) -> None:
    """The window is a top-level condition, not a gate on one arm."""
    clock = await watching(
        mute_mode="fixed", mute_from=_local(-60), mute_until=_local(180)
    )
    await start_sequence(hass, clock)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert alert(hass) is None


async def test_a_rig_still_down_when_the_window_closes_is_reported(
    hass: HomeAssistant, watching
) -> None:
    """The unreachable trigger fires once, inside the window; a rig that never
    came back at dusk must still be reported that night.
    """
    clock = await watching(
        mute_mode="fixed", mute_from=_local(-60), mute_until=_local(5)
    )
    await go_down(hass, clock)
    await tick(hass, T0 + timedelta(minutes=3))
    assert alert(hass) is None

    clock.move_to(T0 + timedelta(minutes=6))
    await tick(hass, T0 + timedelta(minutes=6))

    assert alert(hass) is not None


SITES = {
    "san-diego": (32.87, -117.22),
    "sydney": (-33.87, 151.21),
    "frankfurt": (50.11, 8.68),
}


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize(
    ("altitude", "direction", "after", "alerts"),
    [
        (-12, SunDirection.RISING, -5, True),
        (-12, SunDirection.RISING, 5, False),
        (3, SunDirection.SETTING, -5, False),
        (3, SunDirection.SETTING, 5, True),
    ],
    ids=["before-dawn", "after-dawn", "before-dusk", "after-dusk"],
)
async def test_sun_quiet_hours_follow_the_suns_altitude(
    hass: HomeAssistant, watching, site, altitude, direction, after, alerts
) -> None:
    """Checked against astral's crossing times: a wrong term in the
    hand-rolled solar position moves an edge by several minutes.
    """
    hass.config.latitude, hass.config.longitude = SITES[site]
    assert await async_setup_component(hass, "zone", {})
    observer = LocationInfo(latitude=SITES[site][0], longitude=SITES[site][1]).observer
    crossing = time_at_elevation(observer, altitude, T0.date(), direction)
    fires = crossing + timedelta(minutes=after)
    clock = await watching(
        mute_mode="sun", mute_morning_altitude=-12, mute_evening_altitude=3
    )
    await go_down(hass, clock, fires - timedelta(minutes=3))

    await tick(hass, fires)

    assert (alert(hass) is not None) is alerts


async def test_sun_quiet_hours_without_a_location_mute_nothing(
    hass: HomeAssistant, watching
) -> None:
    """At noon, which a known location would mute."""
    noon = T0 - timedelta(hours=6)
    clock = await watching(mute_mode="sun")
    await go_down(hass, clock, noon - timedelta(minutes=3))

    await tick(hass, noon)

    assert alert(hass) is not None


# How long the sequence runs before the gate under test lets the rig work.
LET_WORK = timedelta(hours=1)


@pytest.mark.parametrize(
    ("mute_mode", "reopened", "named"),
    [
        ("off", (SAFETY, "on", "off"), "conditions turned safe"),
        ("off", ("sun.sun", "above_horizon", "below_horizon"), "the sun set"),
        ("fixed", None, "the quiet hours ended"),
    ],
    ids=["conditions turned safe", "the sun set", "the quiet hours ended"],
)
@pytest.mark.parametrize(("after", "alerts"), [(-1, False), (1, True)])
async def test_the_quiet_clock_starts_when_the_last_gate_opens(
    hass: HomeAssistant, watching, mute_mode, reopened, named, after, alerts
) -> None:
    """A gate mutes only while it is shut. A clock running from the sequence's
    start would alert on the first tick after it opens, before the rig has had
    a chance to cool, focus and take a frame.
    """
    window_ends = LET_WORK // timedelta(minutes=1)
    clock = await watching(
        mute_mode=mute_mode, mute_from=_local(-60), mute_until=_local(window_ends)
    )
    await start_sequence(hass, clock)
    clock.move_to(T0 + LET_WORK)
    if reopened:
        entity, shut, opened = reopened
        hass.states.async_set(entity, shut)
        hass.states.async_set(entity, opened)
    when = T0 + LET_WORK + timedelta(minutes=QUIET_MINUTES + after)

    clock.move_to(when)
    await tick(hass, when)

    raised = alert(hass)
    assert (raised is not None) is alerts
    if raised:
        assert f"since {named}" in raised["message"]


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize(("after", "alerts"), [(-2, False), (2, True)])
async def test_the_quiet_clock_starts_when_the_sun_quiet_hours_end(
    hass: HomeAssistant, watching, site, after, alerts
) -> None:
    """Checked against astral's crossing, as the window's own edges are. With
    no safety monitor and `night_only` off, no other gate opens near it.
    """
    hass.config.latitude, hass.config.longitude = SITES[site]
    assert await async_setup_component(hass, "zone", {})
    observer = LocationInfo(latitude=SITES[site][0], longitude=SITES[site][1]).observer
    dusk = time_at_elevation(observer, 3, T0.date(), SunDirection.SETTING)
    clock = await watching(
        mute_mode="sun", mute_evening_altitude=3, night_only=False, safety_unsafe=[]
    )
    await start_sequence(hass, clock, dusk - LET_WORK)
    when = dusk + timedelta(minutes=QUIET_MINUTES + after)

    clock.move_to(when)
    await tick(hass, when)

    assert (alert(hass) is not None) is alerts


@pytest.mark.parametrize(
    ("raised_at", "reported"),
    [(T0 - timedelta(days=6), False), (T0 + timedelta(minutes=5), True)],
    ids=["another night's", "tonight's"],
)
async def test_the_alert_names_only_tonights_error(
    hass: HomeAssistant, watching, raised_at, reported
) -> None:
    """The error event holds its last value however old, and a week-old
    plate-solve failure in a 3am alert reads as tonight's.
    """
    error = "event.rig_error"
    clock = await watching(error_event=[error])
    await start_sequence(hass, clock)
    hass.states.async_set(
        error, raised_at.isoformat(), {"event_type": "platesolve_failed"}
    )

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    raised = alert(hass)
    assert raised is not None
    assert ("platesolve_failed" in raised["message"]) is reported


# At T0, local noon at the rig and local midnight at Home Assistant: the two
# gates can only agree with the rig if they read its site.
RIG_AT_NOON = (-10.0, 165.0)
HOME_AT_MIDNIGHT = (30.0, -15.0)
SITE = {
    "site_latitude": ["sensor.rig_site_latitude"],
    "site_longitude": ["sensor.rig_site_longitude"],
}


async def place(hass: HomeAssistant, rig_site) -> None:
    """Put Home Assistant at midnight and the rig's site sensors at `rig_site`."""
    hass.config.latitude, hass.config.longitude = HOME_AT_MIDNIGHT
    assert await async_setup_component(hass, "zone", {})
    for entity, reading in zip(SITE.values(), rig_site, strict=True):
        hass.states.async_set(entity[0], str(reading))


@pytest.mark.parametrize(
    ("rig_site", "alerts"),
    [(RIG_AT_NOON, False), (("unknown", "unknown"), True)],
    ids=["site-reported", "site-unknown"],
)
async def test_sun_quiet_hours_place_the_sun_at_the_rig(
    hass: HomeAssistant, watching, rig_site, alerts
) -> None:
    """A site N.I.N.A. has not reported falls back to Home Assistant's."""
    await place(hass, rig_site)
    clock = await watching(mute_mode="sun", **SITE)
    await go_down(hass, clock)

    await tick(hass, T0 + timedelta(minutes=3))

    assert (alert(hass) is not None) is alerts


@pytest.mark.parametrize(
    ("inputs", "alerts"), [(SITE, False), ({}, True)], ids=["wired", "unwired"]
)
async def test_night_only_reads_the_sun_at_the_rig(
    hass: HomeAssistant, watching, inputs, alerts
) -> None:
    """`sun.sun` says night throughout; only the rig's own sky says day."""
    await place(hass, RIG_AT_NOON)
    clock = await watching(**inputs)
    await start_sequence(hass, clock)

    clock.move_to(T0 + STALLED)
    await tick(hass, T0 + STALLED)

    assert (alert(hass) is not None) is alerts


@pytest.mark.parametrize("site", SITES)
@pytest.mark.parametrize(("after", "alerts"), [(-5, False), (5, True)])
async def test_the_quiet_clock_starts_at_sunset_at_the_rig(
    hass: HomeAssistant, watching, site, after, alerts
) -> None:
    """Checked against astral's sunset there. `sun.sun` reads night throughout,
    so a clock started by it would alert as soon as the rig's own sun set.
    """
    await place(hass, SITES[site])
    observer = LocationInfo(latitude=SITES[site][0], longitude=SITES[site][1]).observer
    sunset = time_at_elevation(observer, -0.833, T0.date(), SunDirection.SETTING)
    clock = await watching(safety_unsafe=[], **SITE)
    await start_sequence(hass, clock, sunset - LET_WORK)
    when = sunset + timedelta(minutes=QUIET_MINUTES + after)

    clock.move_to(when)
    await tick(hass, when)

    assert (alert(hass) is not None) is alerts

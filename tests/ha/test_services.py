"""The services, ported onto the v2 client.

Same behaviour, new client (phase D redesigns and trims them). What is pinned
here is the four call sites where the two clients' signatures differ, because
each of those is a silent no-op if it is got wrong: N.I.N.A. answers
`Success: true` to a parameter it did not recognise, and the state changes
seconds later, so nothing at the call site can tell.
"""
import pytest
import voluptuous as vol
from helpers import failure
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.nina_astrophotography.const import DOMAIN


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


@pytest.mark.parametrize(
    ("service", "data", "path", "params"),
    [
        # The service takes RA in HOURS — every RA N.I.N.A. hands out is in
        # hours — and the endpoint reads degrees. Sending hours straight
        # through is a 15× error the mount happily slews on.
        ("mount_slew", {"ra": 22.071111, "dec": 56.6}, "/equipment/mount/slew",
         {"ra": 331.066665, "dec": 56.6}),
        # A boolean over an enum: `Stopped` is one of the mount's own modes.
        ("mount_set_tracking", {"enabled": True}, "/equipment/mount/tracking",
         {"mode": 0}),
        ("mount_set_tracking", {"enabled": False}, "/equipment/mount/tracking",
         {"mode": 4}),
        # `sequenceName`, not `path` — and it is a NAME. 1.4.5 sent `path`, so
        # the sequence never loaded.
        ("sequence_load", {"path": "Autumn"}, "/sequence/load",
         {"sequenceName": "Autumn"}),
        # `duration`, not `time`. 1.4.5 sent `time`, so the exposure length was
        # ignored and the API defaulted it.
        ("camera_capture", {"exposure": 30}, "/equipment/camera/capture",
         {"duration": 30.0, "save": "false"}),
    ],
    ids=["slew-hours-to-degrees", "tracking-on", "tracking-off",
         "sequence-name", "capture-duration"],
)
async def test_a_ported_service_sends_what_the_api_reads(
    hass: HomeAssistant, loaded_entry, rig,
    service: str, data: dict, path: str, params: dict,
) -> None:
    await _call(hass, service, **data)
    assert rig.sent[-1] == (path, params)


async def test_capture_still_accepts_the_parameters_that_bind_nothing(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """`filter_index` and `binning` bound nothing on the old client either —
    `/equipment/camera/capture` takes neither — so they are accepted and not
    sent rather than rejected. Phase D removes them from the schema."""
    await _call(hass, "camera_capture", exposure=5, binning=2, filter_index=3)
    assert rig.sent[-1] == ("/equipment/camera/capture",
                            {"duration": 5.0, "save": "false"})


async def test_a_refused_command_reads_as_a_refusal_not_an_integration_bug(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """`NinaError` subclasses `Exception` alone, deliberately — the API layer
    stays free of Home Assistant. One escaping a handler is treated as a defect
    in this integration: the step fails with a traceback and the frontend
    offers to file a bug. A disconnected mount is not that."""
    rig.respond("/equipment/mount/park", failure("Mount not connected"))
    with pytest.raises(HomeAssistantError) as raised:
        await _call(hass, "mount_park")
    assert "Mount not connected" in str(raised.value)


@pytest.mark.parametrize(
    ("service", "path"),
    [
        ("camera_cool", "/equipment/camera/cool"),
        ("camera_warm", "/equipment/camera/warm"),
        ("camera_abort_capture", "/equipment/camera/abort-exposure"),
        ("mount_unpark", "/equipment/mount/unpark"),
        ("focuser_auto_focus", "/equipment/focuser/auto-focus"),
        ("guider_start", "/equipment/guider/start"),
        ("guider_stop", "/equipment/guider/stop"),
        ("dome_open", "/equipment/dome/open"),
        ("dome_close", "/equipment/dome/close"),
        ("dome_park", "/equipment/dome/park"),
        ("sequence_start", "/sequence/start"),
        ("sequence_stop", "/sequence/stop"),
    ],
    ids=lambda value: value if value.startswith("/") is False else None,
)
async def test_every_remaining_service_reaches_its_own_endpoint(
    hass: HomeAssistant, loaded_entry, rig, service: str, path: str
) -> None:
    """The rest of the ported handlers, which differ only in the endpoint they
    send. `dome_close` is the roof: two shipped blueprints call it, and a
    handler pointed at the wrong path is answered `Success: true`."""
    data = {"temperature": -10} if service == "camera_cool" else {}
    await _call(hass, service, **data)
    assert rig.sent[-1][0] == path


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("mount_slew", {"ra": 30, "dec": 0}),
        ("mount_slew", {"ra": -1, "dec": 0}),
        ("mount_slew", {"ra": 0, "dec": 91}),
        ("focuser_move", {"position": -1}),
        ("filterwheel_change_filter", {"filter_index": -1}),
    ],
    ids=["ra-above-24", "ra-negative", "dec-above-90", "position", "filter"],
)
async def test_out_of_range_input_is_refused_rather_than_clamped(
    hass: HomeAssistant, loaded_entry, rig, service: str, data: dict
) -> None:
    """`services.yaml`'s selectors are a UI hint and bind nothing from a script
    or the REST API. Out-of-range input is silently clamped and answered
    `Success: true`, so nothing downstream would report it — `ra: 30` is 450°,
    and the mount slews somewhere real."""
    with pytest.raises(vol.Invalid):
        await _call(hass, service, **data)
    assert rig.sent == []

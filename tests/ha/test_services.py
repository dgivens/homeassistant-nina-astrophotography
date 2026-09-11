"""The services, ported onto the v2 client.

Same behaviour, new client (phase D redesigns and trims them). What is pinned
here is the four call sites where the two clients' signatures differ, because
each of those is a silent no-op if it is got wrong: N.I.N.A. answers
`Success: true` to a parameter it did not recognise, and the state changes
seconds later, so nothing at the call site can tell.
"""
import pytest
from homeassistant.core import HomeAssistant

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

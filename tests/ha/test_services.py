"""The services: device targeting, and the three redesigns.

What is pinned here is device targeting and the call sites where the service's
field name and the API's parameter name differ, because each of those is a
silent no-op if it is got wrong: N.I.N.A. answers `Success: true` to a
parameter it did not recognise, and the state changes seconds later, so nothing
at the call site can tell.
"""
from pathlib import Path

import pytest
import yaml
from helpers import failure
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import selector

from custom_components.nina_astrophotography.const import DOMAIN

SERVICES_YAML = yaml.safe_load(
    (Path(__file__).resolve().parents[2] / "custom_components"
     / "nina_astrophotography" / "services.yaml").read_text(encoding="utf-8")
)


async def _call(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True)


def _hub(hass: HomeAssistant, entry) -> str:
    """The device id of an entry's hub, as a target picker would yield it."""
    return dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, entry.entry_id), entry.entry_id
    ).id


async def test_a_service_reaches_the_rig_its_device_belongs_to(
    hass: HomeAssistant, two_rigs
) -> None:
    """1.4.5 returned the first loaded entry, so a second rig was unreachable
    from the services however it was targeted."""
    first, second = two_rigs.rigs
    await _call(hass, "mount_park", device_id=_hub(hass, two_rigs.entries[1]))

    assert second.sent[-1][0] == "/equipment/mount/park"
    assert "/equipment/mount/park" not in [path for path, _ in first.sent]


async def test_an_untargeted_call_is_refused_when_two_rigs_are_configured(
    hass: HomeAssistant, two_rigs
) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "mount_park")


async def test_a_device_belonging_to_no_nina_instance_is_refused(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "mount_park", device_id="not-a-device")
    assert rig.sent == []


@pytest.mark.parametrize(
    ("service", "data", "path", "params"),
    [
        # J2000 DEGREES, sent through untouched: all three N.I.N.A. branches
        # build Epoch.J2000 and transform to the mount's own system internally.
        ("mount_slew", {"ra_degrees": 331.07, "dec_degrees": 56.6},
         "/equipment/mount/slew", {"ra": 331.07, "dec": 56.6}),
        # A boolean over an enum: `Stopped` is one of the mount's own modes.
        ("mount_set_tracking", {"enabled": True}, "/equipment/mount/tracking",
         {"mode": 0}),
        ("mount_set_tracking", {"enabled": False}, "/equipment/mount/tracking",
         {"mode": 4}),
        # `sequenceName`, and it is the name N.I.N.A. lists, not a path.
        ("sequence_load", {"sequence_name": "Autumn"}, "/sequence/load",
         {"sequenceName": "Autumn"}),
        # `duration`, not `time`. 1.4.5 sent `time`, so the exposure length was
        # ignored and the API defaulted it.
        ("camera_capture", {"duration": 30}, "/equipment/camera/capture",
         {"duration": 30.0, "save": "false"}),
    ],
    ids=["slew-j2000-degrees", "tracking-on", "tracking-off",
         "sequence-name", "capture-duration"],
)
async def test_a_service_sends_what_the_api_reads(
    hass: HomeAssistant, loaded_entry, rig,
    service: str, data: dict, path: str, params: dict,
) -> None:
    await _call(hass, service, **data)
    assert rig.sent[-1] == (path, params)


def test_capture_no_longer_offers_the_parameters_that_bind_nothing() -> None:
    """`binning` and `filter_index` bind nothing on the wire —
    `/equipment/camera/capture` takes neither — and a parameter that looks like
    it works is worse than no parameter."""
    assert set(SERVICES_YAML["camera_capture"]["fields"]) - {"device_id"} == {
        "duration", "gain", "save"}


@pytest.mark.parametrize("service", sorted(SERVICES_YAML), ids=str)
def test_every_documented_selector_is_one_home_assistant_accepts(
    service: str,
) -> None:
    """`services.yaml` is validated by hassfest, in CI, after the push. This
    is the same check in the suite, where it costs seconds instead."""
    for field, spec in SERVICES_YAML[service]["fields"].items():
        if "selector" in spec:
            selector(spec["selector"])


@pytest.mark.parametrize("service", sorted(SERVICES_YAML), ids=str)
def test_every_action_offers_a_rig_picker(service: str) -> None:
    """A `device:` SELECTOR on a field, not a `target:` block: Home Assistant
    rejects a device filter on `target`, and without the filter the picker
    offers every device in the house."""
    picker = SERVICES_YAML[service]["fields"]["device_id"]["selector"]

    assert picker == {"device": {"integration": DOMAIN}}


@pytest.mark.parametrize("service", sorted(SERVICES_YAML), ids=str)
async def test_the_documented_fields_are_the_fields_the_schema_binds(
    hass: HomeAssistant, loaded_entry, service: str
) -> None:
    """A field documented but not bound does nothing; a field bound but not
    documented is invisible. Both were shipped in 1.4.5."""
    schema = hass.services.async_services()[DOMAIN][service].schema
    # `device_id` is documented as a field but bound as a target field the
    # schema accepts wholesale, so it is excluded from both sides.
    documented = set(SERVICES_YAML[service]["fields"]) - {"device_id"}
    bound = {str(key) for key in schema.schema} - {"device_id"}

    assert bound == documented


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
    ("service", "data"),
    [
        ("mount_slew", {"ra_degrees": 361, "dec_degrees": 0}),
        ("mount_slew", {"ra_degrees": -1, "dec_degrees": 0}),
        ("mount_slew", {"ra_degrees": 0, "dec_degrees": 91}),
        ("mount_slew", {"ra_degrees": 0, "dec_degrees": -91}),
        ("focuser_move", {"position": -1}),
        ("filterwheel_change_filter", {"filter_index": -1}),
    ],
    ids=["ra-above-360", "ra-negative", "dec-above-90", "dec-below-90",
         "position", "filter"],
)
async def test_out_of_range_input_is_refused_rather_than_clamped(
    hass: HomeAssistant, loaded_entry, rig, service: str, data: dict
) -> None:
    """Out-of-range input is silently clamped and answered `Success: true`, so
    nothing downstream would report it — and `services.yaml`'s selectors are a
    UI hint that binds nothing from a script or the REST API."""
    with pytest.raises(ServiceValidationError):
        await _call(hass, service, **data)
    assert rig.sent == []


@pytest.mark.parametrize(
    ("service", "path"),
    [
        ("camera_cool", "/equipment/camera/cool"),
        ("camera_warm", "/equipment/camera/warm"),
        ("camera_abort_capture", "/equipment/camera/abort-exposure"),
        ("mount_park", "/equipment/mount/park"),
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
    ids=lambda value: None if value.startswith("/") else value,
)
async def test_every_remaining_service_reaches_its_own_endpoint(
    hass: HomeAssistant, loaded_entry, rig, service: str, path: str
) -> None:
    """The handlers that differ only in the endpoint they send. `dome_close` is
    the roof: the abort blueprint calls it, and a handler pointed at the wrong
    path is answered `Success: true`."""
    data = {"temperature": -10} if service == "camera_cool" else {}
    await _call(hass, service, **data)
    assert rig.sent[-1][0] == path


async def test_the_actions_exist_before_any_entry_is_loaded(
    hass: HomeAssistant,
) -> None:
    """Bronze `action-setup`. Registered from `async_setup_entry`, the actions
    vanish with the last entry, and an automation referencing one fails
    validation rather than failing legibly at call time."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "mount_park")

"""The actions: device targeting, and what each one sends.

What is pinned here is device targeting and the call sites where the service's
field name and the API's parameter name differ, because each of those is a
silent no-op if it is got wrong: N.I.N.A. answers `Success: true` to a
parameter it did not recognise, and the state changes seconds later, so nothing
at the call site can tell.
"""

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.selector import selector
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol
import yaml

import custom_components.nina_astrophotography as integration
from custom_components.nina_astrophotography.const import DOMAIN
from ha.registry import get_device
from helpers import failure

SERVICES_YAML = yaml.safe_load(
    (Path(integration.__file__).parent / "services.yaml").read_text(encoding="utf-8")
)


# What a target picker can yield, none of which is a documented field.
_TARGET_FIELDS = {"area_id", "device_id", "entity_id", "floor_id", "label_id"}


async def _call(
    hass: HomeAssistant, service: str, target: dict | None = None, **data
) -> None:
    await hass.services.async_call(DOMAIN, service, data, blocking=True, target=target)


def _hub(hass: HomeAssistant, entry) -> str:
    """The device id of an entry's hub, as a target picker would yield it."""
    return get_device(hass, entry).id


def _in_an_area(hass: HomeAssistant, entry) -> str:
    """An area holding the entry's hub, as an area picker would yield it."""
    area = ar.async_get(hass).async_get_or_create("Pier")
    dr.async_get(hass).async_update_device(_hub(hass, entry), area_id=area.id)
    return area.id


@pytest.mark.parametrize(
    ("in_target", "target"),
    [
        # How automations written against the `device_id` field, and the
        # blueprints, send it.
        (False, lambda hass, entry: {"device_id": _hub(hass, entry)}),
        (True, lambda hass, entry: {"device_id": _hub(hass, entry)}),
        (
            True,
            lambda hass, entry: {
                "entity_id": er.async_entries_for_config_entry(
                    er.async_get(hass), entry.entry_id
                )[0].entity_id
            },
        ),
        (True, lambda hass, entry: {"area_id": _in_an_area(hass, entry)}),
    ],
    ids=["device-in-data", "device", "entity", "area"],
)
async def test_a_service_reaches_the_rig_its_target_belongs_to(
    hass: HomeAssistant, two_rigs, in_target: bool, target
) -> None:
    """The targeted device, not the first loaded entry, picks the rig, so a
    second rig is reachable.
    """
    first, second = two_rigs.rigs
    chosen = target(hass, two_rigs.entries[1])
    if in_target:
        await _call(hass, "mount_park", target=chosen)
    else:
        await _call(hass, "mount_park", **chosen)

    assert second.sent[-1][0] == "/equipment/mount/park"
    assert "/equipment/mount/park" not in [path for path, _ in first.sent]


async def test_an_untargeted_call_reaches_the_only_rig(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    await _call(hass, "mount_park")
    assert rig.sent[-1][0] == "/equipment/mount/park"


async def test_an_untargeted_call_is_refused_when_two_rigs_are_configured(
    hass: HomeAssistant, two_rigs
) -> None:
    with pytest.raises(ServiceValidationError):
        await _call(hass, "mount_park")


async def test_a_target_that_names_no_nina_instance_is_refused(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """Never widened to "the only rig": a device of some other
    integration must not park this mount, and neither must a typo.
    """
    other = MockConfigEntry(domain="other")
    other.add_to_hass(hass)
    foreign = dr.async_get(hass).async_get_or_create(
        config_entry_id=other.entry_id, identifiers={("other", "thing")}
    )

    for target in ("not-a-device", foreign.id):
        with pytest.raises(ServiceValidationError):
            await _call(hass, "mount_park", device_id=target)
    assert rig.sent == []


async def test_an_untargeted_call_is_refused_while_a_second_rig_is_merely_down(
    hass: HomeAssistant, two_rigs
) -> None:
    """Ambiguity is judged on CONFIGURED entries. Judged on loaded ones, an
    untargeted call would silently retarget to the surviving rig whenever the
    other rig's N.I.N.A. was down — which is when nobody is watching.
    """
    assert await hass.config_entries.async_unload(two_rigs.entries[0].entry_id)

    with pytest.raises(ServiceValidationError):
        await _call(hass, "mount_park")
    assert two_rigs.rigs[1].sent == []


@pytest.mark.parametrize(
    ("service", "data", "path", "params"),
    [
        # J2000 DEGREES, sent through untouched: all three N.I.N.A. branches
        # build Epoch.J2000 and transform to the mount's own system internally.
        (
            "mount_slew",
            {"ra_degrees": 331.07, "dec_degrees": 56.6},
            "/equipment/mount/slew",
            {"ra": 331.07, "dec": 56.6},
        ),
        # A boolean over an enum: `Stopped` is one of the mount's own modes.
        (
            "mount_set_tracking",
            {"enabled": True},
            "/equipment/mount/tracking",
            {"mode": 0},
        ),
        (
            "mount_set_tracking",
            {"enabled": False},
            "/equipment/mount/tracking",
            {"mode": 4},
        ),
        # `sequenceName`, and it is the name N.I.N.A. lists, not a path.
        (
            "sequence_load",
            {"sequence_name": "Autumn"},
            "/sequence/load",
            {"sequenceName": "Autumn"},
        ),
        # `duration`, not `time`: the API ignores `time` and defaults the
        # exposure length.
        (
            "camera_capture",
            {"duration": 30},
            "/equipment/camera/capture",
            {"duration": 30.0, "save": "false"},
        ),
        # Two angles on two endpoints, both taking `position`: crossed, the
        # rotator turns to the wrong angle and still answers `Success: true`.
        (
            "rotator_move",
            {"position": 90},
            "/equipment/rotator/move",
            {"position": 90.0},
        ),
        (
            "rotator_move_mechanical",
            {"position": 90},
            "/equipment/rotator/move-mechanical",
            {"position": 90.0},
        ),
        # set-cover's parameter is `closed`, so opening sends false.
        (
            "flat_panel_set_cover",
            {"open": True},
            "/equipment/flatdevice/set-cover",
            {"closed": "false"},
        ),
        (
            "flat_panel_set_cover",
            {"open": False},
            "/equipment/flatdevice/set-cover",
            {"closed": "true"},
        ),
        (
            "flat_panel_set_light",
            {"light_on": False},
            "/equipment/flatdevice/set-light",
            {"on": "false"},
        ),
        # `brightness`, in the panel's own units.
        (
            "flat_panel_set_brightness",
            {"level": 1024},
            "/equipment/flatdevice/set-brightness",
            {"brightness": 1024},
        ),
    ],
    ids=[
        "slew-j2000-degrees",
        "tracking-on",
        "tracking-off",
        "sequence-name",
        "capture-duration",
        "rotator-sky-angle",
        "rotator-mechanical-angle",
        "cover-open",
        "cover-close",
        "light-off",
        "brightness-level",
    ],
)
async def test_a_service_sends_what_the_api_reads(
    hass: HomeAssistant,
    loaded_entry,
    rig,
    service: str,
    data: dict,
    path: str,
    params: dict,
) -> None:
    await _call(hass, service, **data)
    assert rig.sent[-1] == (path, params)


def test_capture_offers_only_the_parameters_the_api_binds() -> None:
    """`/equipment/camera/capture` binds no binning and no filter index, and a
    parameter that looks like it works is worse than no parameter.
    """
    assert {"binning", "filter_index"}.isdisjoint(
        SERVICES_YAML["camera_capture"]["fields"]
    )


@pytest.mark.parametrize("service", sorted(SERVICES_YAML), ids=str)
def test_every_documented_selector_is_one_home_assistant_accepts(
    service: str,
) -> None:
    """`services.yaml` is validated by hassfest, in CI, after the push. This
    is the same check in the suite, where it costs seconds instead.
    """
    for spec in SERVICES_YAML[service].get("fields", {}).values():
        if "selector" in spec:
            selector(spec["selector"])


@pytest.mark.parametrize("service", sorted(SERVICES_YAML), ids=str)
def test_every_action_targets_only_this_integration(service: str) -> None:
    """Filtered on entities, since hassfest refuses a device filter on
    `target:`; unfiltered, the picker offers every device in the house.
    """
    target = SERVICES_YAML[service]["target"]

    assert target == {"entity": {"integration": DOMAIN}}
    selector({"target": target})


@pytest.mark.parametrize("service", sorted(SERVICES_YAML), ids=str)
async def test_the_documented_fields_are_the_fields_the_schema_binds(
    hass: HomeAssistant, service: str
) -> None:
    """A field documented but not bound does nothing; a field bound but not
    documented is invisible.

    No entry: the actions register in `async_setup`, so the schema cannot
    depend on one being loaded.
    """
    assert await async_setup_component(hass, DOMAIN, {})
    schema = hass.services.async_services()[DOMAIN][service].schema
    assert isinstance(schema, vol.Schema)
    # The target fields are bound wholesale and documented by `target:`.
    documented = set(SERVICES_YAML[service].get("fields", {}))
    bound = {str(key) for key in schema.schema} - _TARGET_FIELDS

    assert bound == documented


async def test_a_refused_command_reads_as_a_refusal_not_an_integration_bug(
    hass: HomeAssistant, loaded_entry, rig
) -> None:
    """`NinaError` subclasses `Exception` alone, deliberately — the API layer
    stays free of Home Assistant. One escaping a handler is treated as a defect
    in this integration: the step fails with a traceback and the frontend
    offers to file a bug. A disconnected mount is not that.
    """
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
        ("camera_cool", {"temperature": 51}),
        ("camera_cool", {"temperature": -51}),
        ("camera_cool", {"temperature": -10, "minutes": -1}),
        ("camera_warm", {"minutes": -1}),
        ("camera_capture", {"duration": -1}),
        # The API applies only a gain above 0.
        ("camera_capture", {"duration": 30, "gain": 0}),
        # The rig's camera reports GainMax 700 and ExposureMax 2000.
        ("camera_capture", {"duration": 30, "gain": 701}),
        ("camera_capture", {"duration": 2000.5}),
        # The rig's wheel reports slots 0 to 6.
        ("filterwheel_change_filter", {"filter_index": 7}),
        ("filterwheel_change_filter", {"filter_index": -1}),
        ("rotator_move", {"position": 360.5}),
        ("rotator_move", {"position": -1}),
        ("rotator_move_mechanical", {"position": 360.5}),
        ("rotator_move_mechanical", {"position": -1}),
        # The rig's panel reports MaxBrightness 4096.
        ("flat_panel_set_brightness", {"level": 4097}),
        ("flat_panel_set_brightness", {"level": -1}),
        ("flat_panel_set_light", {"light_on": True, "brightness": 4097}),
        # The panel's minimum: an ASCOM panel at 0 is dark, and N.I.N.A. then
        # lights it at MaxBrightness.
        ("flat_panel_set_light", {"light_on": True, "brightness": 0}),
    ],
    ids=[
        "ra-above-360",
        "ra-negative",
        "dec-above-90",
        "dec-below-90",
        "position-negative",
        "temperature-above-50",
        "temperature-below-50",
        "cool-ramp-negative",
        "warm-ramp-negative",
        "duration-negative",
        "gain-zero",
        "gain-above-the-cameras",
        "duration-above-the-cameras",
        "filter-the-wheel-lacks",
        "filter-negative",
        "rotator-above-360",
        "rotator-negative",
        "mechanical-above-360",
        "mechanical-negative",
        "level-above-the-panels",
        "level-negative",
        "light-brightness-above-the-panels",
        "light-brightness-at-the-panels-minimum",
    ],
)
async def test_out_of_range_input_is_refused_rather_than_clamped(
    hass: HomeAssistant, loaded_entry, rig, service: str, data: dict
) -> None:
    """Out-of-range input is silently clamped and answered `Success: true`, so
    nothing downstream would report it — and `services.yaml`'s selectors are a
    UI hint that binds nothing from a script or the REST API.
    """
    with pytest.raises(ServiceValidationError):
        await _call(hass, service, **data)
    assert rig.sent == []


@pytest.mark.parametrize(
    ("service", "data", "path"),
    [
        ("focuser_move", {"position": 0}, "/equipment/focuser/move"),
        # Past any one focuser's travel: no `MaxStep` reaches the wire.
        ("focuser_move", {"position": 1_000_000}, "/equipment/focuser/move"),
        ("camera_cool", {"temperature": -50, "minutes": 0}, "/equipment/camera/cool"),
        ("camera_cool", {"temperature": 50, "minutes": 90.5}, "/equipment/camera/cool"),
        ("camera_warm", {"minutes": 0}, "/equipment/camera/warm"),
        # A bias frame, below the camera's ExposureMin.
        ("camera_capture", {"duration": 0, "gain": 1}, "/equipment/camera/capture"),
        (
            "camera_capture",
            {"duration": 2000, "gain": 700},
            "/equipment/camera/capture",
        ),
        (
            "filterwheel_change_filter",
            {"filter_index": 6},
            "/equipment/filterwheel/change-filter",
        ),
        ("rotator_move", {"position": 0}, "/equipment/rotator/move"),
        (
            "rotator_move_mechanical",
            {"position": 360},
            "/equipment/rotator/move-mechanical",
        ),
        (
            "flat_panel_set_brightness",
            {"level": 4096},
            "/equipment/flatdevice/set-brightness",
        ),
    ],
    ids=[
        "position-zero",
        "position-past-any-cap",
        "cool-coldest-at-once",
        "cool-warmest-slowly",
        "warm-at-once",
        "capture-bias",
        "capture-at-the-cameras-maximum",
        "filter-last-slot",
        "rotator-zero",
        "mechanical-360",
        "level-at-the-panels-maximum",
    ],
)
async def test_a_value_at_its_limit_is_sent(
    hass: HomeAssistant, loaded_entry, rig, service: str, data: dict, path: str
) -> None:
    await _call(hass, service, **data)
    assert rig.sent[-1][0] == path


def _serve_with(rig, device: str, block: dict | None) -> None:
    """Serve the current state with one `/equipment/info` device block
    replaced, or left out when `block` is None.
    """
    envelope = rig.states[rig.state_name]["/equipment/info"]
    response = dict(envelope["Response"])
    if block is None:
        del response[device]
    else:
        response[device] = {**response[device], **block}
    rig.respond("/equipment/info", {**envelope, "Response": response})


@pytest.mark.parametrize(
    ("state", "device", "block", "service", "data"),
    [
        pytest.param(
            "partial_equipment_connection",
            None,
            None,
            "filterwheel_change_filter",
            {"filter_index": 9},
            id="wheel-disconnected",
        ),
        pytest.param(
            "equipment_disconnected",
            None,
            None,
            "camera_capture",
            {"duration": 5000, "gain": 5000},
            id="camera-disconnected",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            "imaging",
            "Camera",
            None,
            "camera_capture",
            {"duration": 5000, "gain": 5000},
            id="camera-absent",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            "imaging",
            "Camera",
            {"GainMin": 0, "GainMax": 0, "ExposureMin": 0, "ExposureMax": 0},
            "camera_capture",
            {"duration": 5000, "gain": 5000},
            id="camera-reports-no-range",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            "imaging_guiding",
            None,
            None,
            "flat_panel_set_brightness",
            {"level": 99999},
            id="panel-disconnected",
        ),
        pytest.param(
            "imaging",
            "FlatDevice",
            {"MinBrightness": 0, "MaxBrightness": 0},
            "flat_panel_set_brightness",
            {"level": 99999},
            id="panel-reports-no-range",
            marks=pytest.mark.synthetic,
        ),
    ],
)
async def test_a_device_that_reports_no_limit_leaves_the_value_to_nina(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    state: str,
    device: str | None,
    block: dict | None,
    service: str,
    data: dict,
) -> None:
    """A disconnected device's command is N.I.N.A.'s to refuse, with its own
    reason, rather than this integration's against a range it cannot see.
    """
    rig.goto(state)
    if device is not None:
        _serve_with(rig, device, block)
    await set_up_at(hass, config_entry, rig, state)

    await _call(hass, service, **data)

    assert rig.sent != []


@pytest.mark.synthetic
async def test_a_slot_whose_name_another_slot_shares_is_sent(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """Two slots named alike, as unused slots often are, are two slots."""
    filters = [
        {"Name": "L", "Id": 0},
        {"Name": "Empty", "Id": 1},
        {"Name": "Empty", "Id": 2},
        {"Name": "Ha", "Id": 3},
    ]
    _serve_with(rig, "FilterWheel", {"AvailableFilters": filters})
    await set_up_at(hass, config_entry, rig, "imaging")

    await _call(hass, "filterwheel_change_filter", filter_index=1)

    assert rig.sent[-1] == ("/equipment/filterwheel/change-filter", {"filterId": 1})


_SET_BRIGHTNESS = "/equipment/flatdevice/set-brightness"
_SET_LIGHT = ("/equipment/flatdevice/set-light", {"on": "true"})


@pytest.mark.parametrize(
    ("block", "data", "sent"),
    [
        pytest.param(
            {}, {}, [(_SET_BRIGHTNESS, {"brightness": 16}), _SET_LIGHT], id="idle"
        ),
        pytest.param(
            {"Brightness": 2048, "LightOn": True},
            {},
            [(_SET_BRIGHTNESS, {"brightness": 2048}), _SET_LIGHT],
            id="already-lit",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            {"Brightness": 4096},
            {},
            [(_SET_BRIGHTNESS, {"brightness": 16}), _SET_LIGHT],
            id="off-holding-the-maximum",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            {},
            {"brightness": 1024},
            [(_SET_BRIGHTNESS, {"brightness": 1024}), _SET_LIGHT],
            id="brightness-given",
        ),
    ],
)
async def test_switching_the_panel_on_does_not_go_to_full_output(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    block: dict,
    data: dict,
    sent: list,
) -> None:
    """A bare `set-light?on=true` lights the panel at the last level N.I.N.A.
    set, or at `MaxBrightness`, so a brightness always goes first: the one
    given, a lit panel's own, or the dimmest — 16 of this panel's 4096.
    """
    _serve_with(rig, "FlatDevice", block)
    await set_up_at(hass, config_entry, rig, "imaging")

    await _call(hass, "flat_panel_set_light", light_on=True, **data)

    assert rig.sent == sent


async def test_the_dimmest_level_lights_a_panel_with_a_narrow_range(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """The simulator panel's range is 0-100, where level 1 of 255 rounds to 0:
    dark on an ASCOM panel, and the set-light after it lights the panel at
    MaxBrightness.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")

    await _call(hass, "flat_panel_set_light", light_on=True)

    assert rig.sent[0] == (_SET_BRIGHTNESS, {"brightness": 1})


@pytest.mark.synthetic
async def test_switching_a_lit_panel_off_sends_no_brightness(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    _serve_with(rig, "FlatDevice", {"Brightness": 2048, "LightOn": True})
    await set_up_at(hass, config_entry, rig, "imaging")

    await _call(hass, "flat_panel_set_light", light_on=False)

    assert rig.sent == [("/equipment/flatdevice/set-light", {"on": "false"})]


@pytest.mark.parametrize(
    ("state", "block", "data"),
    [
        pytest.param(
            "imaging",
            {"SupportsOpenClose": False},
            ("flat_panel_set_cover", {"open": True}),
            id="no-cover",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            "imaging",
            {"SupportsOnOff": False},
            ("flat_panel_set_light", {"light_on": True}),
            id="no-light",
            marks=pytest.mark.synthetic,
        ),
        pytest.param(
            "imaging",
            {"MinBrightness": 0, "MaxBrightness": 0},
            ("flat_panel_set_light", {"light_on": True}),
            id="no-range",
            marks=pytest.mark.synthetic,
        ),
        # Down: N.I.N.A. may connect it before the next poll, and would light
        # it at full output.
        pytest.param(
            "imaging_guiding",
            None,
            ("flat_panel_set_light", {"light_on": True}),
            id="disconnected",
        ),
        pytest.param(
            "imaging",
            None,
            ("flat_panel_set_light", {"light_on": False, "brightness": 1024}),
            id="brightness-while-off",
        ),
    ],
)
async def test_a_flat_panel_command_it_cannot_carry_out_safely_is_refused(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    state: str,
    block: dict | None,
    data: tuple[str, dict],
) -> None:
    if block is not None:
        rig.goto(state)
        _serve_with(rig, "FlatDevice", block)
    await set_up_at(hass, config_entry, rig, state)

    service, fields = data
    with pytest.raises(ServiceValidationError):
        await _call(hass, service, **fields)
    assert rig.sent == []


@pytest.mark.parametrize(
    ("service", "data", "sent"),
    [
        (
            "flat_panel_set_cover",
            {"open": True},
            ("/equipment/flatdevice/set-cover", {"closed": "false"}),
        ),
        (
            "flat_panel_set_light",
            {"light_on": False},
            ("/equipment/flatdevice/set-light", {"on": "false"}),
        ),
    ],
    ids=["cover", "light-off"],
)
async def test_a_disconnected_panel_is_left_to_nina_to_refuse(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    service: str,
    data: dict,
    sent: tuple,
) -> None:
    """A down panel reports every capability false, which is not a panel
    lacking them.
    """
    await set_up_at(hass, config_entry, rig, "imaging_guiding")

    await _call(hass, service, **data)

    assert rig.sent == [sent]


async def test_a_gain_is_held_to_the_cameras_own_range(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """The simulator camera reports GainMax 10000, past any one constant that
    would also fit the rig's camera, whose GainMax is 700.
    """
    await set_up_at(hass, config_entry, rig, "simulator_dome_parked")

    await _call(hass, "camera_capture", duration=1, gain=6000)

    assert rig.sent[-1][1]["gain"] == 6000


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
    path is answered `Success: true`. `dome_open` is refused on this rig's
    unsafe monitor, so `test_dome.py` sends it.
    """
    data: dict[str, Any] = {"temperature": -10} if service == "camera_cool" else {}
    await _call(hass, service, **data)
    assert rig.sent[-1][0] == path


async def test_the_actions_exist_before_any_entry_is_loaded(
    hass: HomeAssistant,
) -> None:
    """Bronze `action-setup`. Registered from `async_setup_entry`, the actions
    vanish with the last entry, and an automation referencing one fails
    validation rather than failing legibly at call time.
    """
    assert await async_setup_component(hass, DOMAIN, {})
    assert hass.services.has_service(DOMAIN, "mount_park")


async def test_a_sky_angle_move_is_refused_until_the_rotator_is_synced(
    hass: HomeAssistant, config_entry, rig, set_up_at
) -> None:
    """N.I.N.A. answers the move `Success: true`, then fails it unsynced, and
    the rotator stays where it is.
    """
    await set_up_at(hass, config_entry, rig, "scheduler_waiting")

    with pytest.raises(ServiceValidationError):
        await _call(hass, "rotator_move", position=90)
    assert rig.sent == []


@pytest.mark.synthetic
@pytest.mark.parametrize("position", [200, 299, 120], ids=str)
async def test_a_mechanical_angle_outside_the_profiles_range_is_refused(
    hass: HomeAssistant, config_entry, rig, set_up_at, position: float
) -> None:
    """N.I.N.A. folds it into the range rather than refusing it, so 200° on a
    half range from 300° turns the rotator to 20°.
    """
    await set_up_at(hass, config_entry, rig, "rotator_half_range")

    with pytest.raises(ServiceValidationError):
        await _call(hass, "rotator_move_mechanical", position=position)
    assert rig.sent == []


@pytest.mark.synthetic
@pytest.mark.parametrize(
    ("service", "position", "path"),
    [
        ("rotator_move_mechanical", 300, "/equipment/rotator/move-mechanical"),
        ("rotator_move_mechanical", 30, "/equipment/rotator/move-mechanical"),
        # A sky angle is folded to the same framing, flipped, so it is not
        # held to the mechanical range.
        ("rotator_move", 200, "/equipment/rotator/move"),
    ],
    ids=["range-start", "past-zero", "sky-angle"],
)
async def test_an_angle_the_profiles_range_allows_is_sent(
    hass: HomeAssistant,
    config_entry,
    rig,
    set_up_at,
    service: str,
    position: float,
    path: str,
) -> None:
    await set_up_at(hass, config_entry, rig, "rotator_half_range")

    await _call(hass, service, position=position)

    assert rig.sent[-1] == (path, {"position": float(position)})

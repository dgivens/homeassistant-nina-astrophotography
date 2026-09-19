"""Binary sensors.

Ten `*_connected` sensors are gone: a disconnected device makes its entities
unavailable, which is observable in automations (§5.2.1). The safety monitor is
the exception — a disconnected safety monitor would make `safety_unsafe`
unavailable, so a roof-close automation on `to: "off"` never fires, and
`to: "unavailable"` cannot substitute because it conflates
device-disconnected, N.I.N.A.-unreachable, HA-restarting and coordinator-failed.

Read-only mirrors of a switch, number or select are gone too; the survivor's
state is the ACTUAL value, not the last commanded one. `rotator_synced` stays
because sky-PA `Position` is meaningful only when synced.

**`safety_unsafe` is `on` when conditions are UNSAFE.** That is Home
Assistant's `SAFETY` device class — `on` means problem — and it is what the
shipped abort blueprint triggers on. An entity named for safety that reads `on`
for safe is a trap every user hits exactly once, at the worst possible moment.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .device import observed, read_field
from .entity import NinaEntity

# Read-only: nothing here commands the rig, so there is nothing to serialize.
PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NinaBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor, plus how to read it out of the snapshot.

    `kind` names the child device the entity hangs off (§5.1); `None` puts it on
    the hub. `verified` is False only for the dome, which cannot be validated
    against hardware — a test asserts every dome descriptor carries the marker.
    `survives_disconnect` drops §7.3's level 2 for the one entity whose job is
    to report that its own device is down.

    **A 1.4.5 entity that survives keeps its 1.4.5 `unique_id`**, through
    `unique_id_suffix` where the new `key` reads better than the old one. Home
    Assistant keys the registry on `unique_id`, so changing it mints a fresh
    entity and strands the old row as `unavailable` — a roof-close automation
    pointing at the 1.4.5 safety entity would stop working on upgrade. Renaming
    is the user's to do, never the upgrade's.
    """

    value: Callable[[NinaData], bool | None]
    kind: str | None
    attributes: Callable[[NinaData], Mapping[str, Any]] | None = None
    verified: bool = True
    survives_disconnect: bool = False
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`. `unique_id` is
    `{entry_id}_{unique_id_suffix or key}`."""


def _unsafe(data: NinaData) -> bool | None:
    """`on` means UNSAFE, which is HA's `SAFETY` convention and the blueprint's."""
    monitor = data.snapshot.safety_monitor
    if monitor is None or monitor.is_safe is None:
        return None
    return not monitor.is_safe


def _autofocus_reason(data: NinaData) -> str | None:
    """Which of the two ways an autofocus fails this is, or `None` for neither.

    They look nothing alike, and what to do about them differs.

    A HUNG run is an absence — a start no finish answers, past the profile's
    timeout — and the fold decides it (§4.4). It never writes a report, so
    `/equipment/focuser/last-af` still holds the PREVIOUS run: anything read off
    that report belongs to a different, probably good, run.

    A REJECTED run finishes normally and is invisible in the event stream: the
    report N.I.N.A. writes carries no verdict, so the only evidence is its R²
    falling under the profile's `RSquaredThreshold`. That is the case that
    costs a night, because the focuser stays where it was and the subs are soft
    with nothing raised.

    The report outlives the session, so it is believed only while it is newer
    than the session start — otherwise a bad run from a previous night would
    read as a problem the moment Home Assistant restarted.
    """
    if data.session.autofocus.failed:
        return "hung"
    report = data.autofocus_report
    threshold = data.profile.r_squared_threshold
    if report is None or report.r_squared is None or threshold is None:
        return None
    start = data.session.session_start
    if report.timestamp is None or (start is not None and report.timestamp < start):
        return None
    return "rejected" if report.r_squared < threshold else None


def _autofocus_failed(data: NinaData) -> bool | None:
    """`on` for either way an autofocus fails; `reason` says which."""
    return _autofocus_reason(data) is not None


def _autofocus_verdict(data: NinaData) -> Mapping[str, Any]:
    """What the verdict was made from, beside the verdict.

    `on` alone cannot be acted on: a hung run wants the sequence looked at,
    while a rejected one wants the focus range or the star detector looked at,
    and only a hung run means the report on display is a different run's.

    The R² is carried here rather than left to
    `sensor.<instance>_focuser_autofocus_r2` — which is diagnostic and ships
    disabled — because it is the value this judgement was actually made on.
    A reader comparing some other R² against this threshold could contradict
    the sensor it sits on: the run's R² is the worst of `RSquares`, which is
    not quite the worst of the equations `fits` could be parsed from.
    """
    return {
        "reason": _autofocus_reason(data),
        "r_squared": None if (report := data.autofocus_report) is None
        else report.r_squared,
        "r_squared_threshold": data.profile.r_squared_threshold,
    }


DESCRIPTIONS: tuple[NinaBinarySensorDescription, ...] = (
    NinaBinarySensorDescription(
        key="safety_unsafe",
        translation_key="safety_unsafe",
        unique_id_suffix="safetymonitor_is_safe",
        device_class=BinarySensorDeviceClass.SAFETY,
        kind="safety_monitor",
        value=_unsafe,
    ),
    NinaBinarySensorDescription(
        key="safety_monitor_connected",
        translation_key="safety_monitor_connected",
        unique_id_suffix="safetymonitor_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="safety_monitor",
        survives_disconnect=True,
        value=read_field("safety_monitor", "connected"),
    ),
    NinaBinarySensorDescription(
        key="camera_is_exposing",
        translation_key="camera_is_exposing",
        unique_id_suffix="camera_exposing",
        kind="camera",
        value=read_field("camera", "is_exposing"),
    ),
    NinaBinarySensorDescription(
        key="mount_at_park",
        translation_key="mount_at_park",
        unique_id_suffix="mount_parked",
        kind="mount",
        value=read_field("mount", "at_park"),
    ),
    NinaBinarySensorDescription(
        key="mount_at_home",
        translation_key="mount_at_home",
        kind="mount",
        value=read_field("mount", "at_home"),
    ),
    NinaBinarySensorDescription(
        key="autofocus_failed",
        translation_key="autofocus_failed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        kind="focuser",
        # Derived from the folded event set on read — there is no timer to leak.
        value=_autofocus_failed,
        attributes=_autofocus_verdict,
    ),
    NinaBinarySensorDescription(
        key="sequencer_running",
        translation_key="sequencer_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        kind=None,
        # The sequencer, not the camera: a rig waiting out a target's start
        # window is running and not imaging. A NEW `unique_id` deliberately —
        # 1.4.5's `_sequence_running` answered the other question, and a row
        # whose meaning changes under an automation is worse than one that goes
        # unavailable and asks to be repointed.
        value=lambda data: data.running,
    ),
    NinaBinarySensorDescription(
        key="scheduler_waiting",
        translation_key="scheduler_waiting",
        kind=None,
        # No device class: HA has none for waiting, and RUNNING here would read
        # as a third opinion on whether the sequence is going.
        value=lambda data: data.wait_ends_at is not None,
    ),
    NinaBinarySensorDescription(
        key="imaging",
        translation_key="imaging",
        device_class=BinarySensorDeviceClass.RUNNING,
        kind=None,
        # §6.2's activity heuristic: a rising count, a camera exposing, or an
        # IMAGE-SAVE inside five minutes. Frames are arriving, whatever the
        # sequencer says.
        value=lambda data: data.imaging,
    ),
    NinaBinarySensorDescription(
        key="focuser_is_moving",
        translation_key="focuser_is_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="focuser",
        value=read_field("focuser", "is_moving"),
    ),
    NinaBinarySensorDescription(
        key="filterwheel_is_moving",
        translation_key="filterwheel_is_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="filter_wheel",
        value=read_field("filter_wheel", "is_moving"),
    ),
    NinaBinarySensorDescription(
        key="rotator_is_moving",
        translation_key="rotator_is_moving",
        device_class=BinarySensorDeviceClass.MOVING,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="rotator",
        value=read_field("rotator", "is_moving"),
    ),
    NinaBinarySensorDescription(
        key="rotator_synced",
        translation_key="rotator_synced",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="rotator",
        # Retained (§5.2.3): unsynced, sky-PA `Position` degenerates toward
        # `MechanicalPosition`, so the position sensors mean nothing without it.
        value=read_field("rotator", "synced"),
    ),
    # The dome is spec-derived and untested against hardware (§5.3.1): bare
    # field reads, no derived state, and `verified=False` on every one.
    NinaBinarySensorDescription(
        key="dome_at_park",
        translation_key="dome_at_park",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "at_park"),
    ),
    NinaBinarySensorDescription(
        key="dome_at_home",
        translation_key="dome_at_home",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "at_home"),
    ),
    NinaBinarySensorDescription(
        key="dome_slewing",
        translation_key="dome_slewing",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "slewing"),
    ),
)


class NinaBinarySensor(NinaEntity, BinarySensorEntity):
    """One descriptor, read out of the published snapshot."""

    entity_description: NinaBinarySensorDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaBinarySensorDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description
        self._survives_disconnect = description.survives_disconnect

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        build = self.entity_description.attributes
        return None if build is None else build(self.coordinator.data)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    added: set[str] = set()

    @callback
    def _add_observed() -> None:
        """Create the entities whose equipment the snapshot now carries.

        Re-run on every publish, so equipment that connects hours after Home
        Assistant started still gets its entities (Gold `dynamic-devices`); a
        slot never returns to `None`, so nothing is ever removed here.
        """
        new = [
            NinaBinarySensor(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and observed(coordinator.data, description.kind)
        ]
        if not new:
            return
        added.update(sensor.entity_description.key for sensor in new)
        async_add_entities(new)

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

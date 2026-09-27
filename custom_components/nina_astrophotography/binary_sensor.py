"""Binary sensors.

A disconnected device makes its entities unavailable, so equipment has no
`*_connected` sensor — except the safety monitor. `unavailable` cannot tell a
dropped monitor from N.I.N.A. unreachable or Home Assistant restarting, and a
roof-close automation must act on the first.

**`safety_unsafe` is `on` when conditions are unsafe**, as Home Assistant's
`SAFETY` device class means it.
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

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class NinaBinarySensorDescription(BinarySensorEntityDescription):
    """A binary sensor, plus how to read it out of the snapshot.

    `kind` names the child device; `None` puts it on the hub. `verified` is
    False only for the dome, which no hardware has validated.
    `survives_disconnect` keeps an entity available while its device is down,
    for the one whose job is to report that.
    """

    value: Callable[[NinaData], bool | None]
    kind: str | None
    attributes: Callable[[NinaData], Mapping[str, Any]] | None = None
    verified: bool = True
    survives_disconnect: bool = False
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`, so an upgraded entity keeps
    its registry row. `unique_id` is `{entry_id}_{unique_id_suffix or key}`."""


def _unsafe(data: NinaData) -> bool | None:
    """`on` means unsafe."""
    monitor = data.snapshot.safety_monitor
    if monitor is None or monitor.is_safe is None:
        return None
    return not monitor.is_safe


def _autofocus_reason(data: NinaData) -> str | None:
    """`"hung"`, `"rejected"`, or `None` if the last autofocus did neither.

    A hung run is a start with no finish past the profile's timeout, decided
    by the fold; it writes no report, so the report on hand is an earlier
    run's. A rejected run finishes normally, and only its R² falling under
    the profile's `RSquaredThreshold` shows it. A report older than the
    session start is a previous night's and is ignored.
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
    """Why the verdict was reached, and the R² and threshold it compared.

    A hung run and a rejected one need different fixes. The R² sensor ships
    disabled, so the value judged is carried here.
    """
    return {
        "reason": _autofocus_reason(data),
        "r_squared": None
        if (report := data.autofocus_report) is None
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
        value=_autofocus_failed,
        attributes=_autofocus_verdict,
    ),
    NinaBinarySensorDescription(
        key="sequencer_running",
        translation_key="sequencer_running",
        device_class=BinarySensorDeviceClass.RUNNING,
        kind=None,
        # The sequencer, not the camera: waiting out a target's start window is
        # running and not imaging. Deliberately not 1.4.5's `sequence_running`
        # `unique_id`, which meant `imaging`.
        value=lambda data: data.running,
    ),
    NinaBinarySensorDescription(
        key="scheduler_waiting",
        translation_key="scheduler_waiting",
        kind=None,
        value=lambda data: data.wait_ends_at is not None,
    ),
    NinaBinarySensorDescription(
        key="imaging",
        translation_key="imaging",
        device_class=BinarySensorDeviceClass.RUNNING,
        kind=None,
        # A rising frame count, a camera exposing, or an IMAGE-SAVE within five
        # minutes, whatever the sequencer says.
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
        # The sky position angle means nothing until the rotator is synced.
        value=read_field("rotator", "synced"),
    ),
    # From the spec alone; no hardware has validated the dome.
    NinaBinarySensorDescription(
        key="dome_at_park",
        translation_key="dome_at_park",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "at_park"),
    ),
    NinaBinarySensorDescription(
        key="dome_at_home",
        translation_key="dome_at_home",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "at_home"),
    ),
    NinaBinarySensorDescription(
        key="dome_slewing",
        translation_key="dome_slewing",
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
        """Create the entities whose equipment has now been observed."""
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

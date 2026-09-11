"""Numbers: the settable equipment values, in the driver's own units.

**Ranges are per-device and come from the model.** Flat panel brightness spans
`MinBrightness`–`MaxBrightness` (4096 on this panel, 255 on an Alnitak) and the
USB limit spans `USBLimitMin`–`USBLimitMax` (40–100 on this camera). A
hardcoded range is not cosmetic here: out-of-range input is **silently clamped
and answers `Success: true`**, so a range wider than the driver's turns a
refusal into a value the user never asked for and never sees.

Where the driver reports no range at all — the focuser, which has no `MaxStep`
on the wire, the camera's cooling setpoint, and the rotator and dome, whose
ranges are geometry rather than hardware — the bound is a documented constant on
the descriptor.

**The declared range is the validation.** `number.set_value` refuses a value
outside the entity's own `min`/`max` before it reaches the platform, so an
honest per-device range is what stands between a typo and a value N.I.N.A.
clamps to something else while answering `Success: true`. What Home Assistant
cannot know is a driver reporting no usable range at all — `Min 0 / Max 0`,
which every value is "inside" — and that refusal lives here.

**A number never confirms itself from the command response** (§3.5). The state
is the next poll's reading; `flat_panel_brightness` in particular is raw driver
units, not the `light`'s HA 0–255, and setting it does not toggle the light —
brightness 0 is not off (§5.3.4).
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import DEGREE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.v2.client import NinaClientV2
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1

# The focuser reports no travel limit — `/equipment/focuser/info` carries
# Position and StepSize and nothing else — so the upper bound is a constant
# wide enough for any focuser rather than a driver reading. N.I.N.A. clamps at
# the driver's own MaxStep.
_FOCUSER_MAX_STEP = 200_000


@dataclass(frozen=True, kw_only=True)
class NinaNumberDescription(NumberEntityDescription):
    """A number, plus how to read it, bound it and send it.

    `kind` names the child device the entity hangs off (§5.1). `verified` is
    False only for the dome, which cannot be validated against hardware — a test
    asserts every dome descriptor carries the marker.

    `bounds` is the driver's own range for this poll, and `None` from it means
    the driver reports no usable range; the descriptor's own
    `native_min_value`/`native_max_value` are the documented fallback, used
    directly by the entities whose range is geometry rather than hardware.

    **A 1.4.5 entity that survives keeps its 1.4.5 `unique_id`**, through
    `unique_id_suffix` where the new `key` reads better than the old one. Home
    Assistant keys the registry on `unique_id`, so changing it mints a fresh
    entity and strands the old row as `unavailable`.
    """

    value: Callable[[NinaData], float | None]
    kind: str
    command: Callable[[NinaClientV2, float], Awaitable[None]]
    bounds: Callable[[NinaData], tuple[float, float] | None] | None = None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`. `unique_id` is
    `{entry_id}_{unique_id_suffix or key}`."""


def _read(kind: str, field: str) -> Callable[[NinaData], float | None]:
    """One reading off one equipment model, `None` while the device is absent."""
    def value(data: NinaData) -> float | None:
        device = getattr(data.snapshot, kind)
        return None if device is None else getattr(device, field)

    return value


def _driver_range(
    kind: str, low_field: str, high_field: str
) -> Callable[[NinaData], tuple[float, float] | None]:
    """The driver's own range, or `None` when it reports none.

    A disconnected flat panel reports `Min 0 / Max 0`, which is an empty range
    rather than a permissive one: every value is "in range" of it.
    """
    def bounds(data: NinaData) -> tuple[float, float] | None:
        device = getattr(data.snapshot, kind)
        if device is None:
            return None
        low, high = getattr(device, low_field), getattr(device, high_field)
        if low is None or high is None or high <= low:
            return None
        return float(low), float(high)

    return bounds


DESCRIPTIONS: tuple[NinaNumberDescription, ...] = (
    NinaNumberDescription(
        key="flat_panel_brightness",
        translation_key="flat_panel_brightness",
        native_step=1,
        mode=NumberMode.SLIDER,
        kind="flat_device",
        value=_read("flat_device", "brightness"),
        bounds=_driver_range("flat_device", "min_brightness", "max_brightness"),
        command=lambda client, value: client.set_flat_brightness(round(value)),
    ),
    NinaNumberDescription(
        key="focuser_position",
        translation_key="focuser_position",
        unique_id_suffix="focuser_position_control",
        native_min_value=0,
        native_max_value=_FOCUSER_MAX_STEP,
        native_step=1,
        native_unit_of_measurement="steps",
        mode=NumberMode.BOX,
        kind="focuser",
        value=_read("focuser", "position"),
        command=lambda client, value: client.move_focuser(round(value)),
    ),
    NinaNumberDescription(
        key="camera_target_temperature",
        translation_key="camera_target_temperature",
        unique_id_suffix="camera_cooling_setpoint",
        device_class=NumberDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        # No setpoint range on the wire; wide enough for any cooled camera.
        native_min_value=-50,
        native_max_value=50,
        native_step=0.5,
        mode=NumberMode.BOX,
        kind="camera",
        # The ACTUAL setpoint, not the last one commanded (§5.2.3). There is no
        # setpoint endpoint either: changing it is a cool-down to the new value.
        value=_read("camera", "target_temperature"),
        command=lambda client, value: client.set_target_temperature(value),
    ),
    NinaNumberDescription(
        key="camera_usb_limit",
        translation_key="camera_usb_limit",
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="camera",
        value=_read("camera", "usb_limit"),
        bounds=_driver_range("camera", "usb_limit_min", "usb_limit_max"),
        command=lambda client, value: client.set_usb_limit(round(value)),
    ),
    NinaNumberDescription(
        key="rotator_position",
        translation_key="rotator_position",
        unique_id_suffix="rotator_position_control",
        native_min_value=0,
        native_max_value=360,
        native_step=0.01,
        native_unit_of_measurement=DEGREE,
        mode=NumberMode.BOX,
        kind="rotator",
        # Sky position angle, meaningful only while `rotator_synced` is on.
        value=_read("rotator", "position"),
        command=lambda client, value: client.move_rotator(value),
    ),
    NinaNumberDescription(
        key="rotator_mechanical_position",
        translation_key="rotator_mechanical_position",
        native_min_value=0,
        native_max_value=360,
        native_step=0.01,
        native_unit_of_measurement=DEGREE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="rotator",
        value=_read("rotator", "mechanical_position"),
        command=lambda client, value: client.move_rotator_mechanical(value),
    ),
    # Spec-derived and untested against hardware (§5.3.1): a bare field read, a
    # geometric range, and `verified=False`.
    NinaNumberDescription(
        key="dome_azimuth",
        translation_key="dome_azimuth",
        native_min_value=0,
        native_max_value=360,
        native_step=0.1,
        native_unit_of_measurement=DEGREE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=_read("dome", "azimuth"),
        command=lambda client, value: client.slew_dome(value),
    ),
)


class NinaNumber(NinaEntity, NumberEntity):
    """One descriptor: read from the snapshot, written through the client."""

    entity_description: NinaNumberDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaNumberDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description

    @property
    def _range(self) -> tuple[float, float] | None:
        """The range to offer, this poll; `None` when the driver reports none."""
        description = self.entity_description
        if description.bounds is None:
            return description.native_min_value, description.native_max_value
        return description.bounds(self.coordinator.data)

    @property
    def native_min_value(self) -> float:
        bounds = self._range
        return super().native_min_value if bounds is None else bounds[0]

    @property
    def native_max_value(self) -> float:
        bounds = self._range
        return super().native_max_value if bounds is None else bounds[1]

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value(self.coordinator.data)

    async def async_set_native_value(self, value: float) -> None:
        if self._range is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_driver_range",
                translation_placeholders={"entity_id": self.entity_id},
            )
        try:
            await self.entity_description.command(self.coordinator.client, value)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the command: {exc}") from exc
        await self.coordinator.async_request_refresh()


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
            NinaNumber(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and getattr(coordinator.data.snapshot, description.kind) is not None
        ]
        if not new:
            return
        added.update(number.entity_description.key for number in new)
        async_add_entities(new)

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

"""Numbers: the settable equipment values, in the driver's own units.

**Ranges are the driver's own**, such as `MinBrightness`–`MaxBrightness`. They
are the validation: `number.set_value` refuses a value outside them, and
N.I.N.A. silently clamps one and answers `Success: true`. A driver reporting
no usable range (`Min 0 / Max 0`) is refused here. Where no driver reports a
range (the focuser, the cooling setpoint, and the geometric rotator and dome),
the descriptor carries a constant.

**A switch device channel is a number when writable and wider than one step**,
such as a dew heater at 0–100. Its range is the channel's own, and it reads
`Value`, never `TargetValue`.

**The state is the next poll's reading**, never the command's response.
`flat_panel_brightness` is in driver units, not the light's 0–255, and 0 is
not off.
"""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from functools import partial

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import DEGREE, EntityCategory, Platform, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.models import SwitchChannelModel
from .api.v2.client import NinaClientV2
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .device import channel_key, channels_for, observed, read_field
from .entity import (
    NinaChannelEntity,
    NinaDescribedEntity,
    NinaEntityDescription,
    async_add_observed,
)

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1

# No `MaxStep` reaches the wire, so this is wide enough for any focuser;
# N.I.N.A. clamps at the driver's own.
_FOCUSER_MAX_STEP = 200_000


@dataclass(frozen=True, kw_only=True)
class NinaNumberDescription(NinaEntityDescription, NumberEntityDescription):
    """A number, plus how to read it, bound it and send it.

    `bounds` reads the driver's range, `None` when it reports none; without
    `bounds`, `native_min_value` and `native_max_value` are the range.
    """

    value: Callable[[NinaData], float | None]
    kind: str
    command: Callable[[NinaClientV2, float], Awaitable[None]]
    bounds: Callable[[NinaData], tuple[float, float] | None] | None = None


DESCRIPTIONS: tuple[NinaNumberDescription, ...] = (
    NinaNumberDescription(
        key="flat_panel_brightness",
        translation_key="flat_panel_brightness",
        native_step=1,
        mode=NumberMode.SLIDER,
        kind="flat_device",
        value=read_field("flat_device", "brightness"),
        bounds=read_field("flat_device", "brightness_range"),
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
        value=read_field("focuser", "position"),
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
        # Setting it cools to the new value; there is no setpoint endpoint.
        value=read_field("camera", "target_temperature"),
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
        value=read_field("camera", "usb_limit"),
        bounds=read_field("camera", "usb_limit_range"),
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
        value=read_field("rotator", "position"),
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
        value=read_field("rotator", "mechanical_position"),
        command=lambda client, value: client.move_rotator_mechanical(value),
    ),
    # From the spec alone; no hardware has validated it.
    NinaNumberDescription(
        key="dome_azimuth",
        translation_key="dome_azimuth",
        native_min_value=0,
        native_max_value=360,
        native_step=0.1,
        native_unit_of_measurement=DEGREE,
        mode=NumberMode.BOX,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "azimuth"),
        command=lambda client, value: client.slew_dome(value),
    ),
)


class NinaNumber(NinaDescribedEntity, NumberEntity):
    """One descriptor: read from the snapshot, written through the client."""

    entity_description: NinaNumberDescription

    @property
    def _range(self) -> tuple[float, float] | None:
        """The range to offer, this poll; `None` when the driver reports none."""
        description = self.entity_description
        if description.bounds is None:
            return super().native_min_value, super().native_max_value
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
        await self._async_send(
            self.entity_description.command(self.coordinator.client, value)
        )


class NinaNumberChannel(NinaChannelEntity, NumberEntity):
    """One writable, non-binary channel of the N.I.N.A. switch device.

    The range is held from creation, so it survives the device disconnecting.
    """

    _attr_mode = NumberMode.SLIDER

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        channel: SwitchChannelModel,
    ) -> None:
        super().__init__(coordinator, entry, channel)
        assert channel.minimum is not None and channel.maximum is not None
        self._attr_native_min_value = channel.minimum
        self._attr_native_max_value = channel.maximum
        if channel.step_size is not None:
            self._attr_native_step = channel.step_size

    @property
    def native_value(self) -> float | None:
        return self.channel_value

    async def async_set_native_value(self, value: float) -> None:
        await self._async_set_channel(value)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator

    def _observed(data: NinaData) -> Iterator[tuple[str, Callable[[], NumberEntity]]]:
        for description in DESCRIPTIONS:
            if observed(data, description.kind):
                yield (
                    description.key,
                    partial(NinaNumber, coordinator, entry, description),
                )
        for channel in channels_for(data, Platform.NUMBER):
            yield (
                channel_key(channel),
                partial(NinaNumberChannel, coordinator, entry, channel),
            )

    async_add_observed(entry, async_add_entities, _observed)

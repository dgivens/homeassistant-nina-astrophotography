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
from .api.models import SwitchChannelModel
from .api.v2.client import NinaClientV2
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .device import channel_key, channels_of, observed, read_field
from .entity import NinaChannelEntity, NinaEntity

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1

# No `MaxStep` reaches the wire, so this is wide enough for any focuser;
# N.I.N.A. clamps at the driver's own.
_FOCUSER_MAX_STEP = 200_000


@dataclass(frozen=True, kw_only=True)
class NinaNumberDescription(NumberEntityDescription):
    """A number, plus how to read it, bound it and send it.

    `kind` names the child device. `verified` is False only for the dome,
    which no hardware has validated. `bounds` reads the driver's range, `None`
    when it reports none; without `bounds`, `native_min_value` and
    `native_max_value` are the range.
    """

    value: Callable[[NinaData], float | None]
    kind: str
    command: Callable[[NinaClientV2, float], Awaitable[None]]
    bounds: Callable[[NinaData], tuple[float, float] | None] | None = None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`, so an upgraded entity keeps
    its registry row. `unique_id` is `{entry_id}_{unique_id_suffix or key}`."""


def _driver_range(
    kind: str, low_field: str, high_field: str
) -> Callable[[NinaData], tuple[float, float] | None]:
    """The driver's own range, or `None` when it reports none, as a
    disconnected flat panel's `Min 0 / Max 0` does.
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
        value=read_field("flat_device", "brightness"),
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
        try:
            await self.entity_description.command(self.coordinator.client, value)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the command: {exc}") from exc
        await self.coordinator.async_request_refresh()


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
        if self.channel is None:
            # The API answers `Success: true` to a `set` for a missing index.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="channel_gone",
                translation_placeholders={
                    "channel": self._attr_name or str(self._index)
                },
            )
        try:
            await self.coordinator.client.set_switch_value(self._index, value)
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
        """Create the entities whose equipment has now been observed."""
        descriptions = [
            description
            for description in DESCRIPTIONS
            if description.key not in added
            and observed(coordinator.data, description.kind)
        ]
        channels = [
            channel
            for channel in channels_of(coordinator.data)
            if channel.writable
            and not channel.binary
            and channel.minimum is not None
            and channel.maximum is not None
            and channel_key(channel) not in added
        ]
        if not descriptions and not channels:
            return
        added.update(description.key for description in descriptions)
        added.update(channel_key(channel) for channel in channels)
        async_add_entities(
            [NinaNumber(coordinator, entry, d) for d in descriptions]
            + [NinaNumberChannel(coordinator, entry, c) for c in channels]
        )

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

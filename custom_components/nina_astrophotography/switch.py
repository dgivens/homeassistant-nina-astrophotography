"""Switches.

**The state is the reported value, never the one commanded.** A command
answers `Success: true` before the equipment moves, so the state changes when
the next poll says it did.

**`switch.guider` is on whenever the guider is running**: every state but
`Stopped`, and a `LostLock` outliving a `GUIDER-STOP`. Keyed on `Guiding`, it
would read off while calibrating, and a tap would restart guiding
mid-exposure. `sensor.guider_status` tells the running states apart.

**The cooler is two endpoints, not a toggle.** `/equipment/camera/cool` needs a
setpoint, so on cools to the one the camera reports; a camera reporting none is
refused.

**A switch device channel is a switch only when binary** (`Max - Min ==
StepSize`), and its on/off values are its own range ends. It reads `Value`,
never `TargetValue`, which is only what it was last asked for.
"""

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from functools import partial
import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory, Platform
from homeassistant.core import HomeAssistant, callback
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

_LOGGER = logging.getLogger(__name__)

# One in-flight command per platform: these switch hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaSwitchDescription(NinaEntityDescription, SwitchEntityDescription):
    """A switch, plus how to read it and how to send both directions.

    `command` gets the snapshot too, since the cooler sends the camera's own
    setpoint. `supported` gates on a capability the driver reports, such as a
    flat panel's cover.
    """

    value: Callable[[NinaData], bool | None]
    command: Callable[[NinaClientV2, NinaData, bool], Awaitable[None]]
    supported: Callable[[NinaData], bool] | None = None


def _supports(kind: str, field: str) -> Callable[[NinaData], bool]:
    read = read_field(kind, field)
    return lambda data: bool(read(data))


def _guider_running(data: NinaData) -> bool | None:
    """On for every guider state but `Stopped`.

    `Paused` reads on too, though N.I.N.A. ignores a stop sent during it. The
    exception is a `LostLock` still reported after a `GUIDER-STOP`; see
    `session.pending_guider_stop` and `polling.GuiderStopLatch`.
    """
    guider = data.snapshot.guider
    state = guider.state if guider is not None else None
    if state is None:
        return None
    if state == "LostLock" and data.guider_stopped:
        return False
    return state != "Stopped"


def _cover_open(data: NinaData) -> bool | None:
    """`NeitherOpenNorClosed` and `Unknown` are neither, and read `unknown`."""
    panel = data.snapshot.flat_device
    state = panel.cover_state if panel is not None else None
    return {"open": True, "closed": False}.get((state or "").lower())


def _toggle(method: str) -> Callable[[NinaClientV2, NinaData, bool], Awaitable[None]]:
    """A command whose whole payload is the direction."""

    async def send(client: NinaClientV2, data: NinaData, on: bool) -> None:
        await getattr(client, method)(on)

    return send


def _either(
    on_method: str, off_method: str
) -> Callable[[NinaClientV2, NinaData, bool], Awaitable[None]]:
    """Two directions that are two different endpoints."""

    async def send(client: NinaClientV2, data: NinaData, on: bool) -> None:
        await getattr(client, on_method if on else off_method)()

    return send


async def _set_guiding(client: NinaClientV2, data: NinaData, on: bool) -> None:
    """Start guiding on the existing calibration, or stop."""
    if on:
        await client.start_guiding(force_calibration=False)
    else:
        await client.stop_guiding()


async def _set_cooler(client: NinaClientV2, data: NinaData, on: bool) -> None:
    """Cool to the driver's current setpoint, or warm up.

    A warm-up leaves the setpoint at its final value, not the imaging
    temperature; the target temperature number cools to a chosen one.
    """
    if not on:
        await client.warm_camera()
        return
    camera = data.snapshot.camera
    setpoint = camera.target_temperature if camera is not None else None
    if setpoint is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_cooling_setpoint"
        )
    await client.cool_camera(setpoint)


DESCRIPTIONS: tuple[NinaSwitchDescription, ...] = (
    NinaSwitchDescription(
        key="guider",
        unique_id_suffix="guider_switch",
        # The guider device's one function, so it takes the device's name.
        name=None,
        kind="guider",
        value=_guider_running,
        command=_set_guiding,
    ),
    NinaSwitchDescription(
        key="camera_cooler",
        translation_key="camera_cooler",
        unique_id_suffix="camera_cooler_switch",
        kind="camera",
        value=read_field("camera", "cooler_on"),
        command=_set_cooler,
    ),
    NinaSwitchDescription(
        key="camera_dew_heater",
        translation_key="camera_dew_heater",
        kind="camera",
        value=read_field("camera", "dew_heater_on"),
        command=_toggle("set_dew_heater"),
    ),
    NinaSwitchDescription(
        key="flat_panel_cover",
        translation_key="flat_panel_cover",
        kind="flat_device",
        supported=_supports("flat_device", "supports_open_close"),
        value=_cover_open,
        command=_either("open_flat_cover", "close_flat_cover"),
    ),
    NinaSwitchDescription(
        key="livestack",
        translation_key="livestack",
        # Always created. Without the livestack plugin it reads off, and
        # turning it on raises.
        kind=None,
        value=lambda data: data.livestack.running,
        command=_either("start_livestack", "stop_livestack"),
    ),
    NinaSwitchDescription(
        key="rotator_reverse",
        translation_key="rotator_reverse",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="rotator",
        value=read_field("rotator", "reverse"),
        command=_toggle("set_rotator_reverse"),
    ),
    # From the spec alone; no hardware has validated it.
    NinaSwitchDescription(
        key="dome_following",
        translation_key="dome_following",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=read_field("dome", "following"),
        command=_toggle("set_dome_follow"),
    ),
)


class NinaSwitch(NinaDescribedEntity, SwitchEntity):
    """One descriptor: read from the snapshot, written through the client."""

    entity_description: NinaSwitchDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(False)

    async def _send(self, on: bool) -> None:
        await self._async_send(
            self.entity_description.command(
                self.coordinator.client, self.coordinator.data, on
            )
        )


class NinaSwitchChannel(NinaChannelEntity, SwitchEntity):
    """One binary channel of the N.I.N.A. switch device.

    On and off are the channel's range ends, held from creation so they
    survive the device disconnecting.
    """

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        channel: SwitchChannelModel,
    ) -> None:
        super().__init__(coordinator, entry, channel)
        assert channel.minimum is not None and channel.maximum is not None
        self._off_value = channel.minimum
        self._on_value = channel.maximum

    @property
    def is_on(self) -> bool | None:
        value = self.channel_value
        return None if value is None else value == self._on_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set_channel(self._on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set_channel(self._off_value)


def _usable(data: NinaData, description: NinaSwitchDescription) -> bool:
    """The device has been seen, and reports the capability the switch drives."""
    return observed(data, description.kind) and (
        description.supported is None or description.supported(data)
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    warned: set[int] = set()

    @callback
    def _warn_about_unplaced() -> None:
        """Warn, once per channel, when no platform can take a channel."""
        for channel in channels_for(coordinator.data, None):
            if channel.index in warned:
                continue
            warned.add(channel.index)
            _LOGGER.warning(
                "N.I.N.A. switch channel %s (%r) is writable but reports no "
                "usable range (min=%s max=%s step=%s), so no entity was "
                "created for it",
                channel.index,
                channel.name,
                channel.minimum,
                channel.maximum,
                channel.step_size,
            )

    def _observed(data: NinaData) -> Iterator[tuple[str, Callable[[], SwitchEntity]]]:
        for description in DESCRIPTIONS:
            if _usable(data, description):
                yield (
                    description.key,
                    partial(NinaSwitch, coordinator, entry, description),
                )
        for channel in channels_for(data, Platform.SWITCH):
            yield (
                channel_key(channel),
                partial(NinaSwitchChannel, coordinator, entry, channel),
            )

    async_add_observed(entry, async_add_entities, _observed)
    _warn_about_unplaced()
    entry.async_on_unload(coordinator.async_add_listener(_warn_about_unplaced))

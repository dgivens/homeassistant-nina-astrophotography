"""Switches: the things that are either on or off, and can be told to change.

**The state is the actual value, never the last commanded one** (§5.2.3), and
never the command's own response (§3.5). Every command on this API answers
`Success: true` without confirming anything — `set-light?on=true` was measured
answering success while an immediate re-read still showed `LightOn: false` — so
a switch that optimistically assumed its new state would lie for a poll and
then flip back. The state moves when the next poll says it moved.

**`switch.guider` is on whenever the guider is RUNNING**, which is every state
but `Stopped`. `State == "Guiding"` reads *off* through `LostLock` and
`Calibrating`, and a dashboard tap on a switch that looks off sends
`/equipment/guider/start` and forces a re-settle mid-exposure.
`sensor.guider_status` is what distinguishes the running states.

**The cooler is two endpoints, not a toggle.** `/equipment/camera/cool` takes
the setpoint and has no "resume at the existing target" form, so cooling starts
at the temperature the camera reports as its own target; a camera that reports
none — `TargetTemp: "NaN"`, which is what a camera with no cooling sends — is
refused rather than cooled to a guessed temperature.

**A channel of the N.I.N.A. switch device belongs here only when it is
binary** — `Max - Min == StepSize` (§5.3.5) — and its on/off values are that
channel's own range ends, not 1 and 0. It reads `Value`, the channel's state,
never `TargetValue`, which is only what the channel was last asked for.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.models import SwitchChannelModel
from .api.v2.client import NinaClientV2
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

# One in-flight command per platform: these switch hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaSwitchDescription(SwitchEntityDescription):
    """A switch, plus how to read it and how to send both directions.

    `kind` names the child device the entity hangs off (§5.1); `None` puts it on
    the hub. `verified` is False only for the dome, which cannot be validated
    against hardware — a test asserts every dome descriptor carries the marker.

    `command` receives the published snapshot as well as the client, because a
    command can need a reading to send: the cooler's setpoint is the camera's
    own `TargetTemp`.

    `supported` is a second gate beyond the device being observed, for a
    capability the driver reports per device — a flat panel with no cover would
    otherwise ship a switch that does nothing.

    **A 1.4.5 entity that survives keeps its 1.4.5 `unique_id`**, through
    `unique_id_suffix` where the new `key` reads better than the old one. Home
    Assistant keys the registry on `unique_id`, so changing it mints a fresh
    entity and strands the old row as `unavailable`.
    """

    value: Callable[[NinaData], bool | None]
    kind: str | None
    command: Callable[[NinaClientV2, NinaData, bool], Awaitable[None]]
    supported: Callable[[NinaData], bool] | None = None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`. `unique_id` is
    `{entry_id}_{unique_id_suffix or key}`."""


def _read(kind: str, field: str) -> Callable[[NinaData], bool | None]:
    """One flag off one equipment model, `None` while the device is absent."""
    def value(data: NinaData) -> bool | None:
        device = getattr(data.snapshot, kind)
        return None if device is None else getattr(device, field)

    return value


def _supports(kind: str, field: str) -> Callable[[NinaData], bool]:
    def supported(data: NinaData) -> bool:
        device = getattr(data.snapshot, kind)
        return device is not None and bool(getattr(device, field))

    return supported


def _channel_key(channel: SwitchChannelModel) -> str:
    """Keyed on the channel's own `Id`, so a channel the driver adds later does
    not renumber the entities already registered."""
    return f"switch_channel_{channel.index}"


def _guider_running(data: NinaData) -> bool | None:
    """Every guider state but `Stopped` is guiding in progress.

    `Looping`, `Calibrating` and `LostLock` are all a guider that has been
    started and has not been stopped; only `Stopped` is off.
    """
    guider = data.snapshot.guider
    state = guider.state if guider is not None else None
    return None if state is None else state != "Stopped"


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
    """Never forces a calibration: an existing one is worth keeping, and
    recalibrating costs the settle as well as the frames it spans."""
    if on:
        await client.start_guiding(force_calibration=False)
    else:
        await client.stop_guiding()


async def _set_cooler(client: NinaClientV2, data: NinaData, on: bool) -> None:
    camera = data.snapshot.camera
    setpoint = camera.target_temperature if camera is not None else None
    if on and setpoint is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="no_cooling_setpoint"
        )
    # The setpoint is unused on the way down, where /warm takes only a ramp.
    await client.set_cooler(on, setpoint if setpoint is not None else 0.0)


DESCRIPTIONS: tuple[NinaSwitchDescription, ...] = (
    NinaSwitchDescription(
        key="guider",
        unique_id_suffix="guider_switch",
        # The guider device's one function, so it takes the device's own name.
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
        value=_read("camera", "cooler_on"),
        command=_set_cooler,
    ),
    NinaSwitchDescription(
        key="camera_dew_heater",
        translation_key="camera_dew_heater",
        kind="camera",
        value=_read("camera", "dew_heater_on"),
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
        # Session-scoped, and the endpoint answers whether or not the plugin is
        # installed, so it hangs off the hub and always exists.
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
        value=_read("rotator", "reverse"),
        command=_toggle("set_rotator_reverse"),
    ),
    # Spec-derived and untested against hardware (§5.3.1): a bare field read,
    # and `verified=False`.
    NinaSwitchDescription(
        key="dome_following",
        translation_key="dome_following",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        value=_read("dome", "following"),
        command=_toggle("set_dome_follow"),
    ),
)


class NinaSwitch(NinaEntity, SwitchEntity):
    """One descriptor: read from the snapshot, written through the client."""

    entity_description: NinaSwitchDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaSwitchDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value(self.coordinator.data)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(False)

    async def _send(self, on: bool) -> None:
        try:
            await self.entity_description.command(
                self.coordinator.client, self.coordinator.data, on
            )
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the command: {exc}") from exc
        await self.coordinator.async_request_refresh()


class NinaSwitchChannel(NinaEntity, SwitchEntity):
    """One binary channel of the N.I.N.A. switch device.

    The on and off values are the channel's own range ends, held from creation:
    they are capability metadata rather than readings, so they survive the
    device disconnecting, and `SwitchChannelModel.binary` has already proved
    both are present.
    """

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        channel: SwitchChannelModel,
    ) -> None:
        super().__init__(
            coordinator, entry, _channel_key(channel), kind="switch_device"
        )
        self._index = channel.index
        self._off_value = channel.minimum
        self._on_value = channel.maximum
        # Named by the driver, so there is no translation key to name it by.
        self._attr_name = channel.name

    @property
    def _channel(self) -> SwitchChannelModel | None:
        device = self.coordinator.data.snapshot.switch_device
        channels = device.channels if device is not None else ()
        return next((c for c in channels if c.index == self._index), None)

    @property
    def is_on(self) -> bool | None:
        channel = self._channel
        value = channel.value if channel is not None else None
        return None if value is None else value == self._on_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._send(self._on_value)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._send(self._off_value)

    async def _send(self, value: float) -> None:
        try:
            await self.coordinator.client.set_switch_value(self._index, value)
        except NinaError as exc:
            raise HomeAssistantError(f"N.I.N.A. refused the command: {exc}") from exc
        await self.coordinator.async_request_refresh()


def _observed(data: NinaData, description: NinaSwitchDescription) -> bool:
    """The device has been seen, and reports the capability the switch drives."""
    if description.kind is not None and getattr(data.snapshot, description.kind) is None:
        return False
    return description.supported is None or description.supported(data)


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
        Assistant started still gets its entities (Gold `dynamic-devices`), and
        so does a capability that only appears once the driver is up. A slot
        never returns to `None`, so nothing is ever removed here.
        """
        descriptions = [
            description
            for description in DESCRIPTIONS
            if description.key not in added
            and _observed(coordinator.data, description)
        ]
        device = coordinator.data.snapshot.switch_device
        channels = [
            channel
            for channel in (device.channels if device is not None else ())
            if channel.binary
            and channel.writable
            and _channel_key(channel) not in added
        ]
        if not descriptions and not channels:
            return
        added.update(description.key for description in descriptions)
        added.update(_channel_key(channel) for channel in channels)
        async_add_entities(
            [NinaSwitch(coordinator, entry, d) for d in descriptions]
            + [NinaSwitchChannel(coordinator, entry, c) for c in channels]
        )

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

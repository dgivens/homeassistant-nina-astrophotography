"""The shared entity base. Entity names derive from their device."""

from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity, EntityDescription
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api.errors import NinaError
from .api.models import SwitchChannelModel
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .device import channel_key, channel_name, channel_of, device_identifiers


@contextmanager
def refusals_raised() -> Iterator[None]:
    """Re-raise `NinaError` as `HomeAssistantError`.

    `NinaError` subclasses `Exception` alone, to keep the API layer free of
    Home Assistant, and Home Assistant reports any other exception escaping a
    command as an integration defect.
    """
    try:
        yield
    except NinaError as exc:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="command_failed",
            translation_placeholders={"error": str(exc)},
        ) from exc


@dataclass(frozen=True, kw_only=True)
class NinaEntityDescription(EntityDescription):
    """What every descriptor carries besides how to read it.

    `kind` names the child device; `None` puts it on the hub. `verified` is
    False only for the dome, which no hardware has validated.
    """

    kind: str | None
    verified: bool = True
    attributes: Callable[[NinaData], Mapping[str, Any]] | None = None
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`, so an upgraded entity keeps
    its registry row. `unique_id` is `{entry_id}_{unique_id_suffix or key}`."""


class NinaEntity(CoordinatorEntity[NinaCoordinator]):
    """Base for every N.I.N.A. entity.

    `kind` names the equipment the entity belongs to; `None` puts it on the
    hub. Only the device's identifiers are claimed; `device.async_sync_devices`
    writes its metadata.
    """

    _attr_has_entity_name = True

    # Keeps an entity reporting its own device's state available while down.
    _survives_disconnect = False

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        key: str,
        kind: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers=device_identifiers(entry.entry_id, kind)
        )

    @property
    def available(self) -> bool:
        """The rig is reachable and, for equipment, connected."""
        if not super().available:
            return False
        if self._kind is None or self._survives_disconnect:
            return True
        device = getattr(self.coordinator.data.snapshot, self._kind)
        return device is not None and device.connected

    async def _async_send(self, command: Awaitable[None]) -> None:
        """Send a command, then poll: its response confirms nothing."""
        with refusals_raised():
            await command
        await self.coordinator.async_request_refresh()


class NinaDescribedEntity(NinaEntity):
    """Base for one descriptor's entity."""

    entity_description: NinaEntityDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaEntityDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        build = self.entity_description.attributes
        return None if build is None else build(self.coordinator.data)


class NinaChannelEntity(NinaEntity):
    """Base for one channel of the N.I.N.A. switch device, keyed on its `Id`
    and named by the driver.
    """

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        channel: SwitchChannelModel,
    ) -> None:
        super().__init__(coordinator, entry, channel_key(channel), kind="switch_device")
        self._index = channel.index
        self._attr_name = channel_name(channel)

    @property
    def channel(self) -> SwitchChannelModel | None:
        """This channel in the newest snapshot; `None` once no longer reported."""
        return channel_of(self.coordinator.data, self._index)

    @property
    def channel_value(self) -> float | None:
        """`Value`, never `TargetValue`, which is only what it was asked for."""
        channel = self.channel
        return None if channel is None else channel.value

    @property
    def available(self) -> bool:
        """Unavailable once the driver stops reporting the channel, though the
        switch device is still connected.
        """
        return super().available and self.channel is not None

    async def _async_set_channel(self, value: float) -> None:
        if self.channel is None:
            # The API answers `Success: true` to a `set` for a missing index.
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="channel_gone",
                translation_placeholders={
                    "channel": self._attr_name or str(self._index)
                },
            )
        await self._async_send(
            self.coordinator.client.set_switch_value(self._index, value)
        )


@callback
def async_add_observed(
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
    candidates: Callable[[NinaData], Iterable[tuple[str, Callable[[], Entity]]]],
) -> None:
    """Add each entity once `candidates` first offers it, now or on any later
    publish, so equipment connected hours after setup still gets its entities.

    `candidates` yields `(key, build)` for everything currently observed;
    `build` runs once per key.
    """
    coordinator = entry.runtime_data.coordinator
    added: set[str] = set()

    @callback
    def add() -> None:
        new = [
            (key, build)
            for key, build in candidates(coordinator.data)
            if key not in added
        ]
        if not new:
            return
        added.update(key for key, _ in new)
        async_add_entities([build() for _, build in new])

    add()
    entry.async_on_unload(coordinator.async_add_listener(add))

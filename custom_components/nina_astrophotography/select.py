"""Selects: the options come from the wire, one per device.

**`TrackingModes` and `AvailableFilters` are per-device**, so both option lists
are read off the model. A hardcoded list offers rates a mount does not have and
filters a wheel does not carry.

**The tracking index is the API's own enum, never the position in the options
list.** `mode` is `0 Sidereal, 1 Lunar, 2 Solar, 3 King, 4 Stopped`, and a mount
that offers no King — this one — reports four modes with `Stopped` third.
Indexing the list would start King tracking on a mount asked to stop. The
spec spells the first mode `Siderial`; the wire spells it `Sidereal`, and the
wire is what the options carry.

Neither select confirms itself from the command response (§3.5): a filter change
takes seconds, and the state is the next poll's reading.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.v2.client import NinaClientV2
from .const import DOMAIN, TrackingMode
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaSelectDescription(SelectEntityDescription):
    """A select, plus how to read its options, its current one, and set it.

    `select` receives the option and the option list as it stands, because the
    wire wants an index and only the list can supply one.

    **A 1.4.5 entity that survives keeps its 1.4.5 `unique_id`**, through
    `unique_id_suffix` where the new `key` reads better than the old one. Home
    Assistant keys the registry on `unique_id`, so changing it mints a fresh
    entity and strands the old row as `unavailable`.
    """

    choices: Callable[[NinaData], tuple[str, ...]]
    current: Callable[[NinaData], str | None]
    select: Callable[[NinaClientV2, str, list[str]], Awaitable[None]]
    kind: str
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`. `unique_id` is
    `{entry_id}_{unique_id_suffix or key}`."""


def _read(kind: str, field: str):
    """One field off one equipment model, empty while the device is absent."""
    def value(data: NinaData):
        device = getattr(data.snapshot, kind)
        return None if device is None else getattr(device, field)

    return value


def _options(kind: str, field: str) -> Callable[[NinaData], tuple[str, ...]]:
    def value(data: NinaData) -> tuple[str, ...]:
        device = getattr(data.snapshot, kind)
        return () if device is None else getattr(device, field)

    return value


async def _set_tracking_mode(
    client: NinaClientV2, option: str, options: list[str]
) -> None:
    """`mode` is the API's enum value, which the option's position is not."""
    try:
        mode = TrackingMode[option.upper()]
    except KeyError:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_tracking_mode",
            translation_placeholders={"option": option},
        ) from None
    await client.set_tracking_mode(mode.value)


async def _change_filter(client: NinaClientV2, option: str, options: list[str]) -> None:
    """`filterId` is the filter's slot, which is its position in the wheel's own
    `AvailableFilters` — the list the wire reports in slot order."""
    await client.change_filter(options.index(option))


DESCRIPTIONS: tuple[NinaSelectDescription, ...] = (
    NinaSelectDescription(
        key="mount_tracking_rate",
        translation_key="mount_tracking_rate",
        unique_id_suffix="tracking_rate_select",
        kind="mount",
        # The ACTUAL rate, not the last one commanded (§5.2.3). `Stopped` is one
        # of the rates, which is why this replaces `binary_sensor.mount_tracking`.
        choices=_options("mount", "tracking_modes"),
        current=_read("mount", "tracking_mode"),
        select=_set_tracking_mode,
    ),
    NinaSelectDescription(
        key="filter",
        translation_key="filter",
        unique_id_suffix="filterwheel_select",
        kind="filter_wheel",
        choices=_options("filter_wheel", "available_filters"),
        current=_read("filter_wheel", "selected_filter"),
        select=_change_filter,
    ),
)


class NinaSelect(NinaEntity, SelectEntity):
    """One descriptor: read from the snapshot, written through the client."""

    entity_description: NinaSelectDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaSelectDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description

    @property
    def options(self) -> list[str]:
        return list(self.entity_description.choices(self.coordinator.data))

    @property
    def current_option(self) -> str | None:
        # A reading outside the option list reads `unknown` rather than being
        # offered as an option Home Assistant would then log a warning about.
        option = self.entity_description.current(self.coordinator.data)
        return option if option in self.options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.entity_description.select(
                self.coordinator.client, option, self.options
            )
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
            NinaSelect(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and getattr(coordinator.data.snapshot, description.kind) is not None
        ]
        if not new:
            return
        added.update(select.entity_description.key for select in new)
        async_add_entities(new)

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

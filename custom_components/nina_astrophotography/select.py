"""Selects, whose options are the device's own `TrackingModes` and
`AvailableFilters`.

**The value sent is never the option's position in the list.** Tracking takes
the API's enum (`0 Sidereal … 3 King, 4 Stopped`), and a mount without King
lists `Stopped` fourth; a filter change takes the wheel's slot id. The spec
spells `Siderial`; the options carry the wire's `Sidereal`.
"""

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
from .device import observed, read_field
from .entity import NinaEntity

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaSelectDescription(SelectEntityDescription):
    """A select, plus how to read its options, its current one, and set it.

    `select` gets the snapshot too, to map the option to the number sent.
    """

    choices: Callable[[NinaData], tuple[str, ...]]
    current: Callable[[NinaData], str | None]
    select: Callable[[NinaClientV2, str, NinaData], Awaitable[None]]
    kind: str
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`, so an upgraded entity keeps
    its registry row. `unique_id` is `{entry_id}_{unique_id_suffix or key}`."""


def _options(kind: str, field: str) -> Callable[[NinaData], tuple[str, ...]]:
    def value(data: NinaData) -> tuple[str, ...]:
        device = getattr(data.snapshot, kind)
        return () if device is None else getattr(device, field)

    return value


async def _set_tracking_mode(client: NinaClientV2, option: str, data: NinaData) -> None:
    """Send the API's enum value for the mode."""
    try:
        mode = TrackingMode[option.upper()]
    except KeyError:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_tracking_mode",
            translation_placeholders={"option": option},
        ) from None
    await client.set_tracking_mode(mode.value)


async def _change_filter(client: NinaClientV2, option: str, data: NinaData) -> None:
    """Send the wheel's own slot `Id`, which need not follow list order."""
    wheel = data.snapshot.filter_wheel
    slot = None if wheel is None else wheel.filter_slots.get(option)
    if slot is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="unknown_filter",
            translation_placeholders={"option": option},
        )
    await client.change_filter(slot)


DESCRIPTIONS: tuple[NinaSelectDescription, ...] = (
    NinaSelectDescription(
        key="mount_tracking_rate",
        translation_key="mount_tracking_rate",
        unique_id_suffix="tracking_rate_select",
        kind="mount",
        choices=_options("mount", "tracking_modes"),
        current=read_field("mount", "tracking_mode"),
        select=_set_tracking_mode,
    ),
    NinaSelectDescription(
        key="filter",
        translation_key="filter",
        unique_id_suffix="filterwheel_select",
        kind="filter_wheel",
        choices=_options("filter_wheel", "available_filters"),
        current=read_field("filter_wheel", "selected_filter"),
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
        # A reading outside the options reads `unknown`, which HA accepts.
        option = self.entity_description.current(self.coordinator.data)
        return option if option in self.options else None

    async def async_select_option(self, option: str) -> None:
        try:
            await self.entity_description.select(
                self.coordinator.client, option, self.coordinator.data
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
        """Create the entities whose equipment has now been observed."""
        new = [
            NinaSelect(coordinator, entry, description)
            for description in DESCRIPTIONS
            if description.key not in added
            and observed(coordinator.data, description.kind)
        ]
        if not new:
            return
        added.update(select.entity_description.key for select in new)
        async_add_entities(new)

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

"""Images: the last saved frame, and the livestack.

Nothing is cached: the previous frame under a fresh timestamp would be
indistinguishable from the new one.

The timestamp is the state, and Home Assistant refetches only when it moves.
`image.last_frame` takes it from the newest frame in the fold, and
`image.livestack` from the `STACK-UPDATED` naming its target and filter.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from functools import partial
import logging

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaCommandError, NinaError, NinaNoImageError
from .api.v2.client import NinaClientV2
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaDescribedEntity, NinaEntityDescription, async_add_observed

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0


async def _fetch_livestack(client: NinaClientV2, data: NinaData) -> bytes:
    if data.stack is None:
        raise NinaNoImageError("No live stack")
    return await client.get_livestack_image_bytes(
        data.stack.target, data.stack.filter_name
    )


@dataclass(frozen=True, kw_only=True)
class NinaImageDescription(NinaEntityDescription, ImageEntityDescription):
    """An image, plus where its bytes and its timestamp come from.

    `observed` gates creation: the livestack waits for a stack to report.
    """

    kind: None = None
    stamp: Callable[[NinaData], datetime | None]
    fetch: Callable[[NinaClientV2, NinaData], Awaitable[bytes]]
    observed: Callable[[NinaData], bool] = lambda data: True


DESCRIPTIONS: tuple[NinaImageDescription, ...] = (
    NinaImageDescription(
        key="last_frame",
        translation_key="last_frame",
        unique_id_suffix="latest_image",
        stamp=lambda data: (
            None if data.newest_frame is None else data.newest_frame.date
        ),
        fetch=lambda client, data: client.get_recent_image_bytes(0),
    ),
    NinaImageDescription(
        key="livestack",
        translation_key="livestack",
        stamp=lambda data: None if data.stack is None else data.stack.updated,
        fetch=_fetch_livestack,
        observed=lambda data: data.stack is not None,
        # Which stack is shown: a mono rig has one per filter, and this follows
        # whichever updated last.
        attributes=lambda data: {
            "target": None if data.stack is None else data.stack.target,
            "filter": None if data.stack is None else data.stack.filter_name,
        },
    ),
)


class NinaImage(NinaDescribedEntity, ImageEntity):
    """One descriptor's frame, fetched when something asks for it."""

    entity_description: NinaImageDescription
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaImageDescription,
    ) -> None:
        super().__init__(coordinator, entry, description)
        ImageEntity.__init__(self, hass)

    @property
    def image_last_updated(self) -> datetime | None:
        """The state; `None`, `unknown`, until something is captured."""
        return self.entity_description.stamp(self.coordinator.data)

    async def async_image(self) -> bytes | None:
        """Fetch the bytes: `None` when there is nothing to render, and a raise
        for a real failure, so its cause reaches the log.
        """
        if self.image_last_updated is None:
            return None
        try:
            return await self.entity_description.fetch(
                self.coordinator.client, self.coordinator.data
            )
        except (NinaNoImageError, NinaCommandError) as exc:
            # An empty history, an index no longer held, a dropped stack.
            _LOGGER.debug("N.I.N.A. has no image for %s: %s", self.entity_id, exc)
            return None
        except NinaError as exc:
            raise HomeAssistantError(
                f"Could not fetch {self.entity_id} from N.I.N.A.: {exc}"
            ) from exc


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_observed(
        entry,
        async_add_entities,
        lambda data: (
            (d.key, partial(NinaImage, hass, coordinator, entry, d))
            for d in DESCRIPTIONS
            if d.observed(data)
        ),
    )

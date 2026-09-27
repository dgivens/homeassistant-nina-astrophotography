"""Images: the last saved frame, and the livestack.

Nothing is cached: the previous frame under a fresh timestamp would be
indistinguishable from the new one.

The timestamp is the state, and Home Assistant refetches only when it moves.
`image.last_frame` takes it from the newest frame in the fold, and
`image.livestack` from the `STACK-UPDATED` naming its target and filter.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaCommandError, NinaError, NinaNoImageError
from .api.v2.client import NinaClientV2
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

# A quality makes the route answer JPEG rather than a far larger PNG.
_QUALITY = 85


async def _fetch_last_frame(client: NinaClientV2, _data: NinaData) -> bytes:
    """`/image/{index}` counts oldest-first, so the newest frame is `count - 1`.

    The count is read per call: the fold can lag a frame behind.
    """
    count = await client.get_image_history_count()
    return await client.get_image_bytes(count - 1, quality=_QUALITY)


async def _fetch_livestack(client: NinaClientV2, data: NinaData) -> bytes:
    if data.stack is None:
        raise NinaNoImageError("No live stack")
    return await client.get_livestack_image_bytes(
        data.stack.target, data.stack.filter_name, quality=_QUALITY
    )


@dataclass(frozen=True, kw_only=True)
class NinaImageDescription(ImageEntityDescription):
    """An image, plus where its bytes and its timestamp come from.

    `observed` gates creation: the livestack waits for a stack to report.
    """

    stamp: Callable[[NinaData], datetime | None]
    fetch: Callable[[NinaClientV2, NinaData], Awaitable[bytes]]
    observed: Callable[[NinaData], bool] = lambda data: True
    attributes: Callable[[NinaData], Mapping[str, Any]] | None = None
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`."""


DESCRIPTIONS: tuple[NinaImageDescription, ...] = (
    NinaImageDescription(
        key="last_frame",
        translation_key="last_frame",
        unique_id_suffix="latest_image",
        stamp=lambda data: (
            None if data.newest_frame is None else data.newest_frame.date
        ),
        fetch=_fetch_last_frame,
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


class NinaImage(NinaEntity, ImageEntity):
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
        super().__init__(
            coordinator, entry, description.unique_id_suffix or description.key
        )
        ImageEntity.__init__(self, hass)
        self.entity_description = description

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        build = self.entity_description.attributes
        return None if build is None else build(self.coordinator.data)

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
    added: set[str] = set()

    @callback
    def _add_observed() -> None:
        """Create the images whose source has now been observed."""
        descriptions = [
            description
            for description in DESCRIPTIONS
            if description.key not in added and description.observed(coordinator.data)
        ]
        if not descriptions:
            return
        added.update(description.key for description in descriptions)
        async_add_entities(
            NinaImage(hass, coordinator, entry, description)
            for description in descriptions
        )

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

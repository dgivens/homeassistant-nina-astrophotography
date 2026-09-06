"""Images: the last saved frame, and the accumulating livestack.

Both routes answer HTTP 200 whatever happens — a rendered frame as `image/*`,
a refusal as the JSON envelope — so the client separates them on content type
and raises rather than handing the envelope back as image bytes. Nothing is
cached here: serving the previous frame under a fresh timestamp is worse than
serving nothing, because a dashboard cannot tell the two apart.

The timestamp is the state, and Home Assistant refetches only when it moves.
`image.last_frame` takes it from the newest frame in the fold — never
`utcnow()`, which reports the moment the integration loaded as the moment a
frame was captured — and `image.livestack` from the `STACK-UPDATED` that named
its target and filter.
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
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

# Reads only, and both entities fetch on demand rather than on a schedule.
PARALLEL_UPDATES = 0

# quality is what makes the route answer JPEG; omitted, it renders PNG, which is
# several times the bytes for a stretched preview.
_QUALITY = 85


@dataclass(frozen=True, kw_only=True)
class NinaImageDescription(ImageEntityDescription):
    """An image, plus where its bytes and its timestamp come from.

    `observed` is the §5.2.2 first-sight rule. The last frame exists from the
    start because its identity does not depend on the poll — with no frame
    yet the timestamp is `None` and `async_image` never asks — while the
    livestack pair is only knowable once a stack has reported one.
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
        fetch=lambda client, _data: client.get_image_bytes(0, quality=_QUALITY),
    ),
    NinaImageDescription(
        key="livestack",
        translation_key="livestack",
        stamp=lambda data: None if data.stack is None else data.stack.updated,
        fetch=lambda client, data: client.get_livestack_image_bytes(
            data.stack.target, data.stack.filter_name, quality=_QUALITY
        ),
        observed=lambda data: data.stack is not None,
        # Which stack is on screen. On a mono rig the plugin holds one stack
        # per filter and this entity follows whichever updated last, so
        # without these a dashboard shows an Ha frame and then an SII one with
        # nothing explaining the jump.
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
        """The state. None reads as `unknown` — nothing has been captured."""
        return self.entity_description.stamp(self.coordinator.data)

    async def async_image(self) -> bytes | None:
        """Fetch the bytes.

        Two outcomes, and they must not look alike. A rig with nothing to
        render answers `None` — no frame yet is not an error, and the timestamp
        has already said so. Anything else is a real failure and is RAISED, so
        the cause reaches the log: Home Assistant renders both as the same
        "unable to get image", and a swallowed one leaves a fresh timestamp
        beside a permanently blank card with nothing naming the route, the
        envelope or the reason.
        """
        if self.image_last_updated is None:
            return None
        try:
            return await self.entity_description.fetch(
                self.coordinator.client, self.coordinator.data
            )
        except (NinaNoImageError, NinaCommandError) as exc:
            # Nothing to render, or the handler declined — an empty history,
            # an index it no longer holds, a stack the plugin has dropped. All
            # ordinary, and not worth a traceback on a dashboard render.
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
        """Create the images whose source the snapshot now carries.

        Re-run on every publish, so a stack that starts hours after Home
        Assistant did still gets its entity (Gold `dynamic-devices`).
        """
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

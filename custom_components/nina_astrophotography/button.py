"""Buttons: the one-shot commands, each a single endpoint.

**A press awaits the HTTP round trip and nothing more.** N.I.N.A. issues no
operation id, so a completion event cannot be tied to the press; the result
shows in the entities that report it, on the next poll.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.errors import NinaError
from .api.v2.client import NinaClientV2
from .const import DOMAIN
from .coordinator import NinaConfigEntry, NinaCoordinator
from .device import observed
from .entity import NinaEntity

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaButtonDescription(ButtonEntityDescription):
    """A button, plus the command it sends.

    `kind` names the child device; `None` puts it on the hub. `verified` is
    False only for the dome, which no hardware has validated.
    """

    press: Callable[[NinaClientV2], Awaitable[None]]
    kind: str | None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`, so an upgraded entity keeps
    its registry row. `unique_id` is `{entry_id}_{unique_id_suffix or key}`."""


DESCRIPTIONS: tuple[NinaButtonDescription, ...] = (
    NinaButtonDescription(
        key="mount_park",
        translation_key="mount_park",
        unique_id_suffix="btn_mount_park",
        kind="mount",
        press=lambda client: client.park_mount(),
    ),
    NinaButtonDescription(
        key="mount_unpark",
        translation_key="mount_unpark",
        unique_id_suffix="btn_mount_unpark",
        kind="mount",
        press=lambda client: client.unpark_mount(),
    ),
    NinaButtonDescription(
        key="mount_find_home",
        translation_key="mount_find_home",
        unique_id_suffix="btn_mount_find_home",
        kind="mount",
        press=lambda client: client.find_home(),
    ),
    NinaButtonDescription(
        key="camera_abort_exposure",
        translation_key="camera_abort_exposure",
        unique_id_suffix="btn_camera_abort",
        kind="camera",
        press=lambda client: client.abort_capture(),
    ),
    NinaButtonDescription(
        key="focuser_auto_focus",
        translation_key="focuser_auto_focus",
        unique_id_suffix="btn_auto_focus",
        kind="focuser",
        press=lambda client: client.auto_focus(),
    ),
    NinaButtonDescription(
        key="sequence_start",
        translation_key="sequence_start",
        unique_id_suffix="btn_sequence_start",
        kind=None,
        press=lambda client: client.start_sequence(),
    ),
    NinaButtonDescription(
        key="sequence_stop",
        translation_key="sequence_stop",
        unique_id_suffix="btn_sequence_stop",
        kind=None,
        press=lambda client: client.stop_sequence(),
    ),
    NinaButtonDescription(
        key="guider_clear_calibration",
        translation_key="guider_clear_calibration",
        entity_category=EntityCategory.CONFIG,
        kind="guider",
        press=lambda client: client.clear_guider_calibration(),
    ),
    # From the spec alone; no hardware has validated the dome.
    NinaButtonDescription(
        key="dome_open",
        translation_key="dome_open",
        unique_id_suffix="btn_dome_open",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.open_dome(),
    ),
    NinaButtonDescription(
        key="dome_close",
        translation_key="dome_close",
        unique_id_suffix="btn_dome_close",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.close_dome(),
    ),
    NinaButtonDescription(
        key="dome_park",
        translation_key="dome_park",
        unique_id_suffix="btn_dome_park",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.park_dome(),
    ),
    NinaButtonDescription(
        key="dome_home",
        translation_key="dome_home",
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.home_dome(),
    ),
)


class NinaButton(NinaEntity, ButtonEntity):
    """One descriptor's command, sent and not waited on."""

    entity_description: NinaButtonDescription

    def __init__(
        self,
        coordinator: NinaCoordinator,
        entry: NinaConfigEntry,
        description: NinaButtonDescription,
    ) -> None:
        super().__init__(
            coordinator,
            entry,
            description.unique_id_suffix or description.key,
            kind=description.kind,
        )
        self.entity_description = description

    async def async_press(self) -> None:
        try:
            await self.entity_description.press(self.coordinator.client)
        except NinaError as exc:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(exc)},
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
        """Create the buttons whose equipment has now been observed."""
        descriptions = [
            description
            for description in DESCRIPTIONS
            if description.key not in added
            and observed(coordinator.data, description.kind)
        ]
        if not descriptions:
            return
        added.update(description.key for description in descriptions)
        async_add_entities(
            NinaButton(coordinator, entry, description) for description in descriptions
        )

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

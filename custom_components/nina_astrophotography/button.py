"""Buttons: the one-shot commands, each of which is a single endpoint.

**A press awaits the HTTP round trip and nothing more** (§3.5). Autofocus and a
mount park take minutes, but v2 issues no request id, so a completion event
cannot be attributed to the caller that started it; waiting would block the
service call on something it cannot identify. The result arrives as the state of
the entities that report it — `binary_sensor.<instance>_mount_at_park`,
`sensor.<instance>_focuser_position` — on the next poll.

**A command's own response confirms nothing**, so nothing is read back here and
no state is assumed. `guider/clear-calibration` is one of the seven handlers
that assign `Success` from a driver boolean and answer
`Success: false, Error: "", StatusCode: 200` on a call that worked; the client's
envelope classification already keys on `StatusCode` and `Error` rather than
`Success` alone, so that is a normal return here rather than a special case.

Guiding is not on this platform: it is a state that can be read back, so it is
`switch.<instance>_guider` (§5.2.3).
"""
from __future__ import annotations

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
from .coordinator import NinaConfigEntry, NinaCoordinator, NinaData
from .entity import NinaEntity

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaButtonDescription(ButtonEntityDescription):
    """A button, plus the command it sends.

    `kind` names the child device the entity hangs off (§5.1); `None` puts it on
    the hub. `verified` is False only for the dome, which cannot be validated
    against hardware — a test asserts every dome descriptor carries the marker.

    **A 1.4.5 entity that survives keeps its 1.4.5 `unique_id`**, through
    `unique_id_suffix`. Home Assistant keys the registry on `unique_id`, so
    changing it mints a fresh entity and strands the old row as `unavailable`.
    """

    press: Callable[[NinaClientV2], Awaitable[None]]
    kind: str | None
    verified: bool = True
    unique_id_suffix: str | None = None
    """The 1.4.5 key, where it differs from `key`. `unique_id` is
    `{entry_id}_{unique_id_suffix or key}`."""


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
    # Sequence control is rig-scoped, so it hangs off the hub.
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
        entity_category=EntityCategory.DIAGNOSTIC,
        kind="guider",
        press=lambda client: client.clear_guider_calibration(),
    ),
    # Spec-derived and untested against hardware (§5.3.1): `verified=False`.
    NinaButtonDescription(
        key="dome_open",
        translation_key="dome_open",
        unique_id_suffix="btn_dome_open",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.open_dome(),
    ),
    NinaButtonDescription(
        key="dome_close",
        translation_key="dome_close",
        unique_id_suffix="btn_dome_close",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.close_dome(),
    ),
    NinaButtonDescription(
        key="dome_park",
        translation_key="dome_park",
        unique_id_suffix="btn_dome_park",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        kind="dome",
        verified=False,
        press=lambda client: client.park_dome(),
    ),
    NinaButtonDescription(
        key="dome_home",
        translation_key="dome_home",
        entity_category=EntityCategory.DIAGNOSTIC,
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


def _observed(data: NinaData, description: NinaButtonDescription) -> bool:
    """The device this button commands has been seen at least once."""
    return (
        description.kind is None
        or getattr(data.snapshot, description.kind) is not None
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NinaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    added: set[str] = set()

    @callback
    def _add_observed() -> None:
        """Create the buttons whose equipment the snapshot now carries.

        Re-run on every publish, so equipment that connects hours after Home
        Assistant started still gets its buttons (Gold `dynamic-devices`). A
        slot never returns to `None`, so nothing is ever removed here.
        """
        descriptions = [
            description
            for description in DESCRIPTIONS
            if description.key not in added
            and _observed(coordinator.data, description)
        ]
        if not descriptions:
            return
        added.update(description.key for description in descriptions)
        async_add_entities(
            NinaButton(coordinator, entry, description)
            for description in descriptions
        )

    _add_observed()
    entry.async_on_unload(coordinator.async_add_listener(_add_observed))

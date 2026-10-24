"""Buttons: the one-shot commands, each a single endpoint.

**A press awaits the HTTP round trip and nothing more.** N.I.N.A. issues no
operation id, so a completion event cannot be tied to the press; the result
shows in the entities that report it, on the next poll.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import partial

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api.v2.client import NinaClientV2
from .coordinator import NinaConfigEntry
from .device import refused_while_following, refused_while_unsafe, supports
from .entity import (
    NinaDescribedEntity,
    NinaEntityDescription,
    async_add_observed,
    refusals_raised,
    usable,
)

# One in-flight command per platform: these move hardware.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class NinaButtonDescription(NinaEntityDescription, ButtonEntityDescription):
    """A button, plus the command it sends."""

    press: Callable[[NinaClientV2], Awaitable[None]]


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
    NinaButtonDescription(
        key="dome_open",
        translation_key="dome_open",
        unique_id_suffix="btn_dome_open",
        kind="dome",
        supported=supports("dome", "can_set_shutter"),
        refusal=refused_while_unsafe,
        press=lambda client: client.open_dome(),
    ),
    NinaButtonDescription(
        key="dome_close",
        translation_key="dome_close",
        unique_id_suffix="btn_dome_close",
        kind="dome",
        supported=supports("dome", "can_set_shutter"),
        press=lambda client: client.close_dome(),
    ),
    NinaButtonDescription(
        key="dome_park",
        translation_key="dome_park",
        unique_id_suffix="btn_dome_park",
        kind="dome",
        supported=supports("dome", "can_park"),
        # N.I.N.A. closes the shutter too, after homing when the profile's
        # `FindHomeBeforePark` asks for it.
        press=lambda client: client.park_dome(),
    ),
    NinaButtonDescription(
        key="dome_home",
        translation_key="dome_home",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        kind="dome",
        supported=supports("dome", "can_find_home"),
        refusal=refused_while_following,
        press=lambda client: client.home_dome(),
    ),
)


class NinaButton(NinaDescribedEntity, ButtonEntity):
    """One descriptor's command, sent and not waited on."""

    entity_description: NinaButtonDescription

    async def async_press(self) -> None:
        self._raise_if_refused()
        with refusals_raised():
            await self.entity_description.press(self.coordinator.client)


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
            (d.key, partial(NinaButton, coordinator, entry, d))
            for d in DESCRIPTIONS
            if usable(data, d)
        ),
    )

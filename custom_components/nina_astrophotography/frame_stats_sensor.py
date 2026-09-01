"""Per-frame image statistics sensors for N.I.N.A. Astrophotography.

These sensors are backed by NinaFrameStatisticsStore (populated in real-time
from IMAGE-SAVE WebSocket events) rather than the polling coordinator.
They update instantly on every captured frame rather than waiting for the
next poll cycle.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .device import HUB, device_info_for
from .frame_statistics import NinaFrameStatisticsStore

_LOGGER = logging.getLogger(__name__)

@dataclass
class NinaFrameSensorDescription(SensorEntityDescription):
    """Sensor description with a callable that extracts value from the store."""
    value_fn: Any = None          # (store: NinaFrameStatisticsStore) -> Any
    extra_attrs_fn: Any = None    # (store) -> dict | None  — optional extra state attrs


# ── Sensor descriptors ────────────────────────────────────────────────────────

FRAME_SENSOR_DESCRIPTIONS: list[NinaFrameSensorDescription] = [

    # ── Latest frame ──────────────────────────────────────────────────────────
    NinaFrameSensorDescription(
        key="frame_last_hfr",
        name="Last Frame HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points-circle",
        value_fn=lambda s: s.last_hfr,
    ),
    NinaFrameSensorDescription(
        key="frame_last_hfr_std_dev",
        name="Last Frame HFR Std Dev",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sigma",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.hfr_std_dev if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_stars",
        name="Last Frame Stars",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-shooting",
        value_fn=lambda s: s.last_stars,
    ),
    NinaFrameSensorDescription(
        key="frame_last_mean_adu",
        name="Last Frame Mean ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-histogram",
        value_fn=lambda s: s.last_mean_adu,
    ),
    NinaFrameSensorDescription(
        key="frame_last_median_adu",
        name="Last Frame Median ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.median_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_min_adu",
        name="Last Frame Min ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-collapse-down",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.min_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_max_adu",
        name="Last Frame Max ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-collapse-up",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.max_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_std_dev_adu",
        name="Last Frame ADU Std Dev",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sigma",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.std_dev_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_filter",
        name="Last Frame Filter",
        icon="mdi:filter",
        value_fn=lambda s: s.last_filter,
    ),
    NinaFrameSensorDescription(
        key="frame_last_exposure",
        name="Last Frame Exposure",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_fn=lambda s: s.last_exposure,
    ),
    NinaFrameSensorDescription(
        key="frame_last_rms",
        name="Last Frame Guide RMS",
        icon="mdi:crosshairs",
        value_fn=lambda s: s.last_rms,
    ),
    NinaFrameSensorDescription(
        key="frame_last_target",
        name="Last Frame Target",
        icon="mdi:star-circle",
        value_fn=lambda s: s.last_target,
    ),

    # ── Rolling window (last 10 frames) ───────────────────────────────────────
    NinaFrameSensorDescription(
        key="frame_rolling_avg_hfr",
        name="Rolling Avg HFR (10)",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line",
        value_fn=lambda s: s.rolling_avg_hfr,
    ),
    NinaFrameSensorDescription(
        key="frame_rolling_avg_stars",
        name="Rolling Avg Stars (10)",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line-variant",
        value_fn=lambda s: s.rolling_avg_stars,
    ),
    NinaFrameSensorDescription(
        key="frame_rolling_avg_adu",
        name="Rolling Avg ADU (10)",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-line-stacked",
        value_fn=lambda s: s.rolling_avg_adu,
    ),

    # ── Session aggregates ────────────────────────────────────────────────────
    NinaFrameSensorDescription(
        key="frame_session_count",
        name="Session Frame Count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:image-multiple",
        value_fn=lambda s: s.session_frame_count,
    ),
    NinaFrameSensorDescription(
        key="frame_session_integration",
        name="Session Integration Time",
        native_unit_of_measurement="min",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:clock-plus-outline",
        value_fn=lambda s: s.total_integration_minutes,
    ),
    NinaFrameSensorDescription(
        key="frame_session_avg_hfr",
        name="Session Avg HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sigma",
        value_fn=lambda s: s.session_avg_hfr,
    ),
    NinaFrameSensorDescription(
        key="frame_session_min_hfr",
        name="Session Best HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-check",
        value_fn=lambda s: s.session_min_hfr,
    ),
    NinaFrameSensorDescription(
        key="frame_session_max_hfr",
        name="Session Worst HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-alert",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.session_max_hfr,
    ),
    NinaFrameSensorDescription(
        key="frame_session_avg_stars",
        name="Session Avg Stars",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:counter",
        value_fn=lambda s: s.session_avg_stars,
    ),

    # ── HFR trend ─────────────────────────────────────────────────────────────
    NinaFrameSensorDescription(
        key="frame_hfr_trend",
        name="HFR Trend",
        icon="mdi:trending-up",
        value_fn=lambda s: s.hfr_trend,
    ),
    NinaFrameSensorDescription(
        key="frame_hfr_trend_delta",
        name="HFR Trend Delta",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:delta",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Negative = improving (HFR got smaller), positive = degrading
        value_fn=lambda s: s.hfr_trend_delta,
    ),

    # ── Per-filter frame counts (stored as extra attrs on a summary sensor) ───
    NinaFrameSensorDescription(
        key="frame_per_filter_counts",
        name="Frames Per Filter",
        icon="mdi:filter-multiple",
        # Primary state = total frames; per-filter breakdown in extra attributes
        value_fn=lambda s: s.session_frame_count,
        extra_attrs_fn=lambda s: {
            **{f"filter_{k.lower().replace(' ', '_')}": v
               for k, v in s.frames_per_filter.items()},
            "frames_per_filter": s.frames_per_filter,
            "total_integration_minutes": s.total_integration_minutes,
        },
    ),

    # ── Sparkline data sensor (used by the Lovelace card) ─────────────────────
    NinaFrameSensorDescription(
        key="frame_sparkline_data",
        name="Frame Sparkline Data",
        icon="mdi:chart-areaspline",
        entity_category=EntityCategory.DIAGNOSTIC,
        # Primary state = frame count; sparklines in extra attributes
        value_fn=lambda s: s.session_frame_count,
        extra_attrs_fn=lambda s: {
            "hfr_sparkline": s.hfr_sparkline(30),
            "stars_sparkline": s.stars_sparkline(30),
            "adu_sparkline": s.adu_sparkline(30),
            "filter_timeline": s.filter_timeline(30),
        },
    ),
]


# ── Entity class ──────────────────────────────────────────────────────────────

class NinaFrameStatisticsSensor(SensorEntity, RestoreEntity):
    """A sensor that updates from the NinaFrameStatisticsStore.

    Uses RestoreEntity so the last known value is available immediately after
    an HA restart, before the next IMAGE-SAVE event arrives.
    """

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True

    entity_description: NinaFrameSensorDescription

    def __init__(
        self,
        store: NinaFrameStatisticsStore,
        description: NinaFrameSensorDescription,
        entry_id: str,
    ) -> None:
        self._store = store
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info_for(entry_id, HUB)
        self._attr_should_poll = False  # push-driven, not polled
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Register with the store when entity is added."""
        await super().async_added_to_hass()
        self._store.add_update_listener(self._on_store_update)
        # Restore last known state on startup
        last_state = await self.async_get_last_state()
        if last_state and last_state.state not in ("unknown", "unavailable"):
            _LOGGER.debug(
                "Restored %s = %s", self.entity_description.key, last_state.state
            )

    async def async_will_remove_from_hass(self) -> None:
        """Deregister from the store on removal."""
        self._store.remove_update_listener(self._on_store_update)

    def _on_store_update(self) -> None:
        """Called by the store on every new frame — schedule a state write."""
        self.schedule_update_ha_states()

    @property
    def native_value(self) -> Any:
        try:
            return self.entity_description.value_fn(self._store)
        except Exception:  # noqa: BLE001
            return None

    @property
    def extra_state_attributes(self) -> dict | None:
        if self.entity_description.extra_attrs_fn:
            try:
                return self.entity_description.extra_attrs_fn(self._store)
            except Exception:  # noqa: BLE001
                return None
        return None


# ── Platform setup ────────────────────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    store: NinaFrameStatisticsStore = hass.data[DOMAIN][entry.entry_id]["frame_store"]
    async_add_entities(
        NinaFrameStatisticsSensor(store, description, entry.entry_id)
        for description in FRAME_SENSOR_DESCRIPTIONS
    )

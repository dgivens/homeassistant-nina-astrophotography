"""Per-frame image statistics sensors for N.I.N.A. Astrophotography.

These sensors are backed by NinaFrameStatisticsStore (populated in real-time
from IMAGE-SAVE WebSocket events) rather than the polling coordinator.
They update instantly on every captured frame rather than waiting for the
next poll cycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .frame_statistics import NinaFrameStatisticsStore


DEVICE_INFO = {
    "manufacturer": "Nighttime Imaging 'N' Astronomy",
    "model": "Advanced API v2 — Frame Statistics",
}


@dataclass
class NinaFrameSensorDescription(SensorEntityDescription):
    """Sensor description with a callable that extracts value from the store."""
    value_fn: Any = None          # (store: NinaFrameStatisticsStore) -> Any
    extra_attrs_fn: Any = None    # (store) -> dict | None  — optional extra state attrs
    # Show the pre-restart value until this entry's first store update. Only
    # for last-frame sensors: a restored session total would read stale and
    # then jump when the next frame lands.
    restore: bool = False


# ── Sensor descriptors ────────────────────────────────────────────────────────

FRAME_SENSOR_DESCRIPTIONS: list[NinaFrameSensorDescription] = [

    # ── Latest frame ──────────────────────────────────────────────────────────
    NinaFrameSensorDescription(
        key="frame_last_hfr",
        restore=True,
        name="Last Frame HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points-circle",
        value_fn=lambda s: s.last_hfr,
    ),
    NinaFrameSensorDescription(
        key="frame_last_hfr_std_dev",
        restore=True,
        name="Last Frame HFR Std Dev",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sigma",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.hfr_std_dev if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_stars",
        restore=True,
        name="Last Frame Stars",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-shooting",
        value_fn=lambda s: s.last_stars,
    ),
    NinaFrameSensorDescription(
        key="frame_last_mean_adu",
        restore=True,
        name="Last Frame Mean ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-histogram",
        value_fn=lambda s: s.last_mean_adu,
    ),
    NinaFrameSensorDescription(
        key="frame_last_median_adu",
        restore=True,
        name="Last Frame Median ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.median_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_min_adu",
        restore=True,
        name="Last Frame Min ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-collapse-down",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.min_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_max_adu",
        restore=True,
        name="Last Frame Max ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-collapse-up",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.max_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_std_dev_adu",
        restore=True,
        name="Last Frame ADU Std Dev",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:sigma",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda s: s.latest.std_dev_adu if s.latest else None,
    ),
    NinaFrameSensorDescription(
        key="frame_last_filter",
        restore=True,
        name="Last Frame Filter",
        icon="mdi:filter",
        value_fn=lambda s: s.last_filter,
    ),
    NinaFrameSensorDescription(
        key="frame_last_exposure",
        restore=True,
        name="Last Frame Exposure",
        native_unit_of_measurement="s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_fn=lambda s: s.last_exposure,
    ),
    NinaFrameSensorDescription(
        key="frame_last_rms",
        restore=True,
        name="Last Frame Guide RMS",
        icon="mdi:crosshairs",
        value_fn=lambda s: s.last_rms,
    ),
    NinaFrameSensorDescription(
        key="frame_last_target",
        restore=True,
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

class NinaFrameStatisticsSensor(RestoreSensor):
    """A sensor that updates from the NinaFrameStatisticsStore.

    Sensors whose description sets `restore` show their pre-restart value until
    the store first reports, then drop it for good. The aggregates do not
    restore — the store is rebuilt empty, so they have nothing to recompute
    from.
    """

    entity_description: NinaFrameSensorDescription

    def __init__(
        self,
        store: NinaFrameStatisticsStore,
        description: NinaFrameSensorDescription,
        entry_id: str,
    ) -> None:
        self._store = store
        self._restored: Any = None
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "N.I.N.A. Astrophotography",
            "manufacturer": DEVICE_INFO["manufacturer"],
            "model": DEVICE_INFO["model"],
        }
        self._attr_should_poll = False  # push-driven, not polled
        self._attr_available = True

    async def async_added_to_hass(self) -> None:
        """Register with the store when entity is added."""
        await super().async_added_to_hass()
        # Read the restored value before subscribing: the await yields, and a
        # store update landing in that window would otherwise be undone by an
        # assignment arriving after it.
        if self.entity_description.restore:
            last = await self.async_get_last_sensor_data()
            if last is not None:
                self._restored = last.native_value
        self._store.add_update_listener(self._on_store_update)

    async def async_will_remove_from_hass(self) -> None:
        """Deregister from the store on removal."""
        await super().async_will_remove_from_hass()
        self._store.remove_update_listener(self._on_store_update)

    def _on_store_update(self) -> None:
        """Write the new state.

        Registered in async_added_to_hass, so hass and entity_id are always set.
        """
        # The store has spoken, so the pre-restart value is finished. Dropping
        # it here rather than gating on the frame count matters because reset()
        # zeroes that count at every SEQUENCE-STARTING, which would otherwise
        # bring a value from a previous night back for each new sequence.
        self._restored = None
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        # The store is built empty at setup, so without this the first state
        # write after a restart would be None. Cleared on the first store
        # update, so it applies once.
        if self._restored is not None:
            return self._restored
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

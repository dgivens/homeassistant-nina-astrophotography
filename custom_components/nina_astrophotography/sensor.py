"""Sensors for the N.I.N.A. Astrophotography integration.

Field names follow the Advanced API v2 component schemas (CameraInfo,
MountInfo, FocuserInfo, FWInfo, GuiderInfo, RotatorInfo, DomeInfo,
FlatDeviceInfo, SwitchInfo, WeatherInfo, SafetyMonitorInfo).
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
from homeassistant.const import (
    DEGREE,
    UnitOfLength,
    UnitOfPressure,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NinaDataCoordinator
from .device import device_info_for_key
from .helpers import (
    focal_length,
    image_history,
    image_scale,
    last_image_hfr_arcsec,
    latest_image,
    latest_image_stat,
    pixel_size,
    positive_int,
    readout_mode_name,
    safe,
    safe_datetime,
    safe_float,
    safe_int,
    sequence_current_instruction,
    sequence_progress,
    sequence_state,
    sequence_target,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class NinaSensorDescription(SensorEntityDescription):
    value_fn: Any = None
    attrs_fn: Any = None


SENSOR_DESCRIPTIONS: list[NinaSensorDescription] = [

    # ── Camera ────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="camera_temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: safe_float(d, "camera", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="camera_target_temperature",
        name="Target Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-lines",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "camera", "Response", "TargetTemp"),
    ),
    NinaSensorDescription(
        key="camera_cooler_power",
        name="Cooler Power",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:snowflake",
        value_fn=lambda d: safe_float(d, "camera", "Response", "CoolerPower"),
    ),
    NinaSensorDescription(
        key="camera_gain",
        name="Gain",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:camera-iris",
        # The API reports -1 when the camera cannot report gain.
        value_fn=lambda d: positive_int(d, "camera", "Response", "Gain"),
    ),
    NinaSensorDescription(
        key="camera_offset",
        name="Offset",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:tune",
        value_fn=lambda d: positive_int(d, "camera", "Response", "Offset"),
    ),
    NinaSensorDescription(
        key="camera_status",
        name="Status",
        icon="mdi:camera",
        value_fn=lambda d: safe(d, "camera", "Response", "CameraState"),
    ),
    NinaSensorDescription(
        key="camera_binning",
        name="Binning",
        icon="mdi:grid",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            f"{x}x{y}"
            if (x := safe_int(d, "camera", "Response", "BinX")) is not None
            and (y := safe_int(d, "camera", "Response", "BinY")) is not None
            else None
        ),
    ),
    NinaSensorDescription(
        key="camera_readout_mode",
        name="Readout Mode",
        icon="mdi:download-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            modes[i]
            if isinstance(modes := safe(d, "camera", "Response", "ReadoutModes"), list)
            and (i := safe_int(d, "camera", "Response", "ReadoutMode")) is not None
            and 0 <= i < len(modes)
            else safe_int(d, "camera", "Response", "ReadoutMode")
        ),
    ),
    NinaSensorDescription(
        key="camera_usb_limit",
        name="USB Limit",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:usb",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: positive_int(d, "camera", "Response", "USBLimit"),
    ),
    NinaSensorDescription(
        key="camera_battery",
        name="Battery",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: positive_int(d, "camera", "Response", "Battery"),
    ),
    NinaSensorDescription(
        key="camera_last_download_time",
        name="Last Download Time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "camera", "Response", "LastDownloadTime"),
    ),
    # Static-looking camera fields that are not actually static, and that are
    # worth reading remotely rather than by remoting into the observatory PC.
    NinaSensorDescription(
        key="camera_pixel_size",
        name="Pixel Size",
        native_unit_of_measurement="μm",
        icon="mdi:dots-grid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=pixel_size,
    ),
    NinaSensorDescription(
        key="camera_sensor_type",
        name="Sensor Type",
        icon="mdi:grid",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Per ASCOM ICameraV3 this is only meaningful at bin 1x1, so a colour
        # sensor can report Monochrome once binned — which breaks debayering
        # downstream. Worth being able to check.
        value_fn=lambda d: safe(d, "camera", "Response", "SensorType"),
    ),
    NinaSensorDescription(
        key="camera_bit_depth",
        name="Bit Depth",
        native_unit_of_measurement="bit",
        icon="mdi:numeric",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # A misconfiguration canary: ASI High Speed Mode and some QHY output
        # modes silently drop the camera to 8-bit, which is unrecoverable in
        # the resulting lights. Alert on anything below 16.
        value_fn=lambda d: safe_int(d, "camera", "Response", "BitDepth"),
    ),
    NinaSensorDescription(
        key="camera_readout_mode_lights",
        name="Readout Mode for Lights",
        icon="mdi:download-network-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: readout_mode_name(d, "ReadoutModeForNormalImages"),
    ),
    NinaSensorDescription(
        key="camera_exposure_end_time",
        name="Exposure End Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:timer-outline",
        value_fn=lambda d: safe_datetime(d, "camera", "Response", "ExposureEndTime"),
    ),

    # ── Filter wheel ──────────────────────────────────────────────────────
    NinaSensorDescription(
        key="camera_current_filter",
        name="Current Filter",
        icon="mdi:filter",
        # Reported by the wheel, not the camera.
        value_fn=lambda d: safe(d, "filterwheel", "Response", "SelectedFilter", "Name"),
        # filter_id is what the change-filter service takes.
        attrs_fn=lambda d: {
            "filter_id": safe(d, "filterwheel", "Response", "SelectedFilter", "Id"),
        },
    ),

    # ── Mount ─────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="mount_ra",
        name="RA",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:telescope",
        value_fn=lambda d: safe_float(d, "mount", "Response", "RightAscension", digits=4),
        attrs_fn=lambda d: {
            "formatted": safe(d, "mount", "Response", "RightAscensionString"),
            "degrees": safe_float(d, "mount", "Response", "Coordinates", "RADegrees",
                                  digits=4),
        },
    ),
    NinaSensorDescription(
        key="mount_dec",
        name="Dec",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:telescope",
        value_fn=lambda d: safe_float(d, "mount", "Response", "Declination", digits=4),
        attrs_fn=lambda d: {
            "formatted": safe(d, "mount", "Response", "DeclinationString"),
        },
    ),
    NinaSensorDescription(
        key="mount_altitude",
        name="Altitude",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-circle",
        value_fn=lambda d: safe_float(d, "mount", "Response", "Altitude"),
    ),
    NinaSensorDescription(
        key="mount_azimuth",
        name="Azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass",
        value_fn=lambda d: safe_float(d, "mount", "Response", "Azimuth"),
    ),
    NinaSensorDescription(
        key="mount_sidereal_time",
        name="Sidereal Time",
        native_unit_of_measurement="h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:clock-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "mount", "Response", "SiderealTime", digits=4),
    ),
    NinaSensorDescription(
        key="mount_time_to_meridian_flip",
        name="Time to Meridian Flip",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:swap-horizontal",
        # MountInfo.TimeToMeridianFlip is in hours, matching HoursToMeridianString.
        value_fn=lambda d: safe_float(d, "mount", "Response", "TimeToMeridianFlip",
                                      digits=3),
        attrs_fn=lambda d: {
            "formatted": safe(d, "mount", "Response", "TimeToMeridianFlipString"),
        },
    ),
    NinaSensorDescription(
        key="mount_tracking_mode",
        name="Tracking Mode",
        icon="mdi:orbit",
        value_fn=lambda d: safe(d, "mount", "Response", "TrackingMode"),
    ),
    NinaSensorDescription(
        key="mount_side_of_pier",
        name="Side of Pier",
        icon="mdi:arrow-decision",
        value_fn=lambda d: safe(d, "mount", "Response", "SideOfPier"),
    ),
    NinaSensorDescription(
        key="mount_site_latitude",
        name="Site Latitude",
        native_unit_of_measurement=DEGREE,
        icon="mdi:latitude",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "mount", "Response", "SiteLatitude", digits=5),
    ),
    NinaSensorDescription(
        key="mount_site_longitude",
        name="Site Longitude",
        native_unit_of_measurement=DEGREE,
        icon="mdi:longitude",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "mount", "Response", "SiteLongitude", digits=5),
    ),
    NinaSensorDescription(
        key="mount_site_elevation",
        name="Site Elevation",
        native_unit_of_measurement=UnitOfLength.METERS,
        device_class=SensorDeviceClass.DISTANCE,
        icon="mdi:elevation-rise",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "mount", "Response", "SiteElevation", digits=1),
    ),

    NinaSensorDescription(
        key="mount_guide_rate_ra",
        name="Guide Rate RA",
        native_unit_of_measurement="arcsec/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # PHD2 calibration is computed against the guide rate. If a driver
        # reconnect or hand controller resets it and PHD2 restores a stale
        # calibration, every correction is scaled wrong for the rest of the
        # night with no error raised anywhere. Alert on deviation.
        value_fn=lambda d: safe_float(
            d, "mount", "Response", "GuideRateRightAscensionArcsecPerSec", digits=3
        ),
    ),
    NinaSensorDescription(
        key="mount_guide_rate_dec",
        name="Guide Rate Dec",
        native_unit_of_measurement="arcsec/s",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:speedometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: safe_float(
            d, "mount", "Response", "GuideRateDeclinationArcsecPerSec", digits=3
        ),
    ),
    NinaSensorDescription(
        key="mount_equatorial_system",
        name="Equatorial System",
        icon="mdi:earth",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # A JNOW/J2000 mismatch is the usual cause of plate solves landing a
        # consistent 15-20 arcmin off. Cannot change at runtime, so read it
        # when debugging pointing rather than alerting on it.
        value_fn=lambda d: safe(d, "mount", "Response", "EquatorialSystem"),
    ),
    NinaSensorDescription(
        key="mount_utc_date",
        name="UTC Date",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-alert-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Mounts with their own RTC or GPS drift, and 30s of clock error is
        # 7.5 arcmin of pointing error plus mistimed meridian flips. Many
        # ASCOM drivers just proxy the PC clock, which makes the check
        # tautological -- hence off by default.
        value_fn=lambda d: safe_datetime(
            d, "mount", "Response", "UTCDate", assume_utc=True
        ),
    ),

    # ── Focuser ───────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="focuser_position",
        name="Position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:focus-field",
        value_fn=lambda d: safe_int(d, "focuser", "Response", "Position"),
    ),
    NinaSensorDescription(
        key="focuser_temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: safe_float(d, "focuser", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="focuser_step_size",
        name="Step Size",
        native_unit_of_measurement="μm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ruler",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "focuser", "Response", "StepSize"),
    ),

    # ── Last autofocus run ────────────────────────────────────────────────
    NinaSensorDescription(
        key="autofocus_last_position",
        name="Last Autofocus Position",
        native_unit_of_measurement="steps",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:image-filter-center-focus",
        value_fn=lambda d: safe_int(
            d, "last_af", "Response", "CalculatedFocusPoint", "Position"
        ),
        attrs_fn=lambda d: {
            "previous_position": safe(
                d, "last_af", "Response", "PreviousFocusPoint", "Position"
            ),
            "method": safe(d, "last_af", "Response", "Method"),
        },
    ),
    NinaSensorDescription(
        key="autofocus_last_hfr",
        name="Last Autofocus HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points",
        value_fn=lambda d: safe_float(
            d, "last_af", "Response", "CalculatedFocusPoint", "Value"
        ),
    ),
    NinaSensorDescription(
        key="autofocus_last_temperature",
        name="Last Autofocus Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        icon="mdi:thermometer",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "last_af", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="autofocus_last_filter",
        name="Last Autofocus Filter",
        icon="mdi:filter",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe(d, "last_af", "Response", "Filter"),
    ),
    NinaSensorDescription(
        key="autofocus_last_timestamp",
        name="Last Autofocus Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-check-outline",
        value_fn=lambda d: safe_datetime(d, "last_af", "Response", "Timestamp"),
        attrs_fn=lambda d: {
            "duration": safe(d, "last_af", "Response", "Duration"),
            "r_squared": safe(d, "last_af", "Response", "RSquares"),
        },
    ),

    # ── Guider ────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="guider_rms_total",
        name="RMS Total",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-scatter-plot",
        value_fn=lambda d: safe_float(
            d, "guider", "Response", "RMSError", "Total", "Arcseconds"
        ),
    ),
    NinaSensorDescription(
        key="guider_rms_ra",
        name="RMS RA",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-left-right",
        value_fn=lambda d: safe_float(
            d, "guider", "Response", "RMSError", "RA", "Arcseconds"
        ),
    ),
    NinaSensorDescription(
        key="guider_rms_dec",
        name="RMS Dec",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-up-down",
        value_fn=lambda d: safe_float(
            d, "guider", "Response", "RMSError", "Dec", "Arcseconds"
        ),
    ),
    NinaSensorDescription(
        key="guider_peak_ra",
        name="Peak RA",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-expand-horizontal",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(
            d, "guider", "Response", "RMSError", "PeakRA", "Arcseconds"
        ),
    ),
    NinaSensorDescription(
        key="guider_peak_dec",
        name="Peak Dec",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:arrow-expand-vertical",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(
            d, "guider", "Response", "RMSError", "PeakDec", "Arcseconds"
        ),
    ),
    NinaSensorDescription(
        key="guider_pixel_scale",
        name="Pixel Scale",
        native_unit_of_measurement="arcsec/px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ruler-square",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda d: safe_float(d, "guider", "Response", "PixelScale", digits=3),
    ),
    NinaSensorDescription(
        key="guider_status",
        name="Status",
        icon="mdi:crosshairs",
        value_fn=lambda d: safe(d, "guider", "Response", "State"),
    ),

    # ── Rotator ───────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="rotator_position",
        name="Position",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:rotate-360",
        value_fn=lambda d: safe_float(d, "rotator", "Response", "Position"),
    ),
    NinaSensorDescription(
        key="rotator_mechanical_position",
        name="Mechanical Position",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cog-clockwise",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "rotator", "Response", "MechanicalPosition"),
    ),
    NinaSensorDescription(
        key="rotator_step_size",
        name="Step Size",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ruler",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        # Drivers that do not know their step size report 0.
        value_fn=lambda d: (
            v if (v := safe_float(d, "rotator", "Response", "StepSize", digits=3)) else None
        ),
    ),

    # ── Dome ──────────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="dome_azimuth",
        name="Azimuth",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass-outline",
        value_fn=lambda d: safe_float(d, "dome", "Response", "Azimuth"),
    ),
    NinaSensorDescription(
        key="dome_shutter_status",
        name="Shutter Status",
        icon="mdi:garage-open-variant",
        value_fn=lambda d: safe(d, "dome", "Response", "ShutterStatus"),
    ),

    # ── Flat device ───────────────────────────────────────────────────────
    NinaSensorDescription(
        key="flatdevice_cover_state",
        name="Cover State",
        icon="mdi:window-shutter",
        value_fn=lambda d: safe(d, "flatdevice", "Response", "CoverState"),
    ),
    NinaSensorDescription(
        key="flatdevice_brightness",
        name="Brightness",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brightness-6",
        value_fn=lambda d: safe_int(d, "flatdevice", "Response", "Brightness"),
    ),

    # ── Sequence ──────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="sequence_status",
        name="Sequence Status",
        icon="mdi:playlist-play",
        value_fn=sequence_state,
    ),
    NinaSensorDescription(
        key="sequence_target_name",
        name="Sequence Target",
        icon="mdi:star-circle",
        value_fn=sequence_target,
    ),
    NinaSensorDescription(
        key="sequence_current_instruction",
        name="Sequence Current Instruction",
        icon="mdi:playlist-check",
        value_fn=sequence_current_instruction,
    ),
    NinaSensorDescription(
        key="sequence_progress",
        name="Sequence Progress",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:percent",
        value_fn=sequence_progress,
    ),

    # ── Imaging train ─────────────────────────────────────────────────────
    #
    # Focal length is read from the active profile on every poll because a
    # focal reducer changes it mid-session; image scale and HFR in arcsec both
    # follow from it. Reporting HFR in arcsec rather than pixels is what makes
    # a threshold survive a binning change, a reducer swap or a new camera.
    NinaSensorDescription(
        key="telescope_focal_length",
        name="Telescope Focal Length",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:telescope",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=focal_length,
        attrs_fn=lambda d: {
            "focal_ratio": safe(
                d, "profile", "Response", "TelescopeSettings", "FocalRatio"
            ),
        },
    ),
    NinaSensorDescription(
        key="image_scale",
        name="Image Scale",
        native_unit_of_measurement="arcsec/px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:ruler",
        value_fn=image_scale,
    ),
    NinaSensorDescription(
        key="image_last_hfr_arcsec",
        name="Last Image HFR (arcsec)",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points-outline",
        value_fn=last_image_hfr_arcsec,
    ),

    # ── Last image statistics (polled from /image-history) ────────────────
    NinaSensorDescription(
        key="image_last_hfr",
        name="Last Image HFR",
        native_unit_of_measurement="px",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-four-points",
        value_fn=lambda d: latest_image_stat(d, "HFR"),
    ),
    NinaSensorDescription(
        key="image_last_star_count",
        name="Last Image Star Count",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-shooting",
        # The history field is "Stars"; there is no "DetectedStars".
        value_fn=lambda d: (
            None if (v := latest_image_stat(d, "Stars")) is None else int(v)
        ),
    ),
    NinaSensorDescription(
        key="image_last_mean_adu",
        name="Last Image Mean ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-histogram",
        value_fn=lambda d: latest_image_stat(d, "Mean"),
    ),
    NinaSensorDescription(
        key="image_last_median_adu",
        name="Last Image Median ADU",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:chart-bell-curve",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: latest_image_stat(d, "Median"),
    ),
    NinaSensorDescription(
        key="image_last_filter",
        name="Last Image Filter",
        icon="mdi:filter",
        value_fn=lambda d: latest_image(d).get("Filter"),
    ),
    NinaSensorDescription(
        key="image_last_exposure_time",
        name="Last Image Exposure Time",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
        value_fn=lambda d: latest_image_stat(d, "ExposureTime"),
    ),
    NinaSensorDescription(
        key="image_count",
        name="Session Image Count",
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:image-multiple",
        value_fn=lambda d: len(image_history(d)),
    ),

    # ── Flat Wizard ───────────────────────────────────────────────────────
    NinaSensorDescription(
        key="flats_state",
        name="Flat Wizard State",
        icon="mdi:auto-fix",
        value_fn=lambda d: safe(d, "flats", "Response", "State"),
    ),
    NinaSensorDescription(
        key="flats_progress",
        name="Flat Wizard Progress",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:progress-clock",
        # Idle reports -1 for both counters, which would otherwise compute
        # as 100%; only a positive total is a real run.
        value_fn=lambda d: (
            round(done / total * 100, 1)
            if (total := safe_int(d, "flats", "Response", "TotalIterations")) is not None
            and total > 0
            and (done := safe_int(d, "flats", "Response", "CompletedIterations")) is not None
            and done >= 0
            else None
        ),
        attrs_fn=lambda d: {
            "completed_iterations": safe(d, "flats", "Response", "CompletedIterations"),
            "total_iterations": safe(d, "flats", "Response", "TotalIterations"),
        },
    ),

    # ── Livestack ─────────────────────────────────────────────────────────
    NinaSensorDescription(
        key="livestack_status",
        name="Livestack Status",
        icon="mdi:layers-triple",
        # The spec documents lowercase running/stopped but the server sends
        # "Stopped"/"Running", so normalise rather than trusting either.
        value_fn=lambda d: (
            v.capitalize() if isinstance(v := safe(d, "livestack", "Response"), str) else None
        ),
    ),

    # ── Weather station (ASCOM ObservingConditions) ───────────────────────
    NinaSensorDescription(
        key="weather_temperature",
        name="Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer",
        value_fn=lambda d: safe_float(d, "weather", "Response", "Temperature"),
    ),
    NinaSensorDescription(
        key="weather_humidity",
        name="Humidity",
        native_unit_of_measurement="%",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:water-percent",
        value_fn=lambda d: safe_float(d, "weather", "Response", "Humidity"),
    ),
    NinaSensorDescription(
        key="weather_dew_point",
        name="Dew Point",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:thermometer-water",
        value_fn=lambda d: safe_float(d, "weather", "Response", "DewPoint"),
    ),
    NinaSensorDescription(
        key="weather_wind_speed",
        name="Wind Speed",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-windy",
        value_fn=lambda d: safe_float(d, "weather", "Response", "WindSpeed"),
    ),
    NinaSensorDescription(
        key="weather_wind_direction",
        name="Wind Direction",
        native_unit_of_measurement=DEGREE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:compass-rose",
        value_fn=lambda d: safe_float(d, "weather", "Response", "WindDirection"),
    ),
    NinaSensorDescription(
        key="weather_wind_gust",
        name="Wind Gust",
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-hurricane",
        value_fn=lambda d: safe_float(d, "weather", "Response", "WindGust"),
    ),
    NinaSensorDescription(
        key="weather_pressure",
        name="Barometric Pressure",
        native_unit_of_measurement=UnitOfPressure.HPA,
        device_class=SensorDeviceClass.PRESSURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:gauge",
        value_fn=lambda d: safe_float(d, "weather", "Response", "Pressure"),
    ),
    NinaSensorDescription(
        key="weather_cloud_cover",
        name="Cloud Cover",
        native_unit_of_measurement="%",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-cloudy",
        value_fn=lambda d: safe_float(d, "weather", "Response", "CloudCover"),
    ),
    NinaSensorDescription(
        key="weather_rain_rate",
        name="Rain Rate",
        native_unit_of_measurement="mm/h",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-rainy",
        value_fn=lambda d: safe_float(d, "weather", "Response", "RainRate"),
    ),
    NinaSensorDescription(
        key="weather_sky_quality",
        name="Sky Quality",
        native_unit_of_measurement="mag/arcsec²",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:star-circle-outline",
        value_fn=lambda d: safe_float(d, "weather", "Response", "SkyQuality"),
    ),
    NinaSensorDescription(
        key="weather_sky_brightness",
        name="Sky Brightness",
        native_unit_of_measurement="lx",
        device_class=SensorDeviceClass.ILLUMINANCE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:brightness-5",
        value_fn=lambda d: safe_float(d, "weather", "Response", "SkyBrightness"),
    ),
    NinaSensorDescription(
        key="weather_sky_temperature",
        name="Sky Temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:weather-night",
        value_fn=lambda d: safe_float(d, "weather", "Response", "SkyTemperature"),
    ),
    NinaSensorDescription(
        key="weather_seeing",
        name="Atmospheric Seeing",
        native_unit_of_measurement="arcsec",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:eye-circle-outline",
        value_fn=lambda d: safe_float(d, "weather", "Response", "StarFWHM"),
    ),
    NinaSensorDescription(
        key="weather_average_period",
        name="Average Period",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-sand",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_float(d, "weather", "Response", "AveragePeriod"),
    ),

    # ── Application ───────────────────────────────────────────────────────
    NinaSensorDescription(
        key="active_profile",
        name="Active Profile",
        icon="mdi:account-cog",
        # Profiles are how most rigs model a changed imaging train, so this is
        # usually what explains a change in focal length or image scale.
        value_fn=lambda d: safe(d, "profile", "Response", "Name"),
        attrs_fn=lambda d: {
            "profile_id": safe(d, "profile", "Response", "Id"),
            "description": safe(d, "profile", "Response", "Description"),
        },
    ),
    NinaSensorDescription(
        key="nina_version",
        name="Version",
        icon="mdi:information-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: (
            v.strip() or None if isinstance(v := safe(d, "nina_version", "Response"), str)
            else None
        ),
    ),
    NinaSensorDescription(
        key="nina_start_time",
        name="Start Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:clock-start",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: safe_datetime(d, "app_start", "Response"),
    ),
]


class NinaSensor(CoordinatorEntity[NinaDataCoordinator], SensorEntity):

    # HA composes the entity id from device name + entity name, which
    # keeps two N.I.N.A. instances from colliding.
    _attr_has_entity_name = True
    entity_description: NinaSensorDescription

    def __init__(self, coordinator, description, entry_id):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry_id}_{description.key}"
        self._attr_device_info = device_info_for_key(entry_id, description.key)

    @property
    def native_value(self):
        if self.entity_description.value_fn and self.coordinator.data:
            try:
                return self.entity_description.value_fn(self.coordinator.data)
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "Value lookup failed for %s", self.entity_description.key,
                    exc_info=True,
                )
                return None
        return None

    @property
    def extra_state_attributes(self) -> dict | None:
        if not self.entity_description.attrs_fn or not self.coordinator.data:
            return None
        try:
            attrs = self.entity_description.attrs_fn(self.coordinator.data)
        except Exception:  # noqa: BLE001
            return None
        # Drop empty values so disconnected devices do not publish null attrs.
        return {k: v for k, v in (attrs or {}).items() if v is not None} or None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]
    frame_store = entry_data["frame_store"]

    entities: list[SensorEntity] = [
        NinaSensor(coordinator, description, entry.entry_id)
        for description in SENSOR_DESCRIPTIONS
    ]

    # Per-frame push-driven statistics sensors
    from .frame_stats_sensor import (
        FRAME_SENSOR_DESCRIPTIONS,
        NinaFrameStatisticsSensor,
    )
    entities += [
        NinaFrameStatisticsSensor(frame_store, description, entry.entry_id)
        for description in FRAME_SENSOR_DESCRIPTIONS
    ]

    # Readonly switches reported by the switch device, one sensor each
    from .switch_device import async_readonly_switch_sensors
    entities += async_readonly_switch_sensors(coordinator, entry.entry_id)

    async_add_entities(entities)

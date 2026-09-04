"""Constants for the N.I.N.A. Astrophotography integration."""

from enum import IntEnum


class TrackingMode(IntEnum):
    """Mount tracking rates.

    The value is what /equipment/mount/tracking expects as its `mode`
    parameter; the label is what /equipment/mount/info reports back as
    TrackingMode, so one definition drives both the request and the display.
    """

    SIDEREAL = 0
    LUNAR = 1
    SOLAR = 2
    KING = 3
    STOPPED = 4

    @property
    def label(self) -> str:
        return self.name.capitalize()


DOMAIN = "nina_astrophotography"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_API_VERSION = "api_version"
CONF_POLL_INTERVAL = "poll_interval"

# Defaults
DEFAULT_PORT = 1888
DEFAULT_API_VERSION = "v2"
DEFAULT_POLL_INTERVAL = 10  # seconds

# Base API path
API_BASE = "http://{host}:{port}/{version}/api"

# ─── Endpoint paths ───────────────────────────────────────────────────────────

# Application
ENDPOINT_VERSION = "/version"
ENDPOINT_APP_INFO = "/application"

# Camera
ENDPOINT_CAMERA_INFO = "/equipment/camera"
ENDPOINT_CAMERA_CONNECT = "/equipment/camera/connect"
ENDPOINT_CAMERA_DISCONNECT = "/equipment/camera/disconnect"
ENDPOINT_CAMERA_COOL = "/equipment/camera/cool"
ENDPOINT_CAMERA_WARM = "/equipment/camera/warm"
ENDPOINT_CAMERA_CAPTURE = "/equipment/camera/capture"
ENDPOINT_CAMERA_ABORT = "/equipment/camera/abort"

# Mount / Telescope
ENDPOINT_MOUNT_INFO = "/equipment/telescope"
ENDPOINT_MOUNT_CONNECT = "/equipment/telescope/connect"
ENDPOINT_MOUNT_DISCONNECT = "/equipment/telescope/disconnect"
ENDPOINT_MOUNT_SLEW = "/equipment/telescope/slew-to-coordinates-j2000"
ENDPOINT_MOUNT_PARK = "/equipment/telescope/park"
ENDPOINT_MOUNT_UNPARK = "/equipment/telescope/unpark"
ENDPOINT_MOUNT_TRACKING = "/equipment/telescope/tracking"
ENDPOINT_MOUNT_HOME = "/equipment/telescope/find-home"

# Focuser
ENDPOINT_FOCUSER_INFO = "/equipment/focuser"
ENDPOINT_FOCUSER_CONNECT = "/equipment/focuser/connect"
ENDPOINT_FOCUSER_DISCONNECT = "/equipment/focuser/disconnect"
ENDPOINT_FOCUSER_MOVE = "/equipment/focuser/move"
ENDPOINT_FOCUSER_AUTO = "/equipment/focuser/auto-focus"

# Filter Wheel
ENDPOINT_FILTERWHEEL_INFO = "/equipment/filterwheel"
ENDPOINT_FILTERWHEEL_CONNECT = "/equipment/filterwheel/connect"
ENDPOINT_FILTERWHEEL_DISCONNECT = "/equipment/filterwheel/disconnect"
ENDPOINT_FILTERWHEEL_CHANGE = "/equipment/filterwheel/change-filter"

# Guider (PHD2)
ENDPOINT_GUIDER_INFO = "/equipment/guider"
ENDPOINT_GUIDER_CONNECT = "/equipment/guider/connect"
ENDPOINT_GUIDER_DISCONNECT = "/equipment/guider/disconnect"
ENDPOINT_GUIDER_START = "/equipment/guider/start-guiding"
ENDPOINT_GUIDER_STOP = "/equipment/guider/stop-guiding"
ENDPOINT_GUIDER_DITHER = "/equipment/guider/dither"

# Rotator
ENDPOINT_ROTATOR_INFO = "/equipment/rotator"
ENDPOINT_ROTATOR_CONNECT = "/equipment/rotator/connect"
ENDPOINT_ROTATOR_DISCONNECT = "/equipment/rotator/disconnect"
ENDPOINT_ROTATOR_MOVE = "/equipment/rotator/move"

# Dome
ENDPOINT_DOME_INFO = "/equipment/dome"
ENDPOINT_DOME_CONNECT = "/equipment/dome/connect"
ENDPOINT_DOME_DISCONNECT = "/equipment/dome/disconnect"
ENDPOINT_DOME_OPEN = "/equipment/dome/open"
ENDPOINT_DOME_CLOSE = "/equipment/dome/close"
ENDPOINT_DOME_PARK = "/equipment/dome/park"
ENDPOINT_DOME_HOME = "/equipment/dome/home"

# Flat Device
ENDPOINT_FLATDEVICE_INFO = "/equipment/flatdevice"
ENDPOINT_FLATDEVICE_CONNECT = "/equipment/flatdevice/connect"
ENDPOINT_FLATDEVICE_TOGGLE = "/equipment/flatdevice/toggle-light"
ENDPOINT_FLATDEVICE_BRIGHTNESS = "/equipment/flatdevice/set-brightness"

# Sequence
ENDPOINT_SEQUENCE_START = "/sequence/start"
ENDPOINT_SEQUENCE_STOP = "/sequence/stop"
ENDPOINT_SEQUENCE_LOAD = "/sequence/load"
ENDPOINT_SEQUENCE_STATUS = "/sequence"

# Image
ENDPOINT_IMAGE_HISTORY = "/image-history"
ENDPOINT_IMAGE_LATEST = "/image/latest"

# ─── HA Entity IDs ────────────────────────────────────────────────────────────

# Sensors
SENSOR_CAMERA_TEMP = "camera_temperature"
SENSOR_CAMERA_TARGET_TEMP = "camera_target_temperature"
SENSOR_CAMERA_COOLER_POWER = "camera_cooler_power"
SENSOR_CAMERA_STATUS = "camera_status"
SENSOR_CAMERA_GAIN = "camera_gain"
SENSOR_CAMERA_OFFSET = "camera_offset"
SENSOR_CAMERA_FILTER = "camera_current_filter"

SENSOR_MOUNT_RA = "mount_ra"
SENSOR_MOUNT_DEC = "mount_dec"
SENSOR_MOUNT_ALT = "mount_altitude"
SENSOR_MOUNT_AZ = "mount_azimuth"
SENSOR_MOUNT_STATUS = "mount_status"
SENSOR_MOUNT_SIDEREAL_TIME = "mount_sidereal_time"
SENSOR_MOUNT_TIME_TO_MERIDIAN = "mount_time_to_meridian_flip"

SENSOR_FOCUSER_POSITION = "focuser_position"
SENSOR_FOCUSER_TEMP = "focuser_temperature"
SENSOR_FOCUSER_STATUS = "focuser_status"

SENSOR_GUIDER_RMS = "guider_rms_total"
SENSOR_GUIDER_RMS_RA = "guider_rms_ra"
SENSOR_GUIDER_RMS_DEC = "guider_rms_dec"
SENSOR_GUIDER_STATUS = "guider_status"

SENSOR_SEQUENCE_STATUS = "sequence_status"
SENSOR_SEQUENCE_PROGRESS = "sequence_progress"
SENSOR_SEQUENCE_TARGET = "sequence_target_name"

SENSOR_IMAGE_COUNT = "image_count"
SENSOR_IMAGE_LAST_HFR = "image_last_hfr"
SENSOR_IMAGE_LAST_STARS = "image_last_star_count"
SENSOR_IMAGE_LAST_MEAN = "image_last_mean_adu"

# Binary sensors
BSENSOR_CAMERA_CONNECTED = "camera_connected"
BSENSOR_CAMERA_COOLING = "camera_cooling_enabled"
BSENSOR_MOUNT_CONNECTED = "mount_connected"
BSENSOR_MOUNT_PARKED = "mount_parked"
BSENSOR_MOUNT_TRACKING = "mount_tracking"
BSENSOR_MOUNT_SLEWING = "mount_slewing"
BSENSOR_FOCUSER_CONNECTED = "focuser_connected"
BSENSOR_FOCUSER_MOVING = "focuser_is_moving"
BSENSOR_FILTERWHEEL_CONNECTED = "filterwheel_connected"
BSENSOR_GUIDER_CONNECTED = "guider_connected"
BSENSOR_GUIDER_GUIDING = "guider_is_guiding"
BSENSOR_DOME_CONNECTED = "dome_connected"
BSENSOR_DOME_OPEN = "dome_shutter_open"
BSENSOR_SEQUENCE_RUNNING = "sequence_running"

# ─── Services ────────────────────────────────────────────────────────────────

SERVICE_CAMERA_COOL = "camera_cool"
SERVICE_CAMERA_WARM = "camera_warm"
SERVICE_CAMERA_CAPTURE = "camera_capture"
SERVICE_CAMERA_ABORT_CAPTURE = "camera_abort_capture"
SERVICE_MOUNT_SLEW = "mount_slew"
SERVICE_MOUNT_PARK = "mount_park"
SERVICE_MOUNT_UNPARK = "mount_unpark"
SERVICE_MOUNT_TRACKING = "mount_set_tracking"
SERVICE_FOCUSER_MOVE = "focuser_move"
SERVICE_FOCUSER_AUTO_FOCUS = "focuser_auto_focus"
SERVICE_FILTERWHEEL_CHANGE = "filterwheel_change_filter"
SERVICE_GUIDER_START = "guider_start"
SERVICE_GUIDER_STOP = "guider_stop"
SERVICE_DOME_OPEN = "dome_open"
SERVICE_DOME_CLOSE = "dome_close"
SERVICE_DOME_PARK = "dome_park"
SERVICE_SEQUENCE_START = "sequence_start"
SERVICE_SEQUENCE_STOP = "sequence_stop"
SERVICE_SEQUENCE_LOAD = "sequence_load"

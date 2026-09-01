"""Constants shared across the N.I.N.A. Astrophotography integration.

Endpoint paths are not here — each one is used by exactly one method of
NinaApiClient, so they live inline in api.py next to the call that issues them.
The enumerations below are shared between the API client and the entity
platforms, and mirror the Advanced API v2 spec (v2.2.15):
https://christian-photo.github.io/github-page/projects/ninaAPI/v2/doc/api
"""

DOMAIN = "nina_astrophotography"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_API_VERSION = "api_version"
CONF_POLL_INTERVAL = "poll_interval"
CONF_NAME = "name"

# Defaults
DEFAULT_PORT = 1888
DEFAULT_API_VERSION = "v2"
DEFAULT_POLL_INTERVAL = 10  # seconds
# Prefixes every device name, and therefore every entity id. Kept free of dots
# so it slugifies to "nina" rather than "n_i_n_a"; set per rig when running
# more than one N.I.N.A. instance.
DEFAULT_NAME = "NINA"

# Base API path
API_BASE = "http://{host}:{port}/{version}/api"
# WebSocket channel; see the AsyncAPI spec at .../v2/doc/websocket
WS_BASE = "ws://{host}:{port}/{version}/socket"

# ─── API enumerations ─────────────────────────────────────────────────────────

# /equipment/mount/tracking takes the index; MountInfo.TrackingMode reports the
# name. N.I.N.A. spells sidereal "Siderial" in TrackingMode — both are accepted
# on the way in, and we present the correct spelling to the user.
TRACKING_MODES = ["Sidereal", "Lunar", "Solar", "King", "Stopped"]
TRACKING_MODE_TO_INDEX = {
    "Sidereal": 0,
    "Siderial": 0,
    "Lunar": 1,
    "Solar": 2,
    "King": 3,
    "Stopped": 4,
}

# DomeInfo.ShutterStatus
SHUTTER_OPEN = "ShutterOpen"
SHUTTER_CLOSED = "ShutterClosed"

# FlatDeviceInfo.CoverState
COVER_STATES = [
    "Unknown",
    "NeitherOpenNorClosed",
    "Closed",
    "Open",
    "Error",
    "NotPresent",
]

# CameraInfo.CameraState values that mean an exposure is under way
CAMERA_BUSY_STATES = {"Exposing", "Reading", "Download"}

# /application/switch-tab
APPLICATION_TABS = [
    "equipment",
    "skyatlas",
    "framing",
    "flatwizard",
    "sequencer",
    "imaging",
    "options",
]

# /sequence/skip
SEQUENCE_SKIP_TYPES = ["CurrentItems", "ToEnd", "ToImaging"]

# /image-history and /equipment/camera/capture
IMAGE_TYPES = ["LIGHT", "FLAT", "DARK", "BIAS", "SNAPSHOT"]

# Sequence item/container Status values, upper-cased for comparison
SEQUENCE_STATUS_RUNNING = "RUNNING"
SEQUENCE_STATUS_FINISHED = "FINISHED"
SEQUENCE_STATUS_SKIPPED = "SKIPPED"
# A container that reached either of these will not run its remaining children,
# so anything still CREATED beneath one is unreachable rather than pending.
SEQUENCE_STATUS_SEALED = frozenset({SEQUENCE_STATUS_FINISHED, SEQUENCE_STATUS_SKIPPED})

# N.I.N.A. suffixes every container's name in the sequence tree.
SEQUENCE_CONTAINER_SUFFIX = "_Container"

# ─── Services ────────────────────────────────────────────────────────────────

SERVICE_CAMERA_COOL = "camera_cool"
SERVICE_CAMERA_WARM = "camera_warm"
SERVICE_CAMERA_CAPTURE = "camera_capture"
SERVICE_CAMERA_ABORT_CAPTURE = "camera_abort_capture"
SERVICE_CAMERA_SET_BINNING = "camera_set_binning"
SERVICE_CAMERA_DEW_HEATER = "camera_set_dew_heater"
SERVICE_MOUNT_SLEW = "mount_slew"
SERVICE_MOUNT_STOP_SLEW = "mount_stop_slew"
SERVICE_MOUNT_SYNC = "mount_sync"
SERVICE_MOUNT_PARK = "mount_park"
SERVICE_MOUNT_UNPARK = "mount_unpark"
SERVICE_MOUNT_TRACKING = "mount_set_tracking"
SERVICE_MOUNT_FLIP = "mount_meridian_flip"
SERVICE_FOCUSER_MOVE = "focuser_move"
SERVICE_FOCUSER_AUTO_FOCUS = "focuser_auto_focus"
SERVICE_FILTERWHEEL_CHANGE = "filterwheel_change_filter"
SERVICE_GUIDER_START = "guider_start"
SERVICE_GUIDER_STOP = "guider_stop"
SERVICE_GUIDER_CLEAR_CALIBRATION = "guider_clear_calibration"
SERVICE_ROTATOR_MOVE = "rotator_move"
SERVICE_DOME_OPEN = "dome_open"
SERVICE_DOME_CLOSE = "dome_close"
SERVICE_DOME_PARK = "dome_park"
SERVICE_DOME_SLEW = "dome_slew"
SERVICE_DOME_SET_FOLLOW = "dome_set_follow"
SERVICE_SWITCH_SET = "switch_set_value"
SERVICE_SEQUENCE_START = "sequence_start"
SERVICE_SEQUENCE_STOP = "sequence_stop"
SERVICE_SEQUENCE_SKIP = "sequence_skip"
SERVICE_SEQUENCE_RESET = "sequence_reset"
SERVICE_SEQUENCE_LOAD = "sequence_load"
SERVICE_FLATS_TRAINED = "flats_trained_flat"
SERVICE_FLATS_AUTO_EXPOSURE = "flats_auto_exposure"
SERVICE_FLATS_AUTO_BRIGHTNESS = "flats_auto_brightness"
SERVICE_FLATS_SKYFLAT = "flats_skyflat"
SERVICE_FLATS_STOP = "flats_stop"
SERVICE_SWITCH_TAB = "application_switch_tab"

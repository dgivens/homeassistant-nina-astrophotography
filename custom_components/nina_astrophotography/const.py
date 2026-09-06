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


DOMAIN = "nina_astrophotography"

# Config entry keys
CONF_HOST = "host"
CONF_PORT = "port"
CONF_INSTANCE_NAME = "instance_name"
CONF_POLL_INTERVAL = "poll_interval"
CONF_ROLLOVER_HOUR = "rollover_hour"

# Defaults
DEFAULT_PORT = 1888
DEFAULT_INSTANCE_NAME = "N.I.N.A."
DEFAULT_POLL_INTERVAL = 10  # seconds
# The session boundary, in the RIG's local hours. Noon is the astrophotographer's
# night boundary; a rig whose Windows clock runs UTC needs it moved, because
# every N.I.N.A. timestamp is local to that clock and 12:00 UTC falls inside a
# UTC-5 site's dawn flats.
DEFAULT_ROLLOVER_HOUR = 12

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

# v2.0 — carried-over findings

Things found while fixing 1.4.2 that were deliberately left out of the
single-purpose fix PRs, because each is a design change rather than a defect.
Every item below was verified against a live rig or upstream `ninaAPI` source.

## Polling cost of `/image-history?all=true`

The 1.4.2 fix requests the whole session history on every poll, because one
call has to serve both the last-frame stats and `Session Image Count`
(`len(Response)`). Measured at **453 bytes per frame**:

| frames | per poll | at the 10 s default |
|---|---|---|
| 89 | 39 KB | 0.23 MB/min |
| 300 | 133 KB | 0.78 MB/min |
| 600 | 265 KB | 1.55 MB/min |

It compounds through the night — a 10-hour, 300-frame session pulls roughly
240 MB off the imaging PC. Fine on a LAN, not fine over a WAN link to a remote
observatory.

**Fix:** two constant-size calls instead of one growing one.
`GET /image-history` with no parameters defaults `index` to `Count() - 1` and
returns the newest frame already wrapped in a one-element list, so
`_latest_stat` works unchanged; `GET /image-history?count=true` returns the
session total as an int. Together ~600 B/poll regardless of session length.
Needs a `get_image_count()` and a second `poll_all` entry, and
`image_count`'s `value_fn` changes from `len(...)` to reading the int.

Watch the empty-history case: with no parameters and no frames yet,
`index = -1` and the API answers `Success: false, "Index out of range"`. That
happens every night before the first sub.

## Server-side frame-type filtering

The same route takes `imageType`, so `?imageType=LIGHT` excludes calibration
frames at the source. Cleaner than sentinel handling for the **polled** path.
It does not help the WebSocket path, where `IMAGE-SAVE` delivers one frame at
a time and the sentinel check in `frame_statistics.py` is still required.

## Duplicate entity families

Two sets of entities measure the same things by different routes:

| polled (`sensor.py`, from image-history) | pushed (`frame_stats_sensor.py`, from IMAGE-SAVE) |
|---|---|
| `Last Image HFR` | `Last Frame HFR` |
| `Last Image Star Count` | `Last Frame Stars` |
| `Last Image Mean ADU` | `Last Frame Mean ADU` |
| `Session Image Count` | `Session Frame Count` |

`Flat Panel Light` also exists as both a `switch` and a `light` for one
device. Deduplicating is breaking, so it belongs with the v2 restructure.

## Blueprints target entity IDs that do not exist

All five hardcode bare IDs like `sensor.camera_temperature`, but the
integration produces `sensor.<area>_<device>_camera_temperature`. Five also
have the wrong suffix outright:

| blueprint references | actual |
|---|---|
| `binary_sensor.guider_is_guiding` | `guider_active` |
| `binary_sensor.camera_cooling_enabled` | `camera_cooling` |
| `sensor.image_count` | `session_image_count` |
| `sensor.sequence_target_name` | `sequence_target` |
| `sensor.frame_session_count` | `session_frame_count` |

The `!input` binding fix makes the templates resolve; it does not make the
blueprints work, because the entities they name are not there. The fix is
entity selectors as inputs rather than hardcoded IDs.

## `/sequence` needs a remap, not a path fix

`/sequence` is 404. The working path is `/sequence/state`, but its `Response`
is a nested container tree, not the flat object the sensors read
(`Response.Status`, `.TargetName`, `.ProgressExposures`). There is no flat
status endpoint — `/sequence/running` and `/sequence/status` are both 404. So
`binary_sensor.sequence_running` and the three sequence sensors stay unknown
until someone walks the tree.

## Image capture time after a restart

`image_last_updated` is `None` until the first `IMAGE-SAVE` of the session, so
a restart mid-session shows `unknown` even though a latest image exists. It
could be seeded from `/image-history`, whose frames carry a timezone-aware
`Date`. Left out of the 1.4.2 fix because it needs the corrected
`get_image_history`, which is a different PR.

## `Time to Meridian Flip` idle sentinel

The mount reports 24 hours when no flip is pending, which the units fix turns
into `1440 min`. No consumer misfires on it, but `state_class: measurement`
records a 1440 baseline in long-term statistics on every idle night. Mapping
the sentinel to `unknown` would avoid that and is a behaviour change, so it
was left out of a units fix.

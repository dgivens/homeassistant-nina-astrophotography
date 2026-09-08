# Captured fixtures

Recorded from a live rig running **Advanced API 2.2.15.2 / N.I.N.A. 3.2.0.9001**
on 2026-09-03/04, then redacted. These are the *authoritative* record of what
the wire actually sends — the published OpenAPI spec is reliable about field
names and unreliable about types, enum values and request parameter names, so
where they disagree, these win.

Naming is `<state>_<endpoint>.json`. Each file holds the **raw envelope**
(`{Response, Error, StatusCode, Success, Type}`), not the unwrapped body.

## What has been redacted

Credentials, account names, absolute paths, hostnames, IPv4 and IPv6 addresses,
UUIDs and Home Assistant entity ids are `"REDACTED"`. The same rules run as a
pre-commit hook over staged fixtures — install it once with
`uv run --group dev pre-commit install`. `DeviceId` and `EntityId` are stable pseudonyms
(`device-<8 hex>`) so *distinctness* survives — two weather sources still
compare unequal. `TelescopeName`/`CameraName` are
generic, and `Filename` is a stable pseudonym (`frame_<8 hex>.fits`) derived
from a hash of the original — never renumbered by position, since frame
identity is `(Date, Filename)` and the fold spans fixtures. `TargetName` is
kept: an astronomical object is not identifying.

The committed corpus predates the 8-hex digest and still carries the legacy,
narrower forms (`frame_NNNN.fits`, `device-NN`) from the pre-script redactor.
`redact()` accepts both forms as already-pseudonymised, so the legacy fixtures
stay clean without a re-capture.

Every fixture carries a trailing `_meta: {captured_at, nina_version,
api_version, endpoint, params}`, stripped before type-checking against the
schema. The 18 fixtures captured before `scripts/capture_fixtures.py` existed
had `_meta` backfilled by hand with `captured_at: "2026-09-04T00:00:00+00:00"`
and the versions in the heading above; `image_history_session.json` is a bare
JSON list, not an envelope, so it carries no `_meta`.

A trial capture of `/profile/show` contained a live API key, so it is captured
as an **allowlist projection**, never a redaction: only
`TelescopeSettings.FocalLength`, `FocuserSettings.{AutoFocusTimeoutSeconds,
RSquaredThreshold}`, `MeridianFlipSettings.*` and `CameraSettings.PixelSize`.
Excluding the endpoint entirely would leave a polled endpoint with no fixture,
no drift coverage and no mapper test. Never denylist it — its secret surface
is too large to redact confidently.

## Inventory

### Mid-session, dawn (a complete imaging night)

| File | Contents |
|---|---|
| `dawn_equipment_info.json` | 11 devices, 9 connected; Dome and Guider disconnected. FlatDevice connected (`device-03`, `MaxBrightness 4096`) |
| `dawn_event_history.json` | **628 events, 44 distinct types**, 19:41 → 07:06. Includes `SEQUENCE-FINISHED`, `MOUNT-BEFORE-FLIP`/`-AFTER-FLIP`, and 8 `AUTOFOCUS-STARTING` against 7 `AUTOFOCUS-FINISHED` (one unmatched — the AF-failure case) |
| `dawn_image_history_with_flats.json` | **122 frames: 55 LIGHT, 67 FLAT.** Every flat has `HFR 0` and `Stars -1`. Four targets, five filters, three exposure lengths |
| `dawn_image_history_count.json` | `?count=true` → `122` |
| `dawn_mount_tracking_off.json` | Session over: `TrackingEnabled false`, `AtHome true`, `TimeToMeridianFlip 24` (the idle sentinel) |
| `dawn_flatdevice_connected.json` | The only connected-flat-panel capture. `MaxBrightness 4096` — proves brightness is per-device, not 0–255 |
| `dawn_flats_status_idle.json` | `{State: "Finished", TotalIterations: -1, CompletedIterations: -1}` after a real Target Scheduler flat run |
| `dawn_sequence_complete.json` | `/sequence/json` with the night finished |

### After a N.I.N.A. restart (in-process state reset)

| File | Contents |
|---|---|
| `restart_application_start.json` | The new process timestamp — the restart detector |
| `restart_equipment_partial_connect.json` | Only 4 of 11 connected, and **19 `"NaN"` string fields**, including every `WeatherData` channel |
| `restart_event_history_truncated.json` | 13 events — the reconnection storm only |
| `restart_image_history_empty_index_error.json` | Bare `/image-history` on an empty history → `Success: false`, `"Index out of range"`, `StatusCode 400` |
| `restart_image_history_empty_list.json` | `?all=true` on the same state → `[]` |
| `restart_image_history_count_zero.json` | `?count=true` → `0` |
| `restart_sequence_state_no_progress.json` | `/sequence/state` without accumulated `SchedulerProgress` rows |

### Other states

| File | Contents |
|---|---|
| `startup_sequence_not_initialized.json` | The ~7.5 s window at N.I.N.A. startup: `"Sequence is not initialized"`, `StatusCode 409` |
| `weather_source_openmeteo.json` | A *second* weather source. Its usable channels are **disjoint** from the physical station's — OpenMeteo has `CloudCover` but not `SkyBrightness`/`SkyTemperature`; the station is the reverse |
| `live_image_save_push.json` | A live `IMAGE-SAVE` socket payload. Field-for-field identical to the matching `/image-history` record, including `Date` and `Filename` |
| `image_history_session.json` | Pre-existing fixture from an earlier session (89 frames) |

## Notes for anyone writing tests against these

- **`Date` is the save time**, not the exposure start — start + exposure +
  download. Verified against FITS `DATE-LOC`.
- **Calibration is keyed on `ImageType`** (`FLAT`, `DARK`, `BIAS`, `DARKFLAT`),
  not on a sentinel: `Stars == -1` appears on flats but a dark reported
  `Stars 1`, and a clouded light reports `HFR 0` too. `HFR 0` is a secondary
  null-out *inside* lights.
- **`"NaN"` arrives as a JSON string**, and which fields carry it depends on
  what is connected and on what the driver implements.
- **`/event-history` and `/image-history` are in-process**; both reset when
  N.I.N.A. restarts.

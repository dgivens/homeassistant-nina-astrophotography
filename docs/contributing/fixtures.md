# Test fixtures: capture from a live rig, then redact

Fixtures are **recorded from real hardware**, never hand-written. The published
OpenAPI spec is accurate about field *names* and unreliable about *types*, and
it contains at least one enum value that does not match the wire. Hand-written
fixtures encode the spec's mistakes; captured ones encode reality.

**Trust the rig over the spec wherever they disagree.**

Capture with `scripts/capture_fixtures.py`; install the redaction guard once
with `uv run --group dev pre-commit install` so a fixture cannot be committed
unredacted. Two hard rules:

**1. Read-only against a live rig.** Only `GET` endpoints that report state:
`/version`, `/version/nina`, `/equipment/info`, `/equipment/*/info`, `/image-history`,
`/sequence/json`, `/sequence/state`, `/event-history`, `/flats/status`,
`/equipment/focuser/last-af`, `/application-start`, `/livestack/status`, and
`/profile/show` (as an allowlist projection only — see below).
**Never** call anything that commands equipment — slew, capture, park, home,
connect, disconnect, guider, filter change, focuser move, flat light, dome,
sequence start/stop, profile switch — unless the operator has explicitly said
the rig is idle and it is safe. A rig may be imaging, and a wasted night is not
recoverable. If unsure whether a call mutates state, do not make it.

**A simulator rig is exempt.** This means a N.I.N.A. running a profile whose
eleven devices are all ASCOM/Alpaca simulators, the dome included. There is no
standing one: the operator brings one up on whatever machine is to hand, and
its address changes. Ask for it rather than assume a host. Any command may be
sent to it — slews, parks, sequences, disconnects — so it is where commands,
the dome and the upgrade from 1.4.5 get exercised.

A fixture captured from it is real wire data from simulated devices. Say so
where it is used, and never let it replace a capture of the same state from the
real rig, whose quirks (a station's `"NaN"` channels, a disconnected panel's
`0 / 0` range) a simulator need not reproduce. `docs/test-vm.md`
designs a disposable one.

**2. Redact before committing.** A profile dump contains live credentials.

| Field pattern | Action |
|---|---|
| `*ApiKey`, `*Token`, `*Secret`, `*Password`, `*Credential` | `"REDACTED"` |
| `*Path`, `*Folder`, `*Directory`, `*Host`, `*Url` | `"REDACTED"` |
| any Windows path, bare IPv4, UUID or HA entity id in a value | `"REDACTED"` |
| a site or facility identifier in `Name`, `DisplayName`, `Description` or `ProjectName` | `"REDACTED"` |
| a facility token inside any other string value | the token → `"REDACTED"`, the rest of the string kept |
| `DeviceId`, `EntityId` | stable pseudonym `device-<8 hex>`, preserving distinctness |
| `TelescopeName`, `CameraName` | `"Telescope"`, `"Camera"` |
| `Filename` | stable pseudonym `frame_<8 hex>.fits`, derived from the original |
| `TargetName` | keep — an astronomical object, not identifying |
| `SiteLatitude`, `SiteLongitude`, `SiteElevation`, `Altitude`, `SiderealTime`, `SideOfPier` | **keep** — see below |

**Site coordinates are kept, deliberately.** The rig is hosted at a public
commercial facility and its location is not sensitive here. Zeroing them was
also ineffective: a mount parked at the pole reports `Altitude` equal to the
site latitude, and `SiderealTime` against `Coordinates.DateTime.UtcNow` solves
for longitude — so the coordinates were derivable from fixtures whose named
fields were all correctly zeroed.

Keeping them is what makes §11's meridian-flip maths testable:
`(RA_JNOW − LST) mod 12` needs a real `SiderealTime`, and the pier-side windows
that add 12 h need a real `SideOfPier`. The alternative is a hand-written
synthetic `(LST, RA, longitude)` triple, and hand-written fixtures encode the
spec's mistakes rather than reality.

**`Filename` is pseudonymised by hashing the original, never numbered by
position.** Frame identity is `(Date, Filename)` and the fold spans fixtures, so
a per-file counter both collides distinct frames across files and splits
identical ones — which would make the path-equivalence property untestable.

The **existing corpus predates this rule** and still carries zeroed coordinates
and a `SideOfPier` of `"REDACTED"`. Re-capture will change those fields, so a
re-capture is not byte-identical to what is committed today; that is expected,
not a regression.

`/profile/show` is captured as an **allowlist projection** — only
`TelescopeSettings.FocalLength`, `FocuserSettings.{AutoFocusTimeoutSeconds,
RSquaredThreshold}`, `MeridianFlipSettings.*`, `CameraSettings.PixelSize` and
`AstrometrySettings.{Latitude,Longitude,Elevation}` (field by field: the section
also holds `HorizonFilePath`). Never denylist it: its secret surface is too large
to redact confidently, and it held a live `WeatherUndergroundAPIKey` on a trial
capture. The committed corpus predates the astrometry fields, so no profile
fixture carries a site until a re-capture.

The corpus needs **states**, not one snapshot — imaging, dawn flats (calibration
sentinels), before the first sub, equipment disconnected, sequence complete,
Home Assistant started before N.I.N.A. Capture them opportunistically as the
rig produces them.

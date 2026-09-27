# Test VM — design

**Status:** accepted, not yet implemented · 2026-09-27

The simulated rig is a disposable Windows VM running N.I.N.A., the Advanced API
and PHD2 against simulated equipment. It lets the integration be tested end to end,
commands included, without a Windows PC set aside for the purpose. It runs either
of two channels, stable or nightly (§0). §5 defines the `tests/rig/` test tier
that uses it.

The supported host is **macOS on Apple silicon**. Nothing outside the host
backend depends on the host, so another host can be added without redesigning
the rest (§4.1).

**How to read this document.** Normative text is plain. Justification appears in
*Rationale* blocks and can be skipped when implementing.

**Revisions.** The text above the first revision stays as written. A later
change is a new dated section at the end, after a horizontal rule. It says what
changed and why, and which earlier sections it replaces. The status line above
records where the work stands.

---

## 0. Glossary

| Term | Meaning |
|---|---|
| the rig | The VM this document designs |
| host | The machine the rig's VM runs on |
| guest | Windows, running inside the VM |
| channel | Which pair of N.I.N.A. and Advanced API versions the rig runs. **Stable** is a pinned release of each. **Nightly** is N.I.N.A.'s newest nightly build with the Advanced API's newest pre-release |
| simulator profile | A N.I.N.A. profile whose every device slot is a simulator. Any command may be sent to a N.I.N.A. running one |
| the live rig | The operator's real observatory. Read-only (CLAUDE.md) |
| the operator | Whoever runs the live rig, and owns the simulator profile the fixtures come from |
| FakeRig | `tests/scenarios/`: serves recorded responses to the `tests/ha/` suite |
| OmniSim | ASCOM's simulator for every device type, bundled with ASCOM Platform 7 |
| Evaluation ISO | Microsoft's free Windows 11 Enterprise Evaluation image: no product key, valid 90 days |

## 1. Purpose and non-goals

Testing the integration against a real N.I.N.A. otherwise needs a spare Windows PC:
N.I.N.A., a simulator profile, ASCOM Platform and PHD2, all installed by hand. That
PC runs one version at a time, cannot be reset, and is not something another
contributor can reproduce. The rig replaces it:

- **It is reproducible.** One command builds it from a public ISO and the
  repository, with no Windows licence.
- **It is disposable.** Every start begins from the same state.
- **It runs both channels.** Nightly is where the Advanced API's next breaking
  change will appear first (§9).

### 1.1 Where it sits

| Tier | Talks to | Commands | What it proves |
|---|---|---|---|
| `tests/unit/` | nothing | — | our pure logic |
| `tests/ha/` | FakeRig: recorded bytes | recorded in `rig.sent`, never executed | the integration against real wire data |
| **`tests/rig/`** (§5) | **the rig: real N.I.N.A., simulated devices** | **executed** | commands, events and state changes end to end |
| the live rig | real equipment | **never** | captures only |

### 1.2 Non-goals

- **CI.** Standard GitHub-hosted runners have no KVM, and only larger runners
  support nested virtualisation (§3.1). A Linux host backend (§4.1) would be the
  starting point if that changes.
- **Hosts other than macOS on Apple silicon.** The design keeps room for them
  (§4.1) but does not provide them.
- **Redistributing images.** The Evaluation licence does not allow it. Each user
  downloads the ISO and builds their own image.
- **Replacing captures from the live rig.** Simulators do not reproduce real
  hardware's quirks: a station's `"NaN"` channels, a disconnected panel's `0 / 0`
  range.
- **A version matrix.** There are two channels.

## 2. Decisions

| # | Decision | Choice |
|---|---|---|
| W-01 | Host | **macOS on Apple silicon**, running QEMU with HVF acceleration |
| W-02 | Guest | **Windows 11 ARM64.** N.I.N.A., OmniSim and PHD2 are x64 and run under Windows' x64 emulation (Prism) |
| W-03 | Windows media | **The Evaluation ISO, ARM64, 25H2**, downloaded by each user |
| W-04 | Build | **Packer**, using its QEMU builder with swtpm for the TPM. Adapted from [mac-vms `windows-11-arm64`][macvms] (MIT, notice kept) |
| W-05 | Answer file | `Autounattend.xml` is rendered from a template, with guest architecture and image index as variables. No product key |
| W-06 | Transport | WinRM (elevated) for Packer's provisioners; OpenSSH after that |
| W-07 | Generalisation | **No sysprep, no identity seeding.** The image boots straight into an autologon session |
| W-08 | Provisioning | `provision/*.ps1` turns **any** clean Windows 11, x64 or ARM64, into the rig. Packer calls it; so can a Windows VM the user made themselves |
| W-09 | Contents | ASCOM Platform **≥ 7.1 Update 3** (which bundles OmniSim), PHD2 x64, N.I.N.A., and the Advanced API and Livestack plugins |
| W-10 | Device selection | Every device slot uses an **OmniSim COM ProgID**, not Alpaca discovery |
| W-11 | Start-up | A logon task starts **N.I.N.A. only**. COM activation starts OmniSim, and N.I.N.A. starts PHD2 |
| W-12 | Profiles | The operator's simulator N.I.N.A. profile and PHD2 settings are **committed as fixtures** in `tests/fixtures/rig/` |
| W-13 | Image layers | Three qcow2 layers: `base`, then a layer per installed channel version, then `run` for one session (§4.3) |
| W-14 | Expiry | `rig.py up` warns at 80 days after the base image was built, and refuses at 90 |
| W-15 | Tooling | `tools/windows-rig/rig.py`, with its host-specific code confined to one backend (§4.1). `just` recipes wrap it. Pyright covers it |
| W-16 | Test tier | `tests/rig/` needs `--rig HOST:PORT` and `--simulated`, and checks the rig is simulated before sending any command (§5) |
| W-17 | Captures | Both channels are captured **on the same rig** and compared by **structure**, not values. `capture_fixtures.py --out` keeps these captures out of `tests/fixtures/` |

> *Rationale (W-01, W-02).* The rig is built for the host the project's
> maintainer uses. The guest has to match the host's architecture to be
> virtualised rather than emulated, so on Apple silicon it is ARM64. The equipment
> software is x64 only, so it runs under Prism inside that guest.

> *Rationale (W-03, W-04, W-14).* No Windows licence is needed. The Evaluation
> image expires after 90 days, and once expired it shuts down every hour.
> Rebuilding about every 80 days is therefore routine, and a routine rebuild has
> to be one command. Packer makes it one.

> *Rationale (W-07).* mac-vms runs sysprep and injects an identity so that one
> image can be cloned into many VMs. The rig runs one throwaway layer at a time, so
> generalising buys nothing. It would also force Windows' first-boot setup screens
> on every start.

> *Rationale (W-08).* The provisioning scripts are the part other hosts would
> reuse. Someone on a host without a backend can run them in a Windows VM of their
> own and get the same rig, without `rig.py`'s lifecycle.

> *Rationale (W-10, W-11).* OmniSim registers each device as a COM LocalServer32
> (§3.2), so Windows starts it when N.I.N.A. first creates the device. Alpaca
> discovery only finds an OmniSim that is already running, which would add a
> process to start and wait for.

> *Rationale (W-17).* Capturing the two channels on different machines would mix
> machine differences into version differences. Values differ between any two
> runs, so the comparison is of key paths and types.

## 3. Verified findings

### 3.1 Platform

- **mac-vms `windows-11-arm64`** ([source][macvms]):
  - It uses QEMU with swtpm because Tart has no TPM 2.0 and no Secure Boot, both
    of which Windows 11 requires.
  - A build takes about 16 minutes on an M2 Max and produces a qcow2.
  - DISM online servicing (the OpenSSH install) is denied under a plain WinRM
    token, so its provisioners run elevated.
  - The answer file's SKU metadata has to match the ISO.
- **The Evaluation ISO** is published for x64 and ARM64 at 25H2. It needs a
  registration form to download, lasts 90 days, and shuts down hourly once
  expired ([Evaluation Center][evalcenter]).
- **x64 emulation (Prism)** on Windows 11 ARM64 needs 24H2 or later for AVX
  ([Microsoft][prism]).
- **N.I.N.A. is a WPF desktop application.** It needs an interactive session,
  hence autologon, and cannot run as a service. The guest has no GPU, so WPF
  renders in software.
- **Standard GitHub-hosted Linux runners do not expose `/dev/kvm`.** Larger
  runners support hardware-accelerated nested virtualisation
  ([runner-images #7541][gh-kvm]).
- **Packer's `hyperv-iso` builder** supports Generation 2 VMs, `enable_tpm`,
  `enable_secure_boot` and `cd_files` ([docs][packer-hyperv]). That is what a
  Windows host backend would need (§4.1).

### 3.2 Equipment software

- **OmniSim registers each device as a COM LocalServer32** pointing at its own
  executable (`OmniSim.Telescope`, `OmniSim.Camera`, `OmniSim.Dome`, …), so COM
  activation starts it. See `RegisterObjects` in
  [`ASCOM.COM.LocalServer/LocalServer.cs`][omnisim-ls]. ASCOM Platform 7 installs
  OmniSim as its default simulators.
- **OmniSim's Windows builds are x86 and x64 only** ([releases][omnisim-rel]),
  so on the ARM64 guest it runs under Prism.
- **ASCOM Platform 7.1 Update 2** added a workaround for a .NET bug that made COM
  drivers fail, "particularly Windows ARM 64bit". Update 2 was **withdrawn** for
  instability, and Update 3 carries the fix ([releases][ascom-rel]).
- **N.I.N.A. starts PHD2 itself** when the guider connects, if the profile gives
  PHD2's path ([docs][nina-guider]).
- **PHD2 settings** are held by wxConfig under
  `HKCU\Software\StarkLabs\PHDGuidingV2`, with `-instanceN` appended for
  instances 2 and up (`ConfigName`, [`src/phdconfig.cpp`][phd-config]):
  - `phd2.exe -s <file>` writes **all** settings, every profile plus global keys
    such as `/currentProfile`, as UTF-8 text headed `PHD Config <ver>`, then
    exits. `phd2.exe -l <file>` deletes every setting, loads the file, and exits.
    See `cmdLineDesc` in [`src/phd.cpp`][phd-main], and `SaveAll`/`RestoreAll`.
  - Manage Profiles' export and import handle a single profile (`PHD Profile
    <ver>`) and leave out the global keys.
  - Dark libraries and defect maps live in `%LOCALAPPDATA%\PHD2` and are in
    neither file. PHD2's docs advise rebuilding them on a new machine
    ([docs][phd-supp]), and the simulator camera needs neither.
  - PHD2 opens its first-light profile wizard on a new configuration, or one
    holding a single empty profile (`OnInit`, [`src/phd.cpp`][phd-main]).
    Loading the settings before first launch avoids it.
  - PHD2 ships an x64 Windows installer (`phd2-x64.iss.in`) as well as x86.

### 3.3 Nightly channel

- **The Advanced API's pre-releases are its 3.0 line** (`3.0.0.3-b.4` at the
  time of writing). On the `v3` branch:
  - it requires N.I.N.A. **3.3.0.1053** (`MinimumApplicationVersion`);
  - it targets **.NET 10** (`net10.0-windows`).

  Stable 2.2.15.2 requires 3.2.0.9001 and targets .NET 8
  ([releases][ninaapi-rel]).
- **The 3.0 release notes** ([`3.0.0.0-b.1`][ninaapi-b1]):
  - add a `/v3` API with no response envelope, status codes carrying the result,
    and a `ProcessId` for long-running operations;
  - add optional **SSL and authentication**;
  - switch the web server to **SimpleW**;
  - remove base64 image support from v2. The integration requests images with
    `stream=true` (`api/v2/client.py:313`), so that removal alone does not affect it.
- **Neither nightly has a stable "latest" URL.**
  - N.I.N.A.'s nightly download path carries the build number
    ([download page][nina-dl]).
  - GitHub's `releases/latest` skips pre-releases, so the plugin's newest
    pre-release has to be picked from the release list.

### 3.4 This repository

- The upgrade harness runs Home Assistant in bridged Docker
  (`-p {PORT}:8123`, `tools/upgrade-harness/harness.py:237`). From inside that
  container, a port forwarded on the host is `host.docker.internal`, not
  `127.0.0.1`.
- The harness defaults `--host` to a fixed LAN address
  (`SIM_HOST`, `tools/upgrade-harness/harness.py:44`). No machine is permanently
  at that address.
- `scripts/capture_fixtures.py` always writes to `tests/fixtures/`
  (`FIXTURES`, `scripts/capture_fixtures.py:27`).
- The redaction guard `scripts/check_fixtures.py` parses JSON only, and
  pre-commit runs it only on `^tests/fixtures/.*\.json$`.
- FakeRig answers every command `Success: true` and records it in `rig.sent`, and
  nothing moves (`tests/scenarios/README.md`). The `tests/ha/` suite can check what
  was sent, never what the equipment did.

## 4. Design

### 4.1 The host backend

All host-specific behaviour lives in two places:
- a **backend** in `rig.py`, which creates and deletes layers, starts and stops
  the VM, and reports the address the rig is reachable at;
- a **Packer source**.

The provisioning scripts, the profile fixtures and `tests/rig/` do not depend on
the host. Anything in them that does is a defect.

There is one backend:

| Host | Backend | Accelerator | Guest | TPM | Layers |
|---|---|---|---|---|---|
| macOS, Apple silicon | `qemu` | HVF | ARM64 | swtpm | qcow2 |

On macOS it needs Packer with its QEMU plugin, `qemu` and `swtpm` (all from
Homebrew), the Evaluation ISO and `virtio-win.iso`. On any other host, `rig.py`
refuses with a pointer to W-08.

**Adding a host.** A new host is a new backend and, where needed, a new Packer
source, added by amending this document. For example:

| Host | Backend | Accelerator | Guest | TPM | Layers |
|---|---|---|---|---|---|
| Linux, amd64 | `qemu` | KVM | x64 | swtpm | qcow2 |
| Linux, arm64 | `qemu` | KVM | ARM64 | swtpm | qcow2 |
| Windows Pro or above | `hyperv` | Hyper-V | the host's | built in | differencing VHDX |

- **An x64 guest** needs the answer file's architecture variable set, and runs
  the equipment software without emulation.
- **Windows hosts** need Hyper-V rather than QEMU: swtpm is not supported on
  Windows, and Hyper-V has a built-in TPM (§3.1).
- **Hyper-V's Default Switch** gives the guest a NAT address rather than a port
  forward, so that backend would report the guest's address instead.

### 4.2 Layout

```
tools/windows-rig/
  packer/rig.pkr.hcl       the qemu source and the build
  packer/variables.pkr.hcl packer/autounattend.xml.pkrtpl
  provision/*.ps1          OpenSSH + firewall rule for 1888, ASCOM, PHD2,
                           profiles, autologon, logon task (W-08)
  install-nina.ps1         <nina-url> <api-zip-url> <livestack-zip-url>
  channels.toml            the pinned stable URLs and SHA256s
  scripts/qemu-with-tpm.sh
  rig.py  README.md  NOTICE
  .run/                    git-ignored: images, layers, swtpm state
tests/fixtures/rig/
  nina-simulator.profile  phd2-simulator.phdcfg
tests/rig/                 the tier in §5
```

The ISO paths and SHA256s are Packer variables. The ISOs never enter the
repository. Stable's versions change by editing `channels.toml`. Nightly's URLs
are discovered each time (`nightly-urls`, §4.5).

### 4.3 Image layers

```
base                      Packer: Windows, ASCOM, PHD2, profiles, autologon
 ├─ stable-<ver>          rig.py install stable   (once per pinned version)
 │   └─ run               rig.py up … down        (every session; discarded)
 └─ nightly-<build>       rig.py install nightly  (once per nightly build)
     └─ run
```

Each layer is a qcow2 whose backing file is the layer above it.

- **`install <channel>`** creates the channel layer. It boots a new child of
  `base`, runs `install-nina.ps1` over SSH, shuts the guest down, and keeps that
  child.
  - `install-nina.ps1` installs N.I.N.A. silently and unzips each plugin into
    N.I.N.A.'s plugin folder.
  - The two channels differ only in the URLs it is given.
- **`up <channel>`** creates `run` on top of the channel layer, installing that
  layer first if it is missing or out of date.
  - It starts the VM with SSH and port 1888 forwarded to the host.
  - It checks the base image's age (W-14).
  - **Starting the rig never installs anything**, and every session begins from
    the same state.
- **`down`** stops the VM and deletes `run`.
- **Rebuilding `base`** leaves every channel layer without its backing file, so
  `rig.py` deletes those layers.

### 4.4 Profiles as fixtures

- **`nina-simulator.profile`** is the operator's simulator profile, taken from
  `%LOCALAPPDATA%\NINA\Profiles\`.
- **`phd2-simulator.phdcfg`** is the output of `phd2.exe -s` on the same
  machine.
- **Provisioning** copies the profile into place and runs `phd2.exe -l` before
  PHD2 first starts.

They follow CLAUDE.md's redaction rules, with changes that keep them loadable:

- **The guard reads both formats.** `check_fixtures.py` parses the XML, and
  PHD2's tab-separated `key type value` lines, into the shape
  `tests/redaction.py`'s `scan` already takes. Pre-commit and CI run it over
  `tests/fixtures/rig/*`.
- **Paths are normalised to VM paths under `C:\rig\`**, not replaced with
  `REDACTED`, because a profile with dead paths does not load. `scan`
  allowlists that one prefix.
- **The profile's GUID `Id` is replaced with a freshly generated one**, which is
  allowlisted.
- **Credential and key fields are blanked.**
- **Device ids are OmniSim ProgIDs** (W-10). Alpaca device ids, which carry a
  network address, do not appear.
- **Both files are read by eye before committing,** as well as by the guard.
  Profiles can hold live API keys.

### 4.5 `rig.py`

| Command | Does |
|---|---|
| `build` | Runs `packer build` and records the build date for W-14 |
| `install stable\|nightly` | Creates or refreshes a channel layer (§4.3) |
| `nightly-urls` | Finds the newest N.I.N.A. nightly on its download page and the newest Advanced API pre-release |
| `up stable\|nightly` | Creates the run layer, starts the VM, checks the age; prints the `HOST:PORT` for tests |
| `wait` | Polls `/v2/api/version`, connects every device through the API, and checks each one reports connected |
| `down` | Stops the VM and deletes the run layer |

The `just` recipes `rig-build`, `rig-install`, `rig-up`, `rig-down` and
`rig-test` wrap it. `rig-test` runs `up`, `wait`, the `tests/rig/` suite and
`down`.

### 4.6 Comparing channels

For each channel:

1. `rig-up`, then `wait`.
2. Run a short simulator sequence, so that image history, events, last-AF and
   livestack have content.
3. `capture_fixtures.py --host <rig> --out <scratch>/<channel>`.
4. `rig-down`.

Compare the two directories by key path and type.

### 4.7 Changes elsewhere in the repository

- **`scripts/capture_fixtures.py`** gains `--out`, with a test.
- **`tools/upgrade-harness/harness.py`** makes `--host` required, with no
  default address (§3.4). Home Assistant in its container reaches a rig on the
  host at `host.docker.internal`.
- **`.gitignore`** gains `tools/windows-rig/.run/`.

## 5. The `tests/rig/` tier

`tests/ha/` proves the integration sends the right command and handles the right
bytes. It cannot prove the command did anything, because FakeRig moves nothing.
This tier sends the command to a real N.I.N.A. and checks what the equipment did.

**Contract:**

- **Opt-in twice.** The tier is collected only with
  `--rig HOST:PORT --simulated`. Without both, every test is skipped and says
  why. There is **no default host**.
- **It verifies the rig before commanding it.** A session fixture reads
  `/equipment/info` and fails the session **before any command is sent** unless
  every connected device's driver is a simulator (OmniSim's ProgIDs or names). A
  mistyped `--rig` that reaches the live rig stops here.
- **Outcomes are observed, never read from responses.** A command returns when
  N.I.N.A. accepts it (CLAUDE.md). A test polls state or waits for the event, with
  timeouts sized for emulation.
- **It is channel-agnostic.** The same suite runs against stable and nightly. A
  test that fails on one channel only is a finding about that channel.
- **It is HA-free where it can be.** Client-level tests run `api/v2/client.py`
  and `events.py` against the rig and import no Home Assistant, like
  `tests/unit/`. Integration-level tests put Home Assistant on the real client.
  Whether those run under PHACC with sockets allowed to the rig, or in the upgrade
  harness's container, is settled in stage 5 and recorded here.
- **Each session starts clean.** `rig-test` starts from a fresh run layer.
  Within a session, a test leaves the equipment as it found it (parked, connected
  or not), or its docstring says it doesn't.

**First coverage** is the destructive controls CLAUDE.md lists, which FakeRig can
only record:
- abort exposure;
- park and unpark;
- dome open and close;
- the flat panel light and brightness, against the device's real range;
- sequence start and stop;
- clearing the guider calibration.

Next come the event socket reporting what the equipment actually did, and the
actions' client-side validation against real device ranges.

## 6. Stages

Each stage ends at a gate. Failing a gate stops the work, not just the stage.

0. **Profile fixtures.** The operator exports both files. They are redacted per
   §4.4, the guard learns their formats, and they are committed.
   - *Gate:* `just ci` is green, and both files read clean by eye.
1. **Feasibility spike.** Build mac-vms' image **unmodified** except for the
   Evaluation ISO. Install everything by hand and load the committed profiles.
   - *Gate:* under emulation, all eleven devices connect, PHD2 guides on its
     simulator, and the host reaches `/v2/api/*` and `/v2/socket`.
2. **Provisioning and Packer.** `provision/*.ps1` and the Packer template.
   - *Gate:* `rig-build`, `rig-install stable` and `rig-up stable` reach a green
     `wait` with no manual steps.
3. **`install-nina.ps1`, `rig.py`, the recipes.**
   - *Gate:* `up stable` and `up nightly` each reach a green `wait`, and a second
     `up` of the same channel installs nothing.
4. **The harness change and the channel comparison** (§4.6, §4.7).
5. **`tests/rig/`, first slice.** The safety fixture, plus the first coverage in
   §5, at client level.
   - *Gate:* the tier passes on stable. Pointed at a N.I.N.A. with any real
     device, it refuses to run.

## 7. Open questions

Stage 1 answers these, and the answers are recorded here:

- The Evaluation ISO's image index and SKU label, for the answer file.
- Whether the N.I.N.A. profile loads with normalised paths and a new `Id`
  (`ImageFilePath`, `PHD2Path`, the plate solver's path).
- Whether PHD2 needs anything outside `-s`/`-l`, such as its update-check prompt.
- Which plugin folder nightly N.I.N.A. reads (`Plugins\3.0.0\` on stable).
- Silent-install switches for ASCOM Platform, N.I.N.A.'s setup bundle and PHD2.
- Whether the 3.0 plugin starts with authentication and SSL off.
- N.I.N.A.'s start-up time under emulation, which sets `wait`'s timeout, and
  which first-run dialogs need suppressing.

## 8. Risks

- **COM under emulation.** An ARM64-specific COM failure needed an ASCOM
  Platform fix in 2025 (§3.2). An x64 guest would not carry this risk.
- **Software rendering.** With no GPU, WPF is slow, and N.I.N.A.'s start-up may
  lengthen every `wait`.
- **Host assumptions.** With one backend, a macOS-only path or tool can enter
  `provision/`, the fixtures or `tests/rig/` without anything failing. Reviews
  check for it (§4.1).
- **Nightly URLs.** `nightly-urls` reads a web page, and the page can change.
- **Evaluation access.** Microsoft can move or re-gate the Evaluation ISO.
- **Rebuild cost.** A build takes about 16 minutes plus provisioning. If the
  80-day rebuild becomes a chore, the rig stops being used.

## 9. What the 3.0 plugin means for the integration

This is input to a future design. Nothing here is decided.

- **Authentication.** If a user enables it, `quality_scale.yaml`'s
  `reauthentication-flow` exemption (line 55: "The N.I.N.A. Advanced API has no
  authentication of any kind") no longer holds.
- **SSL.** The client assumes `http://` (`api/v2/client.py:87`).
- **The web-server change.** Moving to SimpleW may change two behaviours the
  client relies on: "the HTTP status is almost always 200", and "routing failures
  return HTML". The channel comparison (§4.6) and the `tests/rig/` tier show
  whether it does.
- **`/v3`** removes the envelope and adds process ids. It would be a new
  `api/v3/` beside `api/v2/`, which the 2.0 design left room for (D-01).

## 10. Alternatives considered

- **A dedicated Windows PC.** Cannot be reset, runs one version, and cannot be
  reproduced by another contributor.
- **A design that assumes macOS throughout.** A second host would then mean a
  rewrite rather than a backend.
- **Prebuilt images (Vagrant boxes, registries).** The Evaluation licence forbids
  redistribution.
- **Windows containers.** N.I.N.A. needs an interactive desktop session, and
  Windows containers run only on Windows hosts.
- **Lima** ([v2.2][lima]). It would do most of `rig.py`'s job, but its Windows
  guests are experimental: x86_64 only, with no port forwarding and no Windows
  hosts. Worth revisiting once it has ARM64 guests and port forwarding.
- **A VM built by hand.** The Evaluation ISO expires every 90 days, so the build
  has to be scripted.
- **An activated Windows licence.** The rig should cost a user nothing.
- **N.I.N.A. baked into the base image.** Nightly changes daily, and the base
  image is the slowest layer to rebuild.
- **Installing N.I.N.A. on every start.** Slow, and no two sessions would start
  from the same state.
- **A wider version matrix.** Stable and nightly answer the question the rig
  exists for.
- **Sysprep and identity seeding.** Only one run layer exists at a time.
- **Moving PHD2 settings with `reg export`/`reg import`.** `-s`/`-l` is PHD2's own
  format, and being text, it diffs.
- **Shell recipes instead of `rig.py`.** Shell does not carry to a Windows host,
  and URL discovery, polling and the expiry check read badly in it.
- **Alpaca device selection.** OmniSim would have to be started separately.

[macvms]: https://github.com/bbirkinbine/mac-vms/tree/main/packer/windows-11-arm64
[evalcenter]: https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise
[packer-hyperv]: https://developer.hashicorp.com/packer/integrations/hashicorp/hyperv/latest/components/builder/iso
[prism]: https://techcommunity.microsoft.com/blog/windowsosplatform/windows-on-arm-runs-more-apps-and-games-with-new-prism-update/4475631
[lima]: https://lima-vm.io/docs/usage/guests/windows/
[gh-kvm]: https://github.com/actions/runner-images/issues/7541
[omnisim-ls]: https://github.com/ASCOMInitiative/ASCOM.Alpaca.Simulators/blob/main/ASCOM.COM.LocalServer/LocalServer.cs
[omnisim-rel]: https://github.com/ASCOMInitiative/ASCOM.Alpaca.Simulators/releases
[ascom-rel]: https://github.com/ASCOMInitiative/ASCOMPlatform/releases
[nina-guider]: https://nighttime-imaging.eu/docs/master/site/tabs/equipment/guider/
[nina-dl]: https://nighttime-imaging.eu/download/
[phd-config]: https://github.com/OpenPHDGuiding/phd2/blob/master/src/phdconfig.cpp
[phd-main]: https://github.com/OpenPHDGuiding/phd2/blob/master/src/phd.cpp
[phd-supp]: https://openphdguiding.org/man-dev/Supplemental_Info.htm
[ninaapi-rel]: https://github.com/christian-photo/ninaAPI/releases
[ninaapi-b1]: https://github.com/christian-photo/ninaAPI/releases/tag/3.0.0.0-b.1

# Test VM — design

**Status:** accepted; stages 1 and 0 done, stage 2 next · 2026-10-20

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

---

## 2026-10-19 — Windows media, and profiles made in the rig

This revision replaces:
- W-03 and W-12;
- the glossary's *Evaluation ISO* and *the operator*;
- §3.1's finding on the Evaluation ISO;
- where §4.4 takes the profiles from;
- the order of stages 0 and 1 in §6, and both of their texts;
- §7, where one question is answered, one moves to stage 0, and two are added.

It also adds an entry to §10.

### Windows media

| # | Decision | Choice |
|---|---|---|
| W-03 | Windows media | **Windows 11 IoT Enterprise LTSC 2024 Evaluation, ARM64** (build 26100), downloaded by each user |

The glossary's *Evaluation ISO* now means this image. It is still free, needs no
product key and lasts 90 days, so W-14 is unchanged.

These findings replace §3.1's bullet on the Evaluation ISO:

- **The Windows 11 Enterprise evaluation offers no ARM64 download.** Its landing
  page lists "version 26H2 | x64 ISO and Arm64 ISO", but the download page
  reached after registering offers x64 only ([Q&A][q-arm64]). The same page says
  the 26H2 evaluation has to be signed into with a Microsoft account.
- **The IoT Enterprise LTSC 2024 evaluation publishes an ISO for each of x64 and
  ARM64** ([download][iot-eval]), behind the same registration form. It lasts 90
  days, needs no product key, and expires the same way: a black desktop and an
  hourly shutdown.
- **Its ARM64 ISO:**

  | | |
  |---|---|
  | File | `26100.1742.240906-0331.ge_release_svc_refresh_CLIENT_IOT_LTSC_EVAL_A64FRE_en-us.iso` |
  | SHA256 | `3dcdba9c9c0aa0430d4332b60c9afcb3cd613d648a49cbba2d4ef7b5978f32e8` |
  | Images in `install.wim` | one, index 1 |
  | `/IMAGE/NAME` | `Windows 11 IoT Enterprise LTSC 2024 Evaluation` |
  | EditionID, channel | `IoTEnterpriseSEval`, `eval` (`sources\EI.CFG`) |
  | Architecture, build | ARM64, 26100.1742 |

- **Microsoft publishes no hash for it that resolves.** The download page's
  `Windows11IOTEnterpriseLTSCHashValues.pdf` link redirects to the Evaluation
  Center's home page ([Q&A][q-hash]). The SHA256 above was computed from a
  download of the ISO. It matches the hash a user posted for this file in that
  thread, and it is the default for the ISO's SHA256 Packer variable (§4.2).
- **Prism's AVX and AVX2 translation is not in this build.** It reached every
  x64 app on 24H2 and later with a Prism update in December 2025
  ([Microsoft][prism]). Build 26100.1742 dates from September 2024. The guest
  has to take cumulative updates past that point before it emulates AVX.
- **LTSC has no Microsoft Store, and so no inbox `winget`.** `provision/*.ps1`
  installs from direct downloads, which W-08's "any clean Windows 11" already
  requires.
- **virtio-win 0.1.302** carries ARM64 builds of `viostor`, `vioscsi` and
  `NetKVM` under `w11\ARM64`.

> *Rationale.* LTSC keeps the evaluation licence: no key, no cost, no
> redistribution. With it the rest of the design stands, W-14 included. The
> Store and the inbox apps LTSC leaves out are not things the rig uses.

**The answer file (W-05)** selects image index 1 through W-05's index
variable; the name in the table above is what that index holds on this ISO. It
has no `<ProductKey>` block. mac-vms's file selects `Windows 11 Pro` by name and
supplies a generic key. Both of those change in stage 1, which is otherwise
still built from mac-vms unmodified.

**§10 gains an alternative:**

- **Microsoft's consumer ARM64 ISO with a generic key**, which is how mac-vms
  installs Windows 11 Pro. It never expires, which would remove W-14. But it
  means running unactivated retail Windows, which the rig should not ask of a
  contributor. It is the fallback if the IoT LTSC evaluation loses its ARM64
  download too, as the Enterprise evaluation already has (§8, *Evaluation
  access*).

### Profiles made in the rig

There is no existing simulator machine to export the profiles from, so they are
made in the rig.

| # | Decision | Choice |
|---|---|---|
| W-12 | Profiles | The simulator N.I.N.A. profile and PHD2 settings are **created in the stage 1 VM** and committed as fixtures in `tests/fixtures/rig/` |

- **§4.4:** `nina-simulator.profile` comes from the stage 1 VM's
  `%LOCALAPPDATA%\NINA\Profiles\`, and `phd2-simulator.phdcfg` is `phd2.exe -s`
  run there. Every device slot is set to its OmniSim COM driver when the profile
  is made (W-10).
- **Stage 1 uses the `C:\rig\` layout** for every path a profile records: image
  output, PHD2's executable, the plate solver. The exported profiles then
  already point where stage 2's provisioning installs things, so normalising
  paths changes almost nothing. The other redaction rules in §4.4 are
  unchanged: the `Id` is replaced, credentials are blanked, and both files are
  read by eye.
- **Glossary:** *the operator* is whoever runs the live rig. The operator no
  longer supplies the simulator profile.

The stages now run in the order 1, 0, 2, 3, 4, 5. Stages 2 to 5 are unchanged.

- **Stage 1, feasibility spike.** Build mac-vms' image with the Evaluation ISO
  and the answer-file changes above, and bring the guest up to date through
  Windows Update. Install everything by hand under the `C:\rig\` layout, then
  create the simulator profile in N.I.N.A. and PHD2's settings, and export both.
  - *Gate:* under emulation, all eleven devices connect, PHD2 guides on its
    simulator, and the host reaches `/v2/api/*` and `/v2/socket`.
- **Stage 0, profile fixtures.** The exported files are redacted per §4.4, the
  guard learns their formats, and they are committed.
  - *Gate:* `just ci` is green, and both files read clean by eye. Loaded back
    into the stage 1 VM (the N.I.N.A. profile imported, then `phd2.exe -l`), the
    redacted files still connect all eleven devices.

> *Rationale.* A profile made in the rig names the drivers and paths the rig
> actually has, so nothing about another machine has to be stripped out of it.
> Loading the redacted files in stage 0, while the stage 1 VM still exists,
> finds a redaction that breaks loading before stage 2 automates anything.

### Open questions

- **Answered:** the image index is 1, and the SKU label is the `/IMAGE/NAME`
  above.
- **Moved to stage 0:** whether the N.I.N.A. profile loads with normalised paths
  and a new `Id`. Stage 0's gate answers it.
- **Added for stage 1:**
  - Whether LTSC's setup accepts a local account without mac-vms's
    `BYPASSNRO` registry writes.
  - Whether N.I.N.A., OmniSim and PHD2 run on this edition under Prism once it
    is updated, and whether any of them needs AVX. Stage 1 records the build the
    gate passed on.

[iot-eval]: https://www.microsoft.com/en-us/evalcenter/download-windows-11-iot-enterprise-ltsc-eval
[q-arm64]: https://learn.microsoft.com/en-us/answers/questions/5996955/need-windows-11-enterprise-version-25h2-arm64-iso
[q-hash]: https://learn.microsoft.com/en-us/answers/questions/2181328/issue-broken-windows-11-iot-hashes-pdf-link

---

## 2026-10-20 — Stage 1 findings

Stage 1's gate passed. This revision records what stage 2 has to build to
reproduce it.

It replaces:
- W-07's account, W-09's PHD2 architecture and W-10's ProgIDs;
- §3.2's bullets on OmniSim's COM registration and on PHD2's x64 installer;
- the stage 1 open questions in §7 and in the 2026-10-19 revision, which it
  answers or carries forward.

It adds findings on the host, on servicing Windows from a remote session, and
on installing the equipment software, and two terms to the glossary.

### Glossary additions

| Term | Meaning |
|---|---|
| console session | The desktop session autologon starts. N.I.N.A., OmniSim and PHD2 run in it |
| remote session | A logon over SSH or WinRM. It has no desktop, and Windows refuses some servicing from it |

### The gate

| Condition | Result |
|---|---|
| All eleven devices connect under emulation | Yes. Each reports its `ASCOM.OmniSim.<Type>` ProgID as `DeviceId`; PHD2 reports `PHD2_Single` |
| PHD2 guides on its simulator | Yes, at 1.5–2.2″ RMS after a calibration of about five minutes |
| The host reaches `/v2/api/*` | Yes: `/version`, `/equipment/info`, `/equipment/guider/info` |
| The host reaches `/v2/socket` | Yes: the upgrade succeeds, and a commanded filter change arrives as `FILTERWHEEL-CHANGED` |

It passed with this setup:

| | |
|---|---|
| Host | MacBook Pro, M4 Max, macOS 26.6.2 |
| Tools | QEMU 11.1.2, Packer 1.16.1 with its QEMU plugin 1.1.7, swtpm from Homebrew |
| Guest | 8 vCPUs, 16 GB, a 100 GB disk |
| Windows | IoT Enterprise LTSC 2024 Evaluation, build **26100.9457** |
| Software | ASCOM Platform 7.1.3.4851, N.I.N.A. 3.2.0.9001, Advanced API 2.2.15.2, Livestack 1.1.5.1, PHD2 2.6.14 |

### The host

mac-vms' template, adapted, built the base in about eight minutes. Stage 2's
Packer source and `rig.py`'s backend carry these differences from it, besides
the answer file's (2026-10-19 revision):

- **The TPM device sets `ppi=off`.** QEMU 11.1's `tpm-tis-device` defaults
  to `ppi=on`, which adds a RAM region smaller than a 16 KiB host page.
  Hypervisor.framework refuses to map it, and QEMU exits at start-up with
  `HV_BAD_ARGUMENT` from `accel/hvf/hvf-all.c`. Neither Windows on ARM nor
  the `virt` machine's firmware uses PPI.
- **The swtpm socket lives in a short temporary directory.** macOS limits a
  Unix socket path to 104 bytes, and a path under the repository exceeds it.
- **No seed, no sysprep** (W-07). On a client edition, `sysprep /generalize
  /oobe` disables the built-in Administrator, which leaves only the seeded
  account to log in with. Packer shuts the guest down with a
  `shutdown_command` instead.
- **The rig runs with `virtio-gpu-pci`, and the build with `ramfb`.**
  `ramfb` has no resolution properties and shows the firmware's 800×600.
  Windows Setup has no driver for a virtio GPU, so the build keeps `ramfb`.
  Provisioning installs virtio-win's `viogpudo` (`viogpudo\w11\ARM64`) while
  the guest still has `ramfb`. Display settings then offer any resolution.
- **The forwards are SSH (22), RDP (3389) and the Advanced API (1888)**,
  each on the host's loopback interface.

### The guest

**The rig runs as the built-in Administrator**, which replaces W-07's
unnamed autologon user. The VM is reachable only through forwards on the
host's loopback interface, so a separate user protects nothing.

Provisioning applies these settings, none of which mac-vms makes:

- Administrator's autologon, made permanent. The answer file's `LogonCount`
  of 1 is spent during the build.
- The host's SSH key, in `administrators_authorized_keys`.
- PowerShell as OpenSSH's default shell
  (`HKLM:\SOFTWARE\OpenSSH\DefaultShell`).
- No display sleep, standby or lock screen.
- The `RemoteSigned` execution policy for the machine.
- Windows Firewall off on every profile. PHD2 and OmniSim each raise a
  firewall prompt when they first listen.

### Windows updates

**Stage 2 installs one pinned cumulative update** with `DISM /Add-Package`,
its URL and SHA256 Packer variables. Build 26100.1742 is 24H2's checkpoint,
so the current update applies directly to it.

The gate passed after Windows Update installed:

| Update | What it is |
|---|---|
| KB5129195 | 2026-09 cumulative security update, build 26100.9457 |
| KB5050575 | 2025-01 update for 24H2 ARM64 |
| KB5127690 | .NET Framework security update |

Whether KB5129195 needs KB5050575 is for stage 2 to find out.

> *Rationale.* A pinned update makes every 80-day rebuild the same, and
> costs one download and one restart. Running Windows Update until nothing is
> left (the `rgl/windows-update` Packer plugin) needs no pin, but each
> rebuild would differ, and the build gets much slower.

### Servicing from a remote session

**Downloading a Windows feature from Windows Update fails from a remote
session.** `DISM /Online /Enable-Feature /FeatureName:NetFx3` over SSH ends
with `E_ACCESSDENIED` ("Failed to get uup features from WU"). A scheduled
task that runs as Administrator without a stored password fails the same
way. The same command succeeds when typed into an elevated console in the
console session.

mac-vms installs OpenSSH, which comes from Windows Update too, through
Packer's `elevated_user`, whose scheduled task stores the password. Stage 2
uses `elevated_user` for every step that enables a feature or runs an
installer.

### The equipment software

| Software | Installer | Silent install | Notes |
|---|---|---|---|
| ASCOM Platform 7.1.3.4851 | InstallAware | `/s` | Needs .NET 3.5 enabled first. Afterwards, check that `OmniSim.Camera` has a class registered (below) |
| PHD2 2.6.14 | Inno Setup | `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /DIR=C:\rig\PHD2` | x86 |
| N.I.N.A. 3.2.0.9001 | WiX bundle, `NINASetupBundle.exe` inside the published zip | `/quiet /norestart` | x64, with its own .NET runtime |
| Advanced API 2.2.15.2, Livestack 1.1.5.1 | zip | unzip into `%LOCALAPPDATA%\NINA\Plugins\3.0.0\<plugin name>\` | Both match the SHA256s in N.I.N.A.'s plugin manifest |

- **ASCOM's installer enables .NET 3.5 itself, through a script that ends in
  `pause`.** From a remote session DISM fails, and the script then waits for
  a key that never comes. With .NET 3.5 already on, the installer skips the
  script.
- **ASCOM's own registration of the simulators can be missing after an
  install.** Here `OmniSim.<Type>` named CLSIDs that were not registered, and
  every device failed in N.I.N.A. with `MissingMethodException: .ctor`.
  Running the installer's Repair in the console session registered them. The
  install had been interrupted once and then run from a remote session, and
  it is not known which of the two left the registration out.
- **PHD2's Windows download is x86 only.** openphdguiding.org publishes one
  Windows installer, and it and `phd2.exe` are both x86. Prism runs x86 as
  it runs x64. This replaces W-09's "PHD2 x64" and the last bullet of §3.2's
  PHD2 findings.

### OmniSim's ProgIDs

COM reaches OmniSim through three families of ProgID:

| ProgID | In ASCOM's chooser | Served by |
|---|---|---|
| `ASCOM.OmniSim.<Type>` | yes, as "ASCOM OmniSim <Type>" | `OmniSim.COMProxy.exe`, an x86 .NET Framework local server |
| `ASCOM.Simulator.<Type>` | yes, under the Platform 6 simulators' names | the same proxy, when `SetSimulators` selects the OmniSims |
| `OmniSim.<Type>` | no | `ascom.alpaca.simulators.exe`, x64, OmniSim itself |

The proxy serves each device by opening `OmniSim.<Type>`, so OmniSim starts
when N.I.N.A. connects its first device.

- **W-10's ProgIDs are `ASCOM.OmniSim.<Type>`.** N.I.N.A. offers only drivers
  listed in ASCOM's chooser, and `OmniSim.<Type>` is not listed. This replaces
  §3.2's first bullet, whose ProgIDs are the unlisted family.
- **OmniSim needs the console session.** Started from a remote session, it
  exits at once: it cannot create its tray icon. It is started by COM on
  N.I.N.A.'s behalf, in the console session, so this never arises on the rig.
- **N.I.N.A. shows each device by OmniSim's name**, such as "Alpaca Camera
  Simulator". `tests/rig/`'s check that the rig is simulated (§5) keys on
  `DeviceId`, the ProgID.

### PHD2

- **Its first-light wizard asked for a camera and a mount.** The profile
  uses camera **Simulator** and mount **On Camera**. PHD2 also connected its
  AO simulator, which guides with the mount behind it, and the OmniSim
  rotator.
- **"Scope pointing information not available"** follows calibration. The On
  Camera mount cannot report declination or pier side. It needs nothing.
- **`phd2.exe -s` works from a remote session.** It needs no desktop and
  exits at once. The export includes the calibration, so a rig that loads it
  can start guiding without calibrating.

### The profiles

Both were exported from the stage 1 VM for stage 0:

- **`nina-simulator.profile`** is named `Simulator`. Its devices are the ten
  `ASCOM.OmniSim.<Type>` and PHD2 at `C:\rig\PHD2\phd2.exe`, and it saves
  images to `C:\rig\images\`. The sequence folders stay at their default,
  under Administrator's `Documents\N.I.N.A`. Stage 0's redaction treats
  them like any other `*Folder` path.
- **`phd2-simulator.phdcfg`** holds one profile, plus the global keys `-s`
  writes. It records no paths and no credentials.

### Open questions

- **Answered.** LTSC's Setup accepted the build's local Administrator
  without mac-vms's `BYPASSNRO` registry writes.
- **Answered.** N.I.N.A., OmniSim and PHD2 run on build 26100.9457 under
  Prism. Whether any of them needs AVX was not tested, since nothing ran on
  the ISO's build.
- **Answered.** The silent-install switches are in the table above.
- **Answered.** N.I.N.A. loads both plugins 5–8 s after it starts, and shows
  no first-run dialog. The device connections, not N.I.N.A., set `wait`'s
  timeout.
- **Answered.** PHD2 needs nothing outside `-s` and `-l` except the
  firewall, which is off. Its first-light wizard is what loading the settings
  before its first start avoids (§3.2). Stage 0's reload confirms it.
- **Carried to stage 3:** which plugin folder nightly N.I.N.A. reads, and
  whether the 3.0 plugin starts with authentication and SSL off. Stage 1 ran
  the stable channel only.

---

## 2026-10-20 — Stage 0: profile fixtures, and a simulated night

Stage 0's gate passed. This revision:
- replaces §4.4's list of what the guard allows, and its list of fixtures;
- adds a start-up sequence that N.I.N.A. runs at logon, which refines W-11,
  and a second sequence that simulates a night;
- replaces W-10 for the camera slot, which takes N.I.N.A.'s own simulator
  camera so that frames carry real star fields;
- adds the Connector plugin and ASTAP to W-09;
- adds requirements on provisioning;
- records the events and sentinels the simulated night shows.

### The gate

| Condition | Result |
|---|---|
| `just ci` is green | Yes, with the guard reading every file in `tests/fixtures/rig/` |
| Both files read clean by eye | Yes. Neither held a credential, an address or a personal path before redaction |
| Loaded back into the stage 1 VM, the redacted files connect all eleven devices | Yes. PHD2 started without its first-light wizard and guided on the loaded calibration, without recalibrating |

The profile's site, 51.07861° N, 0.29444° W, 708 m, is the ASCOM telescope
simulator's. N.I.N.A. copies the mount's site into the profile when it
connects.

### The fixtures

`tests/fixtures/rig/` holds four files:

| File | What it is | Where provisioning puts it |
|---|---|---|
| `nina-simulator.profile` | The N.I.N.A. profile `Simulator`, `Id` `660fe38b-4d3a-458e-b25a-beadb6f9c83c` | `%LOCALAPPDATA%\NINA\Profiles\<Id>.profile` |
| `phd2-simulator.phdcfg` | `phd2.exe -s`, with the calibration | loaded with `phd2.exe -l` |
| `test-sequence.json` | The start-up sequence (below) | `C:\rig\sequences\Test Sequence.json` |
| `simulated-night.json` | The simulated night (below) | `C:\rig\sequences\Simulated Night.json` |

`.gitattributes` marks them `-text`, so they keep the bytes the guest
wrote. PHD2's export has CRLF line endings.

### What the guard allows

`scripts/check_fixtures.py` reads JSON, N.I.N.A.'s XML and PHD2's
`key<TAB>type<TAB>value` lines. Pre-commit and CI run it over
`tests/fixtures/rig/*` as well as the JSON corpus.

A file in `rig/` may hold these values as they are (`rig_value_kept` in
`tests/redaction.py`):
- a path under `C:\rig\`;
- the profile's `Id`;
- the simulator camera's device id, `4C0BBF74-0D95-41F6-AAD8-D6D58668CF2C`,
  which is fixed in N.I.N.A.'s source;
- `localhost`, `nova.astrometry.net` and `http://nova.astrometry.net`,
  N.I.N.A.'s defaults for its PHD2, planetarium and plate-solving hosts.

The profile stores a plugin's settings, the simulator camera's among them,
as a serialized dictionary: a run of `KeyValueOf…` elements, each a `Key`
and a `Value`. The guard reads it back as a dictionary, so its key rules see
each setting's name (`Type`, `RAError`) and not the literal element `Key`.

The hosts are an addition to §4.4: a `PHD2ServerUrl` of `"REDACTED"` stops
N.I.N.A. reaching PHD2.

**An empty string is never redacted**, in any fixture. It holds nothing, and
a blanked credential is how a profile the rig loads carries one.

> *Rationale.* The profiles were made in the rig, so before redaction they
> held nothing to remove: their keys were empty and their paths were the VM's.
> The guard is for the next export, which may carry a key someone set to test
> a feature.

### N.I.N.A. resets a folder that does not exist

When N.I.N.A. loads a profile, it replaces each folder that does not exist
with its default under the user's profile. It does not report doing so, and
saves the default the next time it saves the profile. Provisioning creates
these folders before N.I.N.A. first starts:

- `C:\rig\images\`
- `C:\rig\sequences\`, with `Targets\` and `Templates\` inside it
- `C:\rig\FramingAssistantCache\`

### The start-up sequence

At logon, `C:\rig\start-nina.cmd`, in Administrator's Startup folder, runs:

```
NINA.exe --profileid 660fe38b-4d3a-458e-b25a-beadb6f9c83c --sequencefile "C:\rig\sequences\Test Sequence.json" --runsequence
```

The sequence:
1. connects all equipment;
2. unparks the scope, finds home on the scope and the dome, and opens the
   dome;
3. starts guiding, and waits five minutes;
4. stops guiding, parks the scope and the dome, closes the dome;
5. disconnects all equipment.

Connecting and disconnecting all equipment are the Connector plugin's
instructions.

This is how W-11's logon task starts N.I.N.A. The rig's tests build on this
sequence. How `wait` (§4.5) and `tests/rig/` (§5) relate to it is settled in
stages 3 and 5.

From a restart, the Advanced API answered in 45 s. N.I.N.A. started 34 s
after the restart, then OmniSim 17 s later, then PHD2 13 s after that, and
by then the sequence had connected all eleven devices. It ran to the end
unattended, and `/event-history` recorded each step: 44 events from the
devices connecting to `SEQUENCE-FINISHED`.

### W-09 adds the Connector plugin and ASTAP

| Software | Version | Archive | SHA256 |
|---|---|---|---|
| Connector plugin | 2.1.1.0 (needs N.I.N.A. 3.2.0.9001) | `https://github.com/isbeorn/nina.plugin.connector/releases/download/2.1.1.0/NINA.Plugins.Connector.2.1.1.0.zip` | `10CC54238C9F0E345C4414969583E54FFE7A85A07488A16F2FB4612EB02D3196` |
| ASTAP, command line, ARM64 | CLI-2026.09.01 | `https://downloads.sourceforge.net/project/astap-program/windows_installer/astap_command-line_version_win11_aarch64.zip` | `C2E1B21B23B85B9A903A930D7273425829F044873EB682AAAB4FD5D0BDD3EC59` |
| ASTAP's D05 star database | — | `https://downloads.sourceforge.net/project/astap-program/star_databases/d05_star_database.zip` | `39D59B73CB960FA0956C35162E70B09A8AF10EF20A1E8F5CAE7B77D48BE5CE31` |

- The plugin installs like the others, into
  `%LOCALAPPDATA%\NINA\Plugins\3.0.0\Connector\`.
- Both ASTAP archives unzip into `C:\rig\ASTAP\`, and the profile points
  N.I.N.A. at `C:\rig\ASTAP\astap_cli.exe`. That build is native ARM64 and
  needs no installer. D05 suits fields of about 0.6° and wider; the simulated
  camera's is 1°.
- SourceForge publishes no checksum that resolves. The SHA256s above were
  computed from the downloads.

### The camera slot: N.I.N.A.'s simulator camera

OmniSim's camera produces synthetic frames that do not follow the mount, so
star counts and HFR say nothing about pointing. The camera slot instead
takes **N.I.N.A. Simulator Camera** in its `SKYSURVEY` mode, which replaces
W-10 for that slot.

- **What it does.** On each exposure it takes the mount's coordinates, adds
  a configured pointing error, and downloads that patch of sky from ESO's
  online survey, 2500 × 2500 pixels across a 1° field. It writes a pixel size
  of 3.8 µm and the matching focal length (783 mm) into the profile.
  N.I.N.A. then measures HFR and star counts on real stars, and ASTAP solves
  real fields.
- **Its settings** live in the profile's plugin storage: `Type` `SKYSURVEY`,
  `RAError` 300″, `DecError` 120″. The error gives centring one correction
  to make.
- **It needs the internet**, as the guest has through QEMU's NAT. It
  downloads an image when the mount's coordinates change, and reuses it
  while they do not.
- **Its device id** is `4C0BBF74-0D95-41F6-AAD8-D6D58668CF2C`. §5's check
  that a rig is simulated accepts it alongside OmniSim's ProgIDs.

### Settings that keep the simulators apart

The simulators do not see one another. Three settings stop that from
producing behaviour no real rig shows:

| Interaction | Without the setting | Setting |
|---|---|---|
| Centring with a pointing error | The camera renders the mount's *reported* position plus the error. A sync moves the reported position, so the error returns after every sync and centring never converges | **Do not sync** (`TelescopeSettings.NoSync`). N.I.N.A. corrects with an offset, and centring converges |
| Rotating to a position angle | The survey image never turns, so a solve measures the same angle (4.38°) after every move, and "Slew, center and rotate" fails after ten attempts | The sequence uses **Slew and Center**. The rotator is still driven by its own instructions |
| PHD2 and the rotator | PHD2 turns its calibration as the rotator moves, but its simulated camera does not turn. After a 56° move, guiding wandered and every dither failed to settle | PHD2's rotator is **None** |

PHD2 guides with camera **Simulator** and mount **On Camera**, without its AO
simulator. Its simulated guide camera has 24 µm pixels behind a 160 mm guide
scope, 30.9″ a pixel, so a five-pixel dither is larger than on a real rig.

### The dome

The profile describes a 2.2 m dome around a German equatorial mount at its
centre: radius 1100 mm, the mount's axes at the dome's centre and equator
(offsets 0 mm), GEM axis 250 mm, lateral offset 0 mm, azimuth tolerance 2°.

- It finds home before parking, and synchronises during mount slews.
- It closes on unsafe. It refuses an unsafe shutter move, and an open
  shutter with no safety device.
- OmniSim's dome cannot slave itself (`CanSlave` false), so N.I.N.A. turns
  it. The sequence enables dome synchronisation after opening the shutter.

### The simulated night

`simulated-night.json`, loaded and started through the Advanced API:

1. connects all equipment, opens the flat panel's cover, unparks and homes
   the scope, homes the dome, opens it and starts following;
2. slews to M81, centres, and runs an autofocus;
3. starts Livestack and guiding, then takes four rounds of one 30 s LIGHT
   frame through each of Red, Green and Blue, dithering every two frames;
4. stops both, closes the dome, then takes ten 2 s FLAT frames through each
   filter with the panel's cover closed and its light at 50 of its 100;
5. parks the scope and the dome, and disconnects.

M81 never sets at the simulated site (51° N), so the sequence runs at any
hour.

### What a simulated night produces

A run in a fresh N.I.N.A. took 14 minutes and produced:

| Source | Result |
|---|---|
| `/image-history` | 42 frames: 12 LIGHT at HFR 3.40, 873 stars; 30 FLAT at `HFR "NaN"`, `Stars -1` |
| `/event-history` | 127 events: one `MOUNT-CENTER`, `AUTOFOCUS-STARTING` with 5 `AUTOFOCUS-POINT-ADDED` and no finish, `GUIDER-START`, 5 `GUIDER-DITHER`, `GUIDER-STOP`, 42 `IMAGE-SAVE`, 14 `FILTERWHEEL-CHANGED`, 11 `STACK-UPDATED`, the dome's and the flat panel's events, then `SEQUENCE-FINISHED` |
| `/equipment/focuser/last-af` | `No AF available`, status 500 |
| `/livestack/status` | `Stopped` |
| `/flats/status` | `Finished`, `-1` / `-1`: flats taken by a sequence leave it idle, as on the live rig |

`capture_fixtures.py --out tools/windows-rig/.run/captures/stable --state
sim_night` records all fourteen read-only endpoints after a run. Those
captures stay outside `tests/fixtures/`; they are the input to the channel
comparison (§4.6), and never stand in for a live-rig capture.

### Starting a sequence unattended

| Path | With devices disconnected | Notes |
|---|---|---|
| `NINA.exe --profileid … --sequencefile … --runsequence` | Runs | Emits no `SEQUENCE-STARTING`. Only at N.I.N.A.'s start |
| `/sequence/load`, then `/sequence/start` | **Waits on a confirmation dialog** | Answers `"Sequence started"`, `Success: true`, all the same |

- **Before an API start, `tests/rig/` connects every device through the
  API**, which is what `wait` does (§4.5). N.I.N.A. validates a sequence
  before running it and asks before running one whose devices are
  disconnected, even when its first instruction connects them.
- **A start is confirmed from `SEQUENCE-STARTING` or `/sequence/state`, never
  from the response** (CLAUDE.md: an action must not confirm from a
  command's own response).
- **A sequence file carries its progress.** N.I.N.A. saves each loop's
  `CompletedIterations` and each exposure's `ExposureCount` into the file. A
  sequence saved after a run loads with its loops complete and skips them,
  by either path. The fixtures are saved with progress reset, and
  `tests/unit/test_rig_sequences.py` checks it.

### What the simulators cannot produce

- **A successful autofocus.** The camera ignores the focuser, so the curve is
  flat and every autofocus fails. `/equipment/focuser/last-af` answers
  `No AF available`, and the event history shows `AUTOFOCUS-STARTING` with
  no `AUTOFOCUS-FINISHED`: the failure case.
- **Auto-brightness flats.** "Auto Brightness Flat" fails ("light source is
  too bright"): the frame's histogram never responds to the panel. The
  sequence sets the brightness and takes fixed-exposure flats.
- **Different frames.** A dither moves PHD2's lock position on its own
  simulated mount, not OmniSim's mount, so the camera renders the same field
  after it. Every LIGHT frame of a run, through every filter, is the same
  image: the same HFR and star count. Only centring changes the field.

Captures from the live rig cover these, and stay the record of what a real
night sends (stage 1 findings).

### Events and sentinels the integration must tolerate

The simulated runs show N.I.N.A. behaviour that a real rig shows too:

- **Connector's "connect all" emits `<DEVICE>-DISCONNECTED` before each
  `<DEVICE>-CONNECTED`**, a second or two apart.
- **`GUIDER-STOP` can arrive twice** for one stop.
- **Disconnecting the safety monitor emits `SAFETY-CHANGED` with
  `IsSafe: false`** before `SAFETY-DISCONNECTED`. Anything keyed on that
  event alone treats every shutdown as unsafe.
- **A FLAT frame can carry `HFR: "NaN"`** with `Stars: -1`. The live rig's
  flats carry `HFR 0`. The mapper discards both: it drops HFR, stars and
  guide RMS from every calibration frame.
- **Flat panels' ranges differ.** OmniSim's runs 0–100, alongside the
  operator's panels at 0–256 and 0–4096.

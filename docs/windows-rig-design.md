# Simulated rig — design

**Rev 2** · 2026-09-27 · **status: proposed** — nothing here is built yet

A disposable Windows VM running N.I.N.A. against simulated equipment. Any
contributor can build it, on Windows, Linux or macOS, amd64 or arm64. It exists to
test N.I.N.A. and the Advanced API end to end, commands included, without a
separate PC. It runs stable or nightly N.I.N.A. and Advanced API. §5 defines the
test tier that uses it.

Normative text is plain. Justification appears in *Rationale* blocks.
**Amendment rule:** a PR that contradicts this document amends it in the same PR
and bumps the rev.

---

## 1. Purpose and non-goals

Today, exercising the integration against a real N.I.N.A. means a spare Windows PC
with N.I.N.A., a simulator profile, ASCOM and PHD2 installed by hand. Only the
maintainer has one, its address changes, and it runs one version. This rig replaces
that PC with something reproducible:

- **Any contributor can build it.** It runs on the host they already have, and
  needs no Windows licence.
- **It is disposable.** Every start begins from the same state.
- **It runs two channels:** stable, and nightly N.I.N.A. with the nightly Advanced
  API. Nightly is where the next break will come from (§9).

### 1.1 Where it sits

| Tier | Talks to | Commands | What it proves |
|---|---|---|---|
| `tests/unit/` | nothing | — | our pure logic |
| `tests/ha/` | FakeRig: recorded bytes | recorded in `rig.sent`, never executed | the integration against real wire data |
| **`tests/rig/`** (§5) | **this rig: real N.I.N.A., simulated devices** | **executed** | commands, events and state changes end to end |
| live rig | the operator's observatory | **never**, read-only | captures only |

### 1.2 Non-goals

- **No CI, for now.** Standard GitHub-hosted runners expose no KVM, and only
  larger runners support nested virtualisation (§3.1). The design leaves the door
  open: the Linux host path is the one CI would use.
- **No redistribution.** The Evaluation licence does not allow sharing Windows
  images. Every contributor downloads their own ISO and builds their own image.
- **No replacement for captures from the real rig.** Simulators do not reproduce
  the real rig's quirks: a station's `"NaN"` channels, a disconnected panel's
  `0 / 0` range.
- **No version matrix.** Two channels.

## 2. Decisions

| # | Decision | Choice |
|---|---|---|
| W-01 | Hosts | macOS (QEMU + HVF), Linux (QEMU + KVM), Windows (Hyper-V); amd64 and arm64 |
| W-02 | Guest architecture | **Matches the host.** An x64 guest on amd64 runs natively; an ARM64 guest on arm64 runs the x64 software under Prism emulation |
| W-03 | Windows media | **Windows 11 Enterprise Evaluation** (x64 or ARM64, 25H2). No key, 90 days, and each contributor downloads their own |
| W-04 | Build | **One Packer template with two sources**, `qemu` (TPM from swtpm) and `hyperv-iso` (built-in vTPM), running the same provisioners. Adapted from [mac-vms `windows-11-arm64`][macvms] (MIT, notice kept) |
| W-05 | Answer file | One `Autounattend.xml` template, rendered per guest architecture (`processorArchitecture`) and image index. No product key |
| W-06 | Transport | WinRM (elevated) for Packer's provisioners; OpenSSH after that |
| W-07 | Generalisation | **No sysprep, no identity seeding.** The image boots straight into an autologon session |
| W-08 | Portable core | `provision/*.ps1` turns **any** clean Windows 11 into the rig, x64 or ARM64. Packer is one caller of it; a contributor's own Windows machine or VM is another |
| W-09 | Contents | ASCOM Platform **≥ 7.1 Update 3** (bundles OmniSim), PHD2 x64, N.I.N.A., and the Advanced API and Livestack plugins |
| W-10 | Device selection | Every slot uses an **OmniSim COM ProgID**, not Alpaca discovery |
| W-11 | Start-up | A logon task starts **N.I.N.A. only**. COM activation starts OmniSim, and N.I.N.A. starts PHD2 |
| W-12 | Profiles | The operator's simulator N.I.N.A. profile and PHD2 config, **committed as fixtures** under `tests/fixtures/rig/` |
| W-13 | Image layers | `base` ← `stable-<ver>` / `nightly-<build>` ← `run`: qcow2 overlays under QEMU, differencing VHDX under Hyper-V (§4.3) |
| W-14 | Expiry | `rig.py up` warns at 80 days since the base image was built, and refuses at 90 |
| W-15 | Tooling | `tools/windows-rig/rig.py`, one command set with a backend per hypervisor (`qemu`, `hyperv`) chosen from the host. `just` recipes wrap it. Pyright covers it |
| W-16 | Test tier | `tests/rig/` needs `--rig HOST:PORT` and `--simulated`, and checks the rig itself is simulated before sending any command (§5) |
| W-17 | Captures | Both channels are captured **on the same VM** and diffed by **structure**, not values. `capture_fixtures.py --out` keeps them out of `tests/fixtures/` |

> *Rationale (W-01, W-02).* A contributor's hardware decides both the
> hypervisor and the architecture. Matching the guest to the host means
> virtualisation everywhere and emulation nowhere except in the guest's own x64
> layer on ARM64. On amd64 hosts, N.I.N.A. runs exactly as on a real imaging PC.

> *Rationale (W-03, W-04).* No Windows licence is bought. The Evaluation image
> expires after 90 days, and once expired it shuts down every hour. Rebuilding
> about every 80 days is therefore routine, and a routine rebuild has to be one
> command on every host.
>
> Packer is the one tool that drives both QEMU and Hyper-V from a single template,
> so the provisioners are written once. On Windows hosts, Hyper-V rather than QEMU:
> it has a built-in virtual TPM, and swtpm is not supported on Windows.

> *Rationale (W-07).* mac-vms runs sysprep and injects an identity so that one
> image can be cloned into many VMs. This rig runs one throwaway overlay at a
> time, so generalising buys nothing, and it would force the out-of-box setup
> screens on every boot.

> *Rationale (W-08).* The provisioning scripts, not Packer, are the durable part.
> Someone whose platform no backend supports yet can still run them in a Windows
> VM of their own and get the same rig, without the lifecycle.

> *Rationale (W-10, W-11).* OmniSim registers each device as a COM LocalServer32
> (§3.2), so the first `CreateInstance` starts the process. With the Alpaca
> discovery route, OmniSim has to be running already, which adds something to
> start and to wait for.

> *Rationale (W-17).* Capturing two channels on two machines would mix machine
> differences into version differences. Values differ between any two runs, so the
> diff compares key paths and types.

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
- **Packer's `hyperv-iso` builder** has the options this rig needs
  ([docs][packer-hyperv]):
  - Generation 2 VMs;
  - `enable_tpm` and `enable_secure_boot`, with a `MicrosoftWindows` template;
  - `cd_files` for the answer file, since Generation 2 has no floppy.
- **Hyper-V is not available on Windows Home.** Contributors on Home fall back on
  W-08.
- **x64 emulation (Prism)** on Windows 11 ARM64 needs 24H2 or later for AVX
  ([Microsoft][prism]).
- **N.I.N.A. is a WPF desktop application.** It needs an interactive session,
  hence autologon, and cannot run as a service. The guest has no GPU, so WPF
  renders in software.
- **Standard GitHub-hosted Linux runners do not expose `/dev/kvm`.** Larger
  runners support hardware-accelerated nested virtualisation
  ([runner-images #7541][gh-kvm]).

### 3.2 Equipment software

- **OmniSim registers each device as a COM LocalServer32** pointing at its own
  executable (`OmniSim.Telescope`, `OmniSim.Camera`, `OmniSim.Dome`, …), so COM
  activation starts it. See `RegisterObjects` in
  [`ASCOM.COM.LocalServer/LocalServer.cs`][omnisim-ls]. ASCOM Platform 7 installs
  OmniSim as its default simulators.
- **OmniSim's Windows builds are x86 and x64 only** ([releases][omnisim-rel]).
  On an ARM64 guest it runs under Prism, like N.I.N.A.
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
    Loading the config before first launch avoids it.
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
  (`SIM_HOST`, `tools/upgrade-harness/harness.py:44`). No such standing host
  exists.
- `scripts/capture_fixtures.py` always writes to `tests/fixtures/`
  (`FIXTURES`, `scripts/capture_fixtures.py:27`).
- The redaction guard `scripts/check_fixtures.py` parses JSON only, and
  pre-commit runs it only on `^tests/fixtures/.*\.json$`.
- Every command FakeRig receives is answered `Success: true` and recorded in
  `rig.sent`, and nothing moves (`tests/scenarios/README.md`). The `tests/ha/`
  suite can check what was sent, but never what the equipment did.

## 4. Design

### 4.1 Host support

| Host | Backend | Accelerator | Guest | TPM | Layers |
|---|---|---|---|---|---|
| macOS arm64 | `qemu` | HVF | ARM64 | swtpm | qcow2 |
| macOS amd64 | `qemu` | HVF | x64 | swtpm | qcow2 |
| Linux amd64 | `qemu` | KVM | x64 | swtpm | qcow2 |
| Linux arm64 | `qemu` | KVM | ARM64 | swtpm | qcow2 |
| Windows amd64 or arm64 (Pro and up) | `hyperv` | Hyper-V | matches the host | built in | differencing VHDX |
| anything else | — | — | — | — | W-08: run `provision/` in your own Windows VM |

`rig.py` picks the backend and guest architecture from the host. A contributor
overrides them only to debug. A backend is **unverified** until someone has
built and run it on that host. The README marks each row, as the 2.0 design
marks the dome.

### 4.2 Layout

```
tools/windows-rig/
  packer/rig.pkr.hcl       sources: qemu, hyperv-iso; one build block
  packer/variables.pkr.hcl packer/autounattend.xml.pkrtpl
  provision/*.ps1          the portable core (W-08): OpenSSH + firewall 1888,
                           ASCOM, PHD2, profiles, autologon, logon task
  install-nina.ps1         <nina-url> <api-zip-url> <livestack-zip-url>
  scripts/qemu-with-tpm.sh
  rig.py  README.md  NOTICE
  .run/                    git-ignored: images, layers, swtpm state
tests/fixtures/rig/
  nina-simulator.profile  phd2-simulator.phdcfg
tests/rig/                 the tier in §5
```

The ISO paths and SHA256s are Packer variables. The ISOs never enter the
repository.

### 4.3 Image layers

```
base                      Packer: Windows, ASCOM, PHD2, profiles, autologon
 ├─ stable-<ver>          rig.py install stable   (once per pinned version)
 │   └─ run               rig.py up … down        (every start; discarded)
 └─ nightly-<build>       rig.py install nightly  (once per nightly build)
     └─ run
```

- Under QEMU the layers are qcow2 backing files. Under Hyper-V they are
  differencing VHDX disks. Both backends have the same meaning.
- **`install <channel>`** boots a throwaway child of `base` and runs
  `install-nina.ps1` over SSH. It then shuts the guest down and keeps that child
  as the channel layer.
  - `install-nina.ps1` installs N.I.N.A. silently.
  - It unzips each plugin into N.I.N.A.'s plugin folder.
  - Stable and nightly differ only in the URLs they are given.
- **`up <channel>`** creates `run` on the channel layer, installing that layer
  first if it is missing or stale.
  - It starts the VM with SSH and 1888 reachable from the host.
  - It checks the base image's age (W-14).
  - **Starting the VM never installs anything**, and every start begins from the
    same state.
- **`down`** stops the VM and deletes `run`.
- **Rebuilding `base`** leaves every channel layer without its parent, so
  `rig.py` deletes them.

### 4.4 Profiles as fixtures

- **`nina-simulator.profile`** is the operator's simulator profile, taken from
  `%LOCALAPPDATA%\NINA\Profiles\`.
- **`phd2-simulator.phdcfg`** is the output of `phd2.exe -s` on the same
  machine.
- **Provisioning** copies the profile into place and runs `phd2.exe -l` before
  PHD2 first starts.

They follow CLAUDE.md's redaction rules, with changes that keep them loadable:

- **The guard learns both formats.** `check_fixtures.py` parses the XML, and
  PHD2's tab-separated `key type value` lines, into the shape
  `tests/redaction.py`'s `scan` already takes. Pre-commit and CI run it over
  `tests/fixtures/rig/*`.
- **Paths are normalised to VM paths under `C:\rig\`**, not replaced with
  `REDACTED`, because a profile with dead paths does not load. `scan`
  allowlists that one prefix.
- **The profile's GUID `Id` is replaced with a freshly generated one**, which is
  allowlisted.
- **Credential and key fields are blanked.**
- **Alpaca device ids carry an address.** If the profile uses any, they are
  switched to the OmniSim ProgIDs, as W-10 requires anyway.
- **Both files are also read by eye before committing.** A trial `/profile/show`
  capture once carried a live API key.

### 4.5 `rig.py`

| Command | Does |
|---|---|
| `build` | `packer build -only=<backend source>`; records the build date for W-14 |
| `install stable\|nightly` | Builds or refreshes a channel layer (§4.3) |
| `nightly-urls` | Finds the newest N.I.N.A. nightly on its download page and the newest ninaAPI pre-release |
| `up stable\|nightly` | Run layer, VM start, the age check; prints the `HOST:PORT` to hand to tests |
| `wait` | Polls `/v2/api/version`, connects every device through the API, and checks each one reports connected |
| `down` | Stops the VM, deletes the run layer |

The `just` recipes `rig-build`, `rig-install`, `rig-up`, `rig-down` and `rig-test`
wrap it. `rig-test` runs `up`, `wait`, the `tests/rig/` suite and `down`.

### 4.6 Capture and diff

For each channel:

1. `rig-up`, then `wait`.
2. Run a short simulator sequence, so that image history, events, last-AF and
   livestack are populated.
3. `capture_fixtures.py --host <rig> --out <scratch>/<channel>`.
4. `rig-down`.

Diff the two directories by key path and type.

### 4.7 Changes elsewhere

- **`scripts/capture_fixtures.py`** gains `--out`, with a test.
- **`tools/upgrade-harness/harness.py`** makes `--host` required, with no
  default LAN address (§3.4). Home Assistant in its container reaches a rig on the
  host at `host.docker.internal`.
- **`.gitignore`** gains `tools/windows-rig/.run/`.
- **`CLAUDE.md`** says a simulator rig takes any command, and that none has a
  standing address.

## 5. The `tests/rig/` tier

`tests/ha/` proves the integration sends the right command and handles the right
bytes. It cannot prove the command did anything, because FakeRig moves nothing.
This tier sends the command to a real N.I.N.A. and checks what the equipment did.

**Contract:**

- **Opt-in twice.** The tier is collected only with
  `--rig HOST:PORT --simulated`. Without both flags, every test is skipped with
  the reason. There is **no default host**, as for the harness.
- **It checks for itself before commanding.** A session fixture reads
  `/equipment/info` and fails the session unless every connected device's driver
  is a simulator (OmniSim's ProgIDs or names) **before any command is sent**. A
  typo in `--rig` that points at the live rig must stop here, not at the
  first slew.
- **Outcomes are observed, never read from the response.** A command returns when
  N.I.N.A. accepts it (CLAUDE.md). A test polls state or waits for the event, with
  a timeout sized for emulation.
- **Channel-agnostic.** The same suite runs against stable and nightly. A test
  that fails on one channel only is a finding about that channel, not a flake.
- **HA-free where it can be.** Client-level tests (`api/v2/client.py` and
  `events.py` against the rig) import no Home Assistant, like `tests/unit/`.
  Integration-level tests put Home Assistant on the real client. Whether that
  runs under PHACC with sockets allowed to the rig host, or through the upgrade
  harness's container, is decided in stage 5.
- **Clean start per session.** `rig-test` starts from a fresh run layer. Within a
  session, tests leave the equipment as they found it (parked, disconnected state
  restored), or say in their docstring that they don't.

**First coverage:** the commands CLAUDE.md lists as destructive, which FakeRig
can only record:
- abort exposure;
- park and unpark;
- dome open and close;
- the flat panel light and brightness, against the device's real range;
- sequence start and stop;
- clearing the guider calibration.

After those come the event socket delivering what the equipment actually did, and
the actions' client-side validation against real device ranges.

## 6. Stages

Each stage ends at a gate. Failing a gate stops the work, not only the stage.

0. **Profile fixtures.** The operator exports both files. Redact them per §4.4,
   teach the guard, and commit.
   - *Gate:* `just ci` is green, and both files read clean by eye.
1. **Spike, on the maintainer's host** (macOS arm64). Build mac-vms' image
   **unmodified** except for the Evaluation ISO. Install everything by hand and load
   the committed profiles.
   - *Gate:* under emulation, all eleven devices connect, PHD2 guides on its
     simulator, and the host reaches `/v2/api/*` and `/v2/socket`.
2. **The portable core and the `qemu` source.** `provision/*.ps1` and the Packer
   template, with the answer file templated by architecture from the start.
   - *Gate:* `rig-build`, `rig-install stable` and `rig-up stable` reach a green
     `wait` with no clicks.
3. **`install-nina.ps1`, `rig.py`, the recipes.**
   - *Gate:* `up stable` and `up nightly` each reach a green `wait`, and a second
     `up` of the same channel installs nothing.
4. **The harness change and capture diff** (§4.6, §4.7).
5. **`tests/rig/`, first slice.** The safety fixture, plus the destructive
   commands in §5, at client level.
   - *Gate:* the tier passes on stable. Pointed at a N.I.N.A. with one real
     device, it refuses to run.
6. **Other hosts.**
   - Linux amd64 (`qemu`, KVM, x64 guest).
   - Then the `hyperv-iso` source for Windows hosts.

   Each row in §4.1 is marked verified once someone has run stages 2–5 on it.

## 7. Open questions

- The Evaluation ISOs' image indexes and SKU labels, for the answer-file
  template.
- Whether the N.I.N.A. profile loads with normalised paths and a new `Id`
  (`ImageFilePath`, `PHD2Path`, the plate solver's path).
- Whether PHD2 needs anything outside `-s`/`-l`, such as its update-check prompt.
- Which plugin folder nightly N.I.N.A. reads (`Plugins\3.0.0\` on stable).
- Silent-install switches for ASCOM Platform, N.I.N.A.'s setup bundle and PHD2.
- Whether the 3.0 plugin starts with authentication and SSL off.
- N.I.N.A.'s start-up time under emulation, which sets `wait`'s timeout, and
  which first-run dialogs need suppressing.
- How `rig.py` reaches the guest under Hyper-V. The Default Switch hands out a NAT
  address, not a port forward, so `up` has to discover and print it.
- Whether Windows 11 ARM64 Hyper-V hosts run ARM64 guests from the same template
  unchanged.

## 8. Risks

- **COM across emulation, on ARM64 guests.** An ARM64-specific COM failure
  needed a Platform fix in 2025 (§3.2). x64 guests don't carry this risk.
- **Software rendering.** With no GPU, WPF is slow. N.I.N.A.'s start-up may
  stretch every `wait`.
- **Untested backends.** The maintainer has one host. The other rows in §4.1
  stay unverified until a contributor runs them, and could rot unnoticed.
- **Churn in nightly URLs.** `nightly-urls` scrapes a page, and the page can
  change.
- **Evaluation access.** Microsoft can move or re-gate the Evaluation ISO.
- **Rebuild cost.** The build takes about 16 minutes plus provisioning. If the
  80-day rebuild becomes a chore, the rig stops being used.

## 9. What the 3.0 plugin means for the integration

This section is input to a future design; nothing here is decided.

- **Authentication.** If a user enables it, `quality_scale.yaml`'s
  `reauthentication-flow` exemption (line 55: "The N.I.N.A. Advanced API has no
  authentication of any kind") no longer holds.
- **SSL.** The client assumes `http://` (`api/v2/client.py:87`).
- **The web-server swap.** Moving to SimpleW may change two behaviours the
  client relies on: "the HTTP status is almost always 200", and "routing failures
  return HTML". The diff in §4.6 and the `tests/rig/` tier are how we find out.
- **`/v3`** removes the envelope and adds process ids. It would be a new
  `api/v3/` beside `api/v2/`, as the 2.0 design left room for (D-01).

## 10. Rejected alternatives

- **A spare Windows PC.** This is the status quo. Only one person has one, its
  address changes, and it runs one version.
- **Supporting macOS arm64 only.** The rig has to serve contributors on any
  host.
- **Sharing prebuilt images (Vagrant boxes, registries).** The Evaluation licence
  forbids redistribution.
- **Windows containers.** N.I.N.A. needs an interactive desktop session, and
  Windows containers run only on Windows hosts.
- **Lima** ([v2.2][lima]). It would do most of `rig.py`'s job, but its
  Windows guests are experimental: x86_64 only, no port forwarding, no Windows
  hosts. Worth revisiting once it has ARM64 guests and port forwarding.
- **QEMU on Windows hosts.** swtpm is not supported there, and WHPX acceleration
  lags Hyper-V's.
- **Building the VM by hand.** The evaluation expires every 90 days.
- **Buying an activated licence.** Declined.
- **Baking N.I.N.A. into the base image.** Nightly churns daily, and a base
  rebuild takes the longest.
- **Installing N.I.N.A. on every start.** Slow, and no two starts would match.
- **A wider version matrix.** Stable and nightly answer the question.
- **Sysprep and identity seeding.** Only one overlay runs at a time.
- **Moving PHD2 settings with `reg export`/`reg import`.** `-s`/`-l` is PHD2's own
  format, it is text, and it diffs.
- **Shell-only recipes instead of `rig.py`.** Shell is not portable to Windows
  hosts, and URL discovery, polling and the expiry check read badly in it.
- **Selecting devices over Alpaca.** OmniSim would need starting explicitly.

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

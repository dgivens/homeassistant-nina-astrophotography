# Windows test rig — design

**Rev 1** · 2026-09-27 · **status: proposed** — nothing here is built yet

A disposable Windows 11 VM on the development Mac that runs N.I.N.A. against
simulated equipment, so the integration can be exercised against **nightly**
N.I.N.A. and the nightly Advanced API as well as stable.

Normative text is plain. Justification appears in *Rationale* blocks.
**Amendment rule:** a PR that contradicts this document amends it in the same PR
and bumps the rev.

---

## 1. Purpose and non-goals

The simulator rig at `10.20.30.133:1888` covers **stable**: N.I.N.A. 3.2.0.9001
with Advanced API 2.2.15.2. Nothing covers **nightly**, which is where the next
break will come from (§8). This rig runs either channel on one throwaway VM,
rebuilt by one command, so that captures from the two channels can be diffed.

Non-goals:

- **No version matrix.** Two channels, stable and nightly.
- **No CI.** GitHub-hosted runners cannot run an ARM64 Windows guest. This is a
  local tool, like `tools/upgrade-harness/`.
- **No replacement for real-rig captures.** A capture from this VM is simulator
  data. It never replaces a capture of the same state from the real rig, whose
  quirks the simulators do not reproduce: the station's `"NaN"` channels, and a
  disconnected panel's `0 / 0` range.
- **No replacement for 10.20.30.133.** It remains the stable rig for the upgrade
  harness.

## 2. Decisions

| # | Decision | Choice |
|---|---|---|
| W-01 | Host | A Windows 11 **ARM64** VM on the Apple Silicon Mac, under QEMU with HVF |
| W-02 | Windows media | **Windows 11 Enterprise Evaluation, ARM64** (25H2): no key, 90 days |
| W-03 | Build | **Packer**, QEMU builder with swtpm, adapted from [mac-vms `windows-11-arm64`][macvms] (MIT, notice kept) |
| W-04 | Answer file | `Autounattend.xml` selects the Evaluation image index, with no product key |
| W-05 | Transport | WinRM (elevated) for Packer's provisioners; OpenSSH for everything after |
| W-06 | Generalisation | **No sysprep, no per-VM identity seeding.** The image boots straight into an autologon session |
| W-07 | Contents | Everything runs in the VM: ASCOM Platform **≥ 7.1 Update 3** (which bundles OmniSim), PHD2 x64, N.I.N.A., and the Advanced API and Livestack plugins |
| W-08 | Device selection | Every slot uses an **OmniSim COM ProgID**, not Alpaca discovery |
| W-09 | Start-up | A logon task starts **N.I.N.A. only**. COM activation starts OmniSim, and N.I.N.A. starts PHD2 |
| W-10 | Profiles | The simulator rig's N.I.N.A. profile and PHD2 config, **committed as fixtures** under `tests/fixtures/rig/` |
| W-11 | Image layers | `base` ← `stable-<ver>` / `nightly-<build>` ← `run`, each a qcow2 copy-on-write child (§4.2) |
| W-12 | Expiry | `rig.py up` warns at 80 days since the base image was built, and refuses at 90 |
| W-13 | Tooling | `tools/windows-rig/rig.py`, shaped like `harness.py` and covered by pyright; `just` recipes wrap it |
| W-14 | Captures | Both channels are captured **on the same VM** and diffed by **structure**, not values. `capture_fixtures.py --out` keeps them out of `tests/fixtures/` |

> *Rationale (W-02, W-03).* No Windows licence will be bought. The Evaluation
> image expires after 90 days, and once expired it shuts down every hour. Rebuilding
> about every 80 days is therefore routine, and a routine rebuild has to be one
> command. That rules out a hand-built VM.

> *Rationale (W-06).* mac-vms runs sysprep and injects an identity so that one
> image can be cloned into many VMs. This rig runs one throwaway overlay at a time,
> so generalising buys nothing, and it would force the out-of-box setup screens on
> every boot.

> *Rationale (W-08, W-09).* OmniSim registers each device as a COM LocalServer32
> (§3.2), so the first `CreateInstance` starts the process. With the Alpaca
> discovery route, OmniSim has to be running already, which adds something to
> start and to wait for.

> *Rationale (W-14).* Diffing nightly from the VM against stable from
> 10.20.30.133 would mix machine differences into version differences. Values
> differ between any two runs, so the diff compares key paths and types.

## 3. Verified findings

### 3.1 Platform

- **mac-vms `windows-11-arm64`** ([source][macvms]):
  - It uses QEMU with swtpm because Tart has no TPM 2.0 and no Secure Boot, both
    of which Windows 11 requires.
  - A build takes about 16 minutes on an M2 Max and produces a qcow2.
  - DISM online servicing (the OpenSSH install) is denied under a plain WinRM
    token, so its provisioners run elevated.
  - The answer file's SKU metadata has to match the ISO.
  - The build needs Packer with its QEMU plugin, `qemu`, `swtpm`, the Windows ISO
    and `virtio-win.iso`.
- **The Evaluation ISO** is published for ARM64 at 25H2. It needs a registration
  form to download, lasts 90 days, and shuts down hourly once expired
  ([Evaluation Center][evalcenter]).
- **x64 emulation (Prism)** on Windows 11 ARM64 needs 24H2 or later for AVX
  ([Microsoft][prism]).
- **N.I.N.A. is a WPF desktop application.** It needs an interactive session,
  hence autologon, and not a service. QEMU gives the guest no GPU, so WPF renders
  in software.

### 3.2 Equipment software

- **OmniSim registers each device as a COM LocalServer32** pointing at its own
  executable (`OmniSim.Telescope`, `OmniSim.Camera`, `OmniSim.Dome`, …), so COM
  activation starts it. See `RegisterObjects` in
  [`ASCOM.COM.LocalServer/LocalServer.cs`][omnisim-ls]. ASCOM Platform 7 installs
  OmniSim as its default simulators.
- **OmniSim's Windows builds are x86 and x64 only.** The native macOS and Linux
  arm64 builds do not help inside a Windows guest ([releases][omnisim-rel]).
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
  container, the VM's forwarded port on the Mac is `host.docker.internal`, not
  `127.0.0.1`.
- `scripts/capture_fixtures.py` always writes to `tests/fixtures/`
  (`FIXTURES`, `scripts/capture_fixtures.py:27`).
- The redaction guard `scripts/check_fixtures.py` parses JSON only, and
  pre-commit runs it only on `^tests/fixtures/.*\.json$`.

## 4. Design

### 4.1 Layout

```
tools/windows-rig/
  packer/windows.pkr.hcl  variables.pkr.hcl  Autounattend.xml
  provision/*.ps1         wait for WinRM, clean up, OpenSSH + firewall 1888,
                          ASCOM, PHD2, profiles, autologon, logon task
  scripts/qemu-with-tpm.sh
  install-nina.ps1        <nina-url> <api-zip-url> <livestack-zip-url>
  rig.py  README.md  NOTICE
  .run/                   git-ignored: images, layers, swtpm state
tests/fixtures/rig/
  nina-simulator.profile  phd2-simulator.phdcfg
```

The ISO paths and SHA256s are Packer variables. The ISOs themselves never
enter the repository.

### 4.2 Image layers

```
base.qcow2                    Packer: Windows, ASCOM, PHD2, profiles, autologon
 ├─ stable-<ver>.qcow2        rig.py install stable   (once per pinned version)
 │   └─ run.qcow2             rig.py up … down        (every start; discarded)
 └─ nightly-<build>.qcow2     rig.py install nightly  (once per nightly build)
     └─ run.qcow2
```

- **`install <channel>`** boots a throwaway child of `base` and runs
  `install-nina.ps1` over SSH. It then shuts the guest down and keeps that child as
  the channel layer.
  - `install-nina.ps1` installs N.I.N.A. silently.
  - It unzips each plugin into N.I.N.A.'s plugin folder.
  - Stable and nightly differ only in the URLs they are given.
- **`up <channel>`** creates `run.qcow2` on the channel layer, installing that
  layer first if it is missing or stale.
  - It starts QEMU with the SSH and 1888 ports forwarded.
  - It checks the base image's age (W-12).
  - **Starting the VM never installs anything**, and every start begins from the
    same state.
- **`down`** stops QEMU and deletes `run.qcow2`.
- **Rebuilding `base`** leaves every channel layer without its parent, so `rig.py`
  deletes them.

### 4.3 Profiles as fixtures

- **`nina-simulator.profile`** is copied from `%LOCALAPPDATA%\NINA\Profiles\` on
  10.20.30.133.
- **`phd2-simulator.phdcfg`** is the output of `phd2.exe -s` there.
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
- **Alpaca device ids carry an address.** If the rig's profile uses any, they are
  switched to the OmniSim ProgIDs, as W-08 requires anyway.
- **Both files are also read by eye before committing.** A trial `/profile/show`
  capture once carried a live API key.

### 4.4 `rig.py`

| Command | Does |
|---|---|
| `build` | `packer build`; records the build date for W-12 |
| `install stable\|nightly` | Builds or refreshes a channel layer (§4.2) |
| `nightly-urls` | Finds the newest N.I.N.A. nightly on its download page and the newest ninaAPI pre-release |
| `up stable\|nightly` | Run layer, QEMU, the age check |
| `wait` | Polls `/v2/api/version`, connects every device through the API, and checks each one reports connected |
| `down` | Stops QEMU, deletes the run layer |

The `just` recipes `rig-build`, `rig-install`, `rig-up` and `rig-down` wrap it.

### 4.5 Capture and diff

For each channel:

1. `rig-up`, then `wait`.
2. Run a short simulator sequence, so that image history, events, last-AF and
   livestack are populated.
3. Run `capture_fixtures.py --host 127.0.0.1 --out <scratch>/<channel>`.
4. `rig-down`.

Diff the two directories by key path and type. The upgrade harness reaches the VM
with `--host host.docker.internal` (§3.4).

### 4.6 Changes elsewhere

- **`scripts/capture_fixtures.py`** gains `--out`, with a test.
- **`CLAUDE.md`:**
  - The VM, like 10.20.30.133, takes any command.
  - Its captures are simulator data.
  - Point to `tools/windows-rig/README.md`.
- **`.gitignore`** gains `tools/windows-rig/.run/`.

## 5. Stages

Each stage ends at a gate. Failing a gate stops the work, not only the stage.

0. **Profile fixtures.** Pull both files from 10.20.30.133, redact them per §4.3,
   teach the guard, and commit.
   - *Gate:* `just ci` is green, and both files read clean by eye.
1. **Spike.** Build mac-vms' image **unmodified** except for the Evaluation ISO.
   Install everything by hand and load the committed profiles.
   - *Gate:* under emulation, all eleven devices connect, PHD2 guides on its
     simulator, and the Mac reaches `/v2/api/*` and `/v2/socket`.
2. **Packer provisioners** (§4.1).
   - *Gate:* `rig-build`, then `rig-install stable` and `rig-up stable`, reach a
     green `wait` with no clicks.
3. **`install-nina.ps1`, `rig.py`, the recipes.**
   - *Gate:* `up stable` and `up nightly` each reach a green `wait`, and a second
     `up` of the same channel installs nothing.
   - *Parity:* the upgrade harness against the VM on stable gives the same
     `check` result as against 10.20.30.133.
4. **Diff** (§4.5).

## 6. Open questions for the spike

- The Evaluation ISO's image index and SKU label, for `Autounattend.xml`.
- Whether the N.I.N.A. profile loads with normalised paths and a new `Id`
  (`ImageFilePath`, `PHD2Path`, the plate solver's path).
- Whether PHD2 needs anything outside `-s`/`-l`, such as its update-check prompt.
- Which plugin folder nightly N.I.N.A. reads (`Plugins\3.0.0\` on stable).
- Silent-install switches for ASCOM Platform, N.I.N.A.'s setup bundle and PHD2.
- Whether the 3.0 plugin starts with authentication and SSL off.
- N.I.N.A.'s start-up time under emulation, which sets `wait`'s timeout, and
  which first-run dialogs need suppressing.

## 7. Risks

- **COM across emulation.** An ARM64-specific COM failure needed a Platform
  fix in 2025 (§3.2), so this path has broken before.
- **Software rendering.** With no GPU, WPF is slow. N.I.N.A.'s start-up may
  stretch every `wait`.
- **Churn in nightly URLs.** `nightly-urls` scrapes a page, and the page can change.
- **Evaluation access.** Microsoft can move or re-gate the Evaluation ISO.
- **Rebuild cost.** The build takes about 16 minutes plus provisioning. If the
  80-day rebuild becomes a chore, the rig stops being used.

## 8. What the 3.0 plugin means for the integration

This section is input to a future design; nothing here is decided.

- **Authentication.** If a user enables it, `quality_scale.yaml`'s
  `reauthentication-flow` exemption (line 55: "The N.I.N.A. Advanced API has no
  authentication of any kind") no longer holds.
- **SSL.** The client assumes `http://` (`api/v2/client.py:87`).
- **The web-server swap.** Moving to SimpleW may change two behaviours the
  client relies on: "the HTTP status is almost always 200", and "routing failures
  return HTML". The diff in §4.5 is how we find out.
- **`/v3`** removes the envelope and adds process ids. It would be a new
  `api/v3/` beside `api/v2/`, as the 2.0 design left room for (D-01).

## 9. Rejected alternatives

- **Building the VM by hand.** The evaluation expires every 90 days.
- **Buying an activated licence.** Declined.
- **Baking N.I.N.A. into the base image.** Nightly churns daily, and a base
  rebuild takes the longest.
- **Installing N.I.N.A. on every start.** Slow, and no two starts would match.
- **Two fully baked images.** The channel layers give the same result without a
  second Packer build.
- **A wider version matrix.** Stable and nightly answer the question.
- **Sysprep and identity seeding.** Only one overlay runs at a time.
- **Moving PHD2 settings with `reg export`/`reg import`.** `-s`/`-l` is PHD2's own
  format, it is text, and it diffs.
- **Shell-only recipes instead of `rig.py`.** URL discovery, polling and the
  expiry check read badly in shell.
- **A second N.I.N.A. beside the stable one on 10.20.30.133.** N.I.N.A. installs
  in place, and both copies would share one plugin folder and one OmniSim.
- **Cloning 10.20.30.133.** It is not a VM.
- **A GitHub `windows-latest` job.** The harness's Linux Home Assistant
  container cannot run there, and failures cannot be inspected.
- **Selecting devices over Alpaca.** OmniSim would need starting explicitly.

[macvms]: https://github.com/bbirkinbine/mac-vms/tree/main/packer/windows-11-arm64
[evalcenter]: https://www.microsoft.com/en-us/evalcenter/evaluate-windows-11-enterprise
[prism]: https://techcommunity.microsoft.com/blog/windowsosplatform/windows-on-arm-runs-more-apps-and-games-with-new-prism-update/4475631
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

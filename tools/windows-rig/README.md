# The test VM

A disposable Windows guest running N.I.N.A., the Advanced API and PHD2 against
simulated equipment, so the integration can be tested end to end, commands
included. `docs/test-vm.md` is its design; this file is how to run it.

The host is macOS on Apple silicon. On any other host, `rig.py` refuses, and
`provision/provision.ps1` turns a Windows VM you made yourself into the same
rig (see the end of this file).

## What you need

- `brew install packer qemu swtpm`
- The **Windows 11 IoT Enterprise LTSC 2024 Evaluation, ARM64** ISO, from
  Microsoft's Evaluation Center (free; a registration form). Its SHA256 is
  `3dcdba9c9c0aa0430d4332b60c9afcb3cd613d648a49cbba2d4ef7b5978f32e8`.
- **virtio-win 0.1.302**:
  `https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.302-1/virtio-win-0.1.302.iso`
- About 60 GB free, and internet access for the guest.

Neither ISO may be redistributed, and neither enters the repository.

## Running it

```bash
export RIG_WINDOWS_ISO=~/Downloads/26100.1742.240906-0331.ge_release_svc_refresh_CLIENT_IOT_LTSC_EVAL_A64FRE_en-us.iso
export RIG_VIRTIO_ISO=~/Downloads/virtio-win-0.1.302.iso

just rig-build          # the base image; rebuild it every 80 days
just rig-up             # stable; installs the channel layer the first time
just rig-wait           # waits for the Advanced API and connects all eleven devices
just rig-down           # stops the guest and discards the session
```

`rig-up` prints the address tests use, `127.0.0.1:1888`. SSH is on 2022 and
RDP on 3390, both on the loopback interface; the guest's Administrator
authorises the key at `.run/ssh/rig_ed25519`:

```bash
ssh -p 2022 -i tools/windows-rig/.run/ssh/rig_ed25519 Administrator@127.0.0.1
```

`rig.py up stable --show` opens the guest's display in a window; so does
`rig.py build --show`, which also takes `--on-error abort` to keep a failed
build's VM for inspection.

## What is where

| Path | What |
|---|---|
| `packer/` | The base image's QEMU source, its variables and the answer file template |
| `provision/` | The PowerShell that turns a clean Windows 11 into the rig; `downloads.json` pins what it downloads |
| `install-nina.ps1` | Installs one channel's N.I.N.A. and plugins, from the pins in `channels.toml` |
| `scripts/qemu-with-tpm.sh` | Packer's QEMU: adds the TPM, display and USB devices |
| `rig.py` | The lifecycle; its `QemuBackend` holds everything that knows the host |
| `.run/` | Git-ignored: images, the download mirror, the SSH key |

The layers under `.run/` stack base → channel → session. A channel layer is
reused while its base image and its pins are unchanged; `up` reinstalls it
when either changes. Rebuilding the base deletes every channel layer.

## A Windows VM of your own

Copy `provision/` to the guest and `tests/fixtures/rig/` to `C:\rig\fixtures`,
then, in an elevated PowerShell in the desktop session:

```powershell
$env:RIG_PASSWORD = "<your password, for autologon>"
$env:RIG_SSH_PUBLIC_KEY = "<an OpenSSH public key>"   # optional
& .\provision\provision.ps1
```

Then install a channel with `install-nina.ps1`, whose header shows the
channel file it reads. The guest must be updated through Windows Update first;
`provision/windows-update.ps1` is the build's pinned update, and is ARM64-only.

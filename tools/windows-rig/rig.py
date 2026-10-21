"""Build, install and run the test VM: a Windows guest running N.I.N.A., PHD2
and the Advanced API against simulators (docs/test-vm.md).

    uv run python tools/windows-rig/rig.py build --iso WIN.iso --virtio virtio-win.iso
    uv run python tools/windows-rig/rig.py up stable      # installs the channel if needed
    uv run python tools/windows-rig/rig.py wait           # connects every device
    uv run python tools/windows-rig/rig.py down

Everything lives under `tools/windows-rig/.run/` (git-ignored). The image
layers stack base → channel → session; `down` discards the session.

Only the backend knows the host. On a host without one, provision/provision.ps1
turns a Windows VM made by hand into the same rig (W-08).
"""

import argparse
from collections.abc import Callable
import contextlib
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from typing import Any
import urllib.request
import uuid

HERE = Path(__file__).resolve().parent
RUN = HERE / ".run"
BASE = RUN / "base"
CHANNELS = RUN / "channels"
SESSION = RUN / "session"
DOWNLOADS = RUN / "downloads"
SSH_KEY = RUN / "ssh" / "rig_ed25519"

# What the base image is built from; `up` warns when it has changed since.
BASE_SOURCES = (
    HERE / "packer",
    HERE / "provision",
    HERE.parents[1] / "tests" / "fixtures" / "rig",
)
INSTALLER = HERE / "install-nina.ps1"

VIRTIO_SHA256 = "303f7ae40dad495d6ae474fdc571df58958a4dbc5c37a522d80f9a203867949d"
VIRTIO_DRIVERS = ("viostor", "vioscsi", "NetKVM", "viogpudo")

# The Evaluation shuts down hourly once it expires, 90 days after installation.
WARN_AFTER_DAYS = 80
REFUSE_AFTER_DAYS = 90

DEVICES = (
    "camera",
    "filterwheel",
    "focuser",
    "rotator",
    "mount",
    "dome",
    "flatdevice",
    "switch",
    "weather",
    "safetymonitor",
    "guider",
)


@dataclass(frozen=True)
class Ports:
    ssh: int = 2022
    rdp: int = 3390
    api: int = 1888


# ── pure decisions ────────────────────────────────────────────────────────────


def age_verdict(built: date, today: date) -> tuple[bool, str] | None:
    """Whether to refuse the base image today, and why; `None` when it is fine."""
    age = (today - built).days
    if age >= REFUSE_AFTER_DAYS:
        return (
            True,
            f"the base image is {age} days old and its Evaluation has expired; run `rig.py build`",
        )
    if age >= WARN_AFTER_DAYS:
        return (
            False,
            f"the base image is {age} days old; its Evaluation expires at {REFUSE_AFTER_DAYS}, so rebuild soon",
        )
    return None


def channel_pins(channels: dict[str, Any], channel: str) -> dict[str, Any]:
    """The channel file install-nina.ps1 reads."""
    if channel not in channels:
        raise SystemExit(f"channels.toml has no [{channel}]")
    pins = channels[channel]
    return {"nina": pins["nina"], "plugins": pins["plugins"], "plugin": pins["plugin"]}


# ── files ─────────────────────────────────────────────────────────────────────


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _tree_sha256(*roots: Path) -> str:
    """One hash over every file under `roots`, by path and content."""
    digest = hashlib.sha256()
    for root in roots:
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            digest.update(str(path.relative_to(HERE.parents[1])).encode())
            digest.update(_sha256(path).encode())
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.exists() else None


def _fetch(url: str, sha256: str, target: Path) -> None:
    """Download `url` to `target` unless a file with that hash is already there."""
    if target.exists() and _sha256(target) == sha256.lower():
        return
    print(f"downloading {url}")
    partial = target.with_suffix(target.suffix + ".partial")
    # curl, not urllib: urllib tries each address in turn with no timeout, and
    # hangs on an IPv6 route that connects nowhere.
    subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--retry",
            "5",
            "--output",
            str(partial),
            url,
        ],
        check=True,
    )
    if (actual := _sha256(partial)) != sha256.lower():
        partial.unlink()
        raise SystemExit(f"{url} has SHA256 {actual}, expected {sha256}")
    partial.rename(target)


def _prefetch(arch: str) -> None:
    """Mirror provision/downloads.json on the host, so a rebuild fetches nothing.

    An entry is one pin, or a list of them with one per `arch`.
    """
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    entries = json.loads((HERE / "provision" / "downloads.json").read_text())
    for entry in entries.values():
        for pin in entry if isinstance(entry, list) else [entry]:
            if pin.get("arch", arch) == arch:
                _fetch(
                    pin["url"], pin["sha256"], DOWNLOADS / pin["url"].rsplit("/", 1)[-1]
                )


def _ssh_key() -> str:
    if not SSH_KEY.exists():
        SSH_KEY.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ssh-keygen",
                "-q",
                "-t",
                "ed25519",
                "-N",
                "",
                "-C",
                "nina-rig",
                "-f",
                str(SSH_KEY),
            ],
            check=True,
        )
    return SSH_KEY.with_suffix(".pub").read_text().strip()


# ── the guest over SSH ────────────────────────────────────────────────────────

_SSH_OPTIONS = (
    "-i", str(SSH_KEY),
    "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "LogLevel=ERROR",
    "-o", "ConnectTimeout=10",
)  # fmt: skip
_GUEST = "Administrator@127.0.0.1"


def _ssh(port: int, command: str, quiet: bool = False) -> int:
    """Run a PowerShell command in the guest; returns its exit code."""
    return subprocess.run(
        ["ssh", "-p", str(port), *_SSH_OPTIONS, _GUEST, command],
        capture_output=quiet,
        check=False,
    ).returncode


def _scp(port: int, sources: list[Path], target: str) -> None:
    subprocess.run(
        [
            "scp",
            "-P",
            str(port),
            *_SSH_OPTIONS,
            *map(str, sources),
            f"{_GUEST}:{target}",
        ],
        check=True,
    )


def _wait_for_ssh(port: int, alive: Callable[[], bool], timeout: float = 900) -> None:
    deadline = time.monotonic() + timeout
    while _ssh(port, "exit 0", quiet=True) != 0:
        if not alive():
            raise SystemExit("the VM exited before its guest answered SSH")
        if time.monotonic() > deadline:
            raise SystemExit(f"the guest did not answer SSH on port {port}")
        time.sleep(5)


# ── the host backend ──────────────────────────────────────────────────────────


def _ours(pid: int, marker: str) -> bool:
    """Whether `pid` is a live process whose command line holds `marker`.

    A record outlives its processes, and after a reboot their ids belong to
    something else, so a process is signalled only once its command line
    names the layer or TPM state it was started on.
    """
    ps = subprocess.run(
        ["ps", "-o", "command=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    return marker in ps.stdout


def _signal(pid: int, marker: str, sig: signal.Signals) -> None:
    if _ours(pid, marker):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, sig)


def _reap(pid: int) -> None:
    """Collect a child that exited, so that `ps` stops listing it."""
    with contextlib.suppress(ChildProcessError):
        os.waitpid(pid, os.WNOHANG)


class QemuBackend:
    """macOS on Apple silicon: QEMU with HVF, swtpm, qcow2 layers, an ARM64 guest."""

    arch = "ARM64"
    tools = (
        "packer",
        "qemu-system-aarch64",
        "qemu-img",
        "swtpm",
        "bsdtar",
        "ssh",
        "scp",
    )

    def __init__(self) -> None:
        missing = [tool for tool in self.tools if shutil.which(tool) is None]
        if missing:
            raise SystemExit(
                f"missing {', '.join(missing)}: brew install packer qemu swtpm"
            )
        share = (
            Path(shutil.which("qemu-system-aarch64") or "").resolve().parents[1]
            / "share"
            / "qemu"
        )
        self.efi_code = share / "edk2-aarch64-code.fd"
        self.efi_vars = share / "edk2-arm-vars.fd"

    # swtpm's socket path must fit macOS's 104-byte limit, which a path under
    # the repository does not; each boot gets a fresh TPM in a short temp dir.
    @staticmethod
    def _start_swtpm() -> tuple[Path, int]:
        state = Path(tempfile.mkdtemp(prefix="rig."))
        subprocess.run(
            [
                "swtpm", "socket", "--tpm2", "--daemon",
                "--tpmstate", f"dir={state}",
                "--ctrl", f"type=unixio,path={state / 's'}",
                "--pid", f"file={state / 'pid'}",
            ],
            check=True,
        )  # fmt: skip
        for _ in range(50):
            if (state / "s").is_socket() and (state / "pid").exists():
                return state, int((state / "pid").read_text())
            time.sleep(0.1)
        raise SystemExit(f"swtpm did not start in {state}")

    @staticmethod
    def _stop_swtpm(state: Path, pid: int) -> None:
        _signal(pid, str(state), signal.SIGTERM)
        shutil.rmtree(state, ignore_errors=True)

    @staticmethod
    def _stage_drivers(virtio: Path) -> Path:
        """The guest's virtio drivers, one folder each, for Packer's CD."""
        if _sha256(virtio) != VIRTIO_SHA256:
            raise SystemExit(
                f"{virtio} is not virtio-win 0.1.302 (SHA256 {VIRTIO_SHA256})"
            )
        drivers = RUN / "build" / "drivers"
        shutil.rmtree(drivers, ignore_errors=True)
        drivers.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as unpacked:
            # Whole: most drivers are hard links into the ISO's other folders.
            subprocess.run(["bsdtar", "-xf", str(virtio), "-C", unpacked], check=True)
            # An ISO's folders come out read-only, and nothing could delete them.
            subprocess.run(["chmod", "-R", "u+w", unpacked], check=True)
            for driver in VIRTIO_DRIVERS:
                shutil.copytree(
                    Path(unpacked, driver, "w11", "ARM64"), drivers / driver
                )
        return drivers

    def build(self, iso: Path, virtio: Path, show: bool, on_error: str) -> None:
        drivers = self._stage_drivers(virtio)
        _prefetch(self.arch)
        public_key = _ssh_key()
        sources = _tree_sha256(*BASE_SOURCES)

        output = RUN / "base.new"
        shutil.rmtree(output, ignore_errors=True)
        packer = HERE / "packer"
        subprocess.run(["packer", "init", str(packer)], check=True)
        variables = {
            "iso_path": iso,
            "drivers_dir": drivers,
            "downloads_dir": DOWNLOADS,
            "qemu_binary": HERE / "scripts" / "qemu-with-tpm.sh",
            "efi_firmware_code": self.efi_code,
            "efi_firmware_vars": self.efi_vars,
            "output_directory": output,
            "ssh_public_key": public_key,
            "headless": str(not show).lower(),
        }
        state, swtpm = self._start_swtpm()
        try:
            build = subprocess.Popen(
                [
                    "packer", "build", f"-on-error={on_error}",
                    *(f"-var={name}={value}" for name, value in variables.items()),
                    str(packer),
                ],
                env={**os.environ, "SWTPM_SOCK": str(state / "s")},
            )  # fmt: skip
            try:
                returncode = build.wait()
            except KeyboardInterrupt:
                # Packer had the terminal's interrupt too, and stops its VM.
                build.wait()
                raise
        finally:
            self._stop_swtpm(state, swtpm)
        if returncode != 0:
            raise SystemExit(f"packer build exited {returncode}")

        # Every channel layer is backed by the old base, which is going.
        shutil.rmtree(CHANNELS, ignore_errors=True)
        shutil.rmtree(BASE, ignore_errors=True)
        output.rename(BASE)
        (BASE / "efivars.fd").rename(_vars(BASE / "base.qcow2"))
        built = {
            "id": uuid.uuid4().hex,
            "built": datetime.now(UTC).date().isoformat(),
            "sources": sources,
        }
        (BASE / "built.json").write_text(json.dumps(built))

    def create_layer(self, layer: Path, backing: Path) -> None:
        """A qcow2 at `layer` over `backing`, with its own copy of the EFI variables."""
        layer.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "qemu-img",
                "create",
                "-q",
                "-f",
                "qcow2",
                "-F",
                "qcow2",
                "-b",
                str(backing),
                str(layer),
            ],
            check=True,
        )
        shutil.copyfile(_vars(backing), _vars(layer))

    def start(
        self, layer: Path, forwards: dict[int, int], show: bool, record: Path
    ) -> dict[str, Any]:
        """Boot `layer` in the background, forwarding each host port on the
        loopback interface to its guest port. What `stop` needs is written to
        `record` before anything else can go wrong, and returned.
        """
        state, swtpm = self._start_swtpm()
        hostfwd = ",".join(
            f"hostfwd=tcp:127.0.0.1:{host}-:{guest}" for host, guest in forwards.items()
        )
        log = layer.with_suffix(".log")
        qemu = subprocess.Popen(
            [
                "qemu-system-aarch64",
                "-machine", "virt,gic-version=max", "-accel", "hvf", "-cpu", "host",
                "-smp", "8", "-m", "16G",
                "-drive", f"if=pflash,format=raw,readonly=on,file={self.efi_code}",
                "-drive", f"if=pflash,format=raw,file={_vars(layer)}",
                "-chardev", f"socket,id=chrtpm,path={state / 's'}",
                "-tpmdev", "emulator,id=tpm0,chardev=chrtpm",
                "-device", "tpm-tis-device,tpmdev=tpm0,ppi=off",
                # Windows draws on virtio-gpu once provisioning's viogpudo binds,
                # and can then take any resolution; Setup needed ramfb.
                "-device", "virtio-gpu-pci",
                "-device", "qemu-xhci,id=usb",
                "-device", "usb-kbd,bus=usb.0",
                "-device", "usb-tablet,bus=usb.0",
                "-drive", f"file={layer},if=virtio,format=qcow2,cache=writeback,aio=threads",
                "-device", "virtio-net-pci,netdev=net0",
                "-netdev", f"user,id=net0,{hostfwd}",
                "-display", "cocoa,zoom-to-fit=on" if show else "none",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log.open("w"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )  # fmt: skip
        handle = {
            "qemu": qemu.pid,
            "layer": str(layer),
            "swtpm": swtpm,
            "tpm": str(state),
        }
        record.write_text(json.dumps(handle))
        # A forwarded port already in use stops QEMU at once.
        time.sleep(2)
        if qemu.poll() is not None:
            self._stop_swtpm(state, swtpm)
            record.unlink()
            raise SystemExit(f"QEMU exited at start:\n{log.read_text().strip()}")
        return handle

    @staticmethod
    def running(handle: dict[str, Any]) -> bool:
        _reap(handle["qemu"])
        return _ours(handle["qemu"], handle["layer"])

    def stop(self, handle: dict[str, Any], ssh_port: int, timeout: float = 180) -> bool:
        """Shut the guest down, or kill it if it will not go; whether it went
        cleanly.
        """
        clean = True
        if self.running(handle):
            # 255 is ssh's own failure: with nothing listening, nobody will shut down.
            asked = _ssh(ssh_port, "Stop-Computer -Force", quiet=True) != 255
            deadline = time.monotonic() + (timeout if asked else 10)
            while self.running(handle) and time.monotonic() < deadline:
                time.sleep(2)
            if self.running(handle):
                _signal(handle["qemu"], handle["layer"], signal.SIGKILL)
                clean = False
        self._stop_swtpm(Path(handle["tpm"]), handle["swtpm"])
        return clean


def _vars(layer: Path) -> Path:
    """The EFI variables that boot `layer`."""
    return layer.with_name(f"{layer.stem}-vars.fd")


def backend() -> QemuBackend:
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return QemuBackend()
    raise SystemExit(
        "rig.py has a backend only for macOS on Apple silicon. Elsewhere, run "
        "tools/windows-rig/provision/provision.ps1 in a Windows VM of your own (docs/test-vm.md, W-08)."
    )


# ── commands ──────────────────────────────────────────────────────────────────


def _built() -> dict[str, Any]:
    built = _read_json(BASE / "built.json")
    if built is None:
        raise SystemExit("no base image; run `rig.py build`")
    return built


def _channels() -> dict[str, Any]:
    return tomllib.loads((HERE / "channels.toml").read_text())


def _no_session(rig: QemuBackend) -> None:
    """Refuse while a session runs; forget one whose VM has gone."""
    session = _read_json(SESSION / "session.json")
    if session is None:
        return
    if rig.running(session["handle"]):
        raise SystemExit("the rig is up; run `rig.py down` first")
    rig.stop(session["handle"], session["ports"]["ssh"])
    shutil.rmtree(SESSION, ignore_errors=True)


def cmd_build(args: argparse.Namespace) -> None:
    rig = backend()
    _no_session(rig)
    rig.build(args.iso.resolve(), args.virtio.resolve(), args.show, args.on_error)
    print(f"built {BASE / 'base.qcow2'}")


def _wanted(channel: str) -> dict[str, Any]:
    """The stamp a current layer of `channel` carries: its base, its pins and
    the script that installed it.
    """
    pins = channel_pins(_channels(), channel)
    return {"base": _built()["id"], "pins": pins, "installer": _sha256(INSTALLER)}


def install(rig: QemuBackend, channel: str, ports: Ports) -> None:
    wanted = _wanted(channel)
    layer = CHANNELS / f"{channel}.new.qcow2"
    record = CHANNELS / f"{channel}.new.json"
    if stale := _read_json(record):
        rig.stop(stale, ports.ssh)
    rig.create_layer(layer, BASE / "base.qcow2")
    handle = rig.start(layer, {ports.ssh: 22}, show=False, record=record)
    clean = False
    try:
        _wait_for_ssh(ports.ssh, lambda: rig.running(handle))
        with tempfile.TemporaryDirectory() as tmp:
            pinned = Path(tmp, "channel.json")
            pinned.write_text(json.dumps(wanted["pins"]))
            _scp(ports.ssh, [INSTALLER, pinned], "C:/rig/")
        returncode = _ssh(
            ports.ssh,
            r"& C:\rig\install-nina.ps1 -Channel C:\rig\channel.json; exit $LASTEXITCODE",
        )
        if returncode == 3010:
            # An installer left work for a restart; done now, not in every session.
            _ssh(ports.ssh, "Restart-Computer -Force", quiet=True)
            time.sleep(30)
            _wait_for_ssh(ports.ssh, lambda: rig.running(handle))
        elif returncode != 0:
            raise SystemExit(f"install-nina.ps1 exited {returncode}")
        _ssh(ports.ssh, r"Remove-Item C:\rig\install-nina.ps1, C:\rig\channel.json")
    finally:
        clean = rig.stop(handle, ports.ssh)
        record.unlink(missing_ok=True)
    if not clean:
        raise SystemExit(
            "the guest did not shut down, so its layer may be missing writes; run install again"
        )
    final = CHANNELS / f"{channel}.qcow2"
    layer.rename(final)
    _vars(layer).rename(_vars(final))
    (CHANNELS / f"{channel}.json").write_text(json.dumps(wanted))
    print(f"installed {channel}: N.I.N.A. {wanted['pins']['nina']['version']}")


def cmd_install(args: argparse.Namespace) -> None:
    rig = backend()
    _no_session(rig)
    install(rig, args.channel, Ports())


def cmd_up(args: argparse.Namespace) -> None:
    rig = backend()
    _no_session(rig)
    built = _built()
    if verdict := age_verdict(
        date.fromisoformat(built["built"]), datetime.now(UTC).date()
    ):
        refuse, message = verdict
        if refuse:
            raise SystemExit(message)
        print(f"warning: {message}", file=sys.stderr)
    if built.get("sources") != _tree_sha256(*BASE_SOURCES):
        print(
            "warning: packer/, provision/ or tests/fixtures/rig/ changed after the base image was built; "
            "run `rig.py build` to pick the change up",
            file=sys.stderr,
        )

    ports = Ports(ssh=args.ssh_port, rdp=args.rdp_port, api=args.api_port)
    if _read_json(CHANNELS / f"{args.channel}.json") != _wanted(args.channel):
        install(rig, args.channel, ports)

    SESSION.mkdir(parents=True, exist_ok=True)
    layer = SESSION / "run.qcow2"
    rig.create_layer(layer, CHANNELS / f"{args.channel}.qcow2")
    record = SESSION / "session.json"
    handle = rig.start(
        layer, {ports.ssh: 22, ports.rdp: 3389, ports.api: 1888}, args.show, record
    )
    record.write_text(
        json.dumps({"channel": args.channel, "ports": asdict(ports), "handle": handle})
    )
    print(f"up: {args.channel}; SSH on {ports.ssh}, RDP on {ports.rdp}")
    print(f"127.0.0.1:{ports.api}")


def _api(port: int, path: str, timeout: float = 30) -> Any:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{port}/v2/api{path}", timeout=timeout
    ) as response:
        return json.loads(response.read())


def _poll[T](
    what: str, check: Callable[[], T | None], timeout: float, interval: float = 3
) -> T:
    deadline = time.monotonic() + timeout
    while True:
        with contextlib.suppress(OSError, ValueError, KeyError):
            if (result := check()) is not None:
                return result
        if time.monotonic() > deadline:
            raise SystemExit(f"timed out waiting for {what}")
        time.sleep(interval)


def _connected(port: int, device: str) -> dict[str, Any] | None:
    """The device's info if it reads connected; `None` otherwise, an error
    reply included.
    """
    try:
        info = _api(port, f"/equipment/{device}/info").get("Response")
    except OSError, ValueError:
        return None
    return info if isinstance(info, dict) and info.get("Connected") else None


def _connect(port: int, device: str, timeout: float = 180) -> dict[str, Any]:
    """Connect `device` and return its info once it reads connected.

    A command returns when N.I.N.A. accepts it, so the connection is read back
    from the device's info, and the command is sent again until it holds: one
    sent while N.I.N.A. is still listing drivers at start-up does nothing.
    """

    def attempt() -> dict[str, Any] | None:
        if info := _connected(port, device):
            return info
        reply = _api(port, f"/equipment/{device}/connect", timeout=120)
        if not reply.get("Success"):
            print(f"{device}: {reply.get('Error')}", file=sys.stderr)
        return None

    return _poll(f"the {device} to connect", attempt, timeout, interval=10)


def cmd_wait(args: argparse.Namespace) -> None:
    session = _read_json(SESSION / "session.json")
    if session is None:
        raise SystemExit("the rig is not up")
    port = session["ports"]["api"]
    started = time.monotonic()
    version = _poll(
        "the Advanced API", lambda: _api(port, "/version")["Response"], args.timeout
    )
    print(f"Advanced API {version} after {time.monotonic() - started:.0f}s")
    for device in DEVICES:
        info = _connect(port, device)
        print(f"{device:<14} {info.get('DeviceId') or '-':<40} {info.get('Name')}")
    print(
        f"all {len(DEVICES)} devices connected after {time.monotonic() - started:.0f}s"
    )


def cmd_down(args: argparse.Namespace) -> None:
    session = _read_json(SESSION / "session.json")
    if session is not None:
        backend().stop(session["handle"], session["ports"]["ssh"])
    shutil.rmtree(SESSION, ignore_errors=True)
    print("down")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="build the base image with Packer")
    for flag, variable in (
        ("--iso", "RIG_WINDOWS_ISO"),
        ("--virtio", "RIG_VIRTIO_ISO"),
    ):
        build.add_argument(
            flag,
            type=Path,
            default=os.environ.get(variable),
            required=variable not in os.environ,
        )
    build.add_argument("--show", action="store_true", help="show the guest's display")
    build.add_argument(
        "--on-error", default="cleanup", choices=("cleanup", "abort", "ask")
    )
    build.set_defaults(func=cmd_build)

    install_ = commands.add_parser("install", help="create or refresh a channel layer")
    install_.add_argument("channel", choices=("stable",))
    install_.set_defaults(func=cmd_install)

    up = commands.add_parser("up", help="start a session on a channel")
    up.add_argument("channel", choices=("stable",))
    up.add_argument("--show", action="store_true", help="show the guest's display")
    up.add_argument("--ssh-port", type=int, default=Ports.ssh)
    up.add_argument("--rdp-port", type=int, default=Ports.rdp)
    up.add_argument("--api-port", type=int, default=Ports.api)
    up.set_defaults(func=cmd_up)

    wait = commands.add_parser(
        "wait", help="wait for the API, then connect every device"
    )
    wait.add_argument(
        "--timeout", type=float, default=900, help="seconds to wait for the API"
    )
    wait.set_defaults(func=cmd_wait)

    down = commands.add_parser("down", help="stop the session and discard it")
    down.set_defaults(func=cmd_down)

    args = parser.parse_args()
    # Its progress interleaves with Packer's and SSH's, often into a log.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)
    args.func(args)


if __name__ == "__main__":
    main()

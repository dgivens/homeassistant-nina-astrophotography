"""Stand up a throwaway Home Assistant in Docker, install one version of the
integration against a N.I.N.A., and upgrade it in place to another.

    uv run python tools/upgrade-harness/harness.py up --ref origin/main
    uv run python tools/upgrade-harness/harness.py snapshot before
    uv run python tools/upgrade-harness/harness.py upgrade --ref origin/v2
    uv run python tools/upgrade-harness/harness.py snapshot after
    uv run python tools/upgrade-harness/harness.py check before after
    uv run python tools/upgrade-harness/harness.py down

Everything lives under `tools/upgrade-harness/.run/` (git-ignored): the
container's `/config`, the access token, and the snapshots. The instance is
onboarded through its own onboarding API, so no step needs a browser.

Point it only at the simulator rig: setting an entry up polls every endpoint,
and a check that goes further may command equipment.
"""

import argparse
import asyncio
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import time
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
RUN = Path(__file__).resolve().parent / ".run"
STATE = RUN / "state.json"
RENAMES = ROOT / "docs" / "2.0-renames.md"

DOMAIN = "nina_astrophotography"
CONTAINER = "nina-upgrade-harness"
IMAGE = "ghcr.io/home-assistant/home-assistant:2026.9.0"
PORT = 8124
BASE = f"http://127.0.0.1:{PORT}"
CLIENT_ID = f"{BASE}/"
SIM_HOST = "10.20.30.133"
SIM_PORT = 1888


# ── the container ─────────────────────────────────────────────────────────────


def _docker(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False
    )
    if check and result.returncode != 0:
        raise SystemExit(f"docker {args[0]} failed: {result.stderr.strip()}")
    return result


def _config() -> Path:
    """This run's `/config`.

    Named per run: Docker Desktop's file sharing can serve a directory deleted
    and recreated within seconds as missing, and the container then fails to
    start or Home Assistant exits unable to create `/config/deps`.
    """
    return Path(json.loads(STATE.read_text())["config"])


def _install(ref: str) -> None:
    """Replace the integration in `/config` with the one at git `ref`."""
    config = _config()
    target = config / "custom_components" / DOMAIN
    shutil.rmtree(target, ignore_errors=True)
    archive = subprocess.run(
        ["git", "archive", ref, f"custom_components/{DOMAIN}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(config, filter="data")
    manifest = json.loads((target / "manifest.json").read_text())
    print(f"installed {DOMAIN} {manifest['version']} from {ref}")


async def _wait_for_http(session: aiohttp.ClientSession, timeout: float = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            # Served without a token, before and after onboarding alike.
            async with session.get(f"{BASE}/manifest.json") as resp:
                if resp.status == 200:
                    return
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(2)
    raise TimeoutError(f"Home Assistant did not answer on {BASE}")


# ── onboarding and the API ────────────────────────────────────────────────────


async def _token(session: aiohttp.ClientSession, auth_code: str) -> str:
    async with session.post(
        f"{BASE}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": CLIENT_ID,
        },
    ) as resp:
        resp.raise_for_status()
        return (await resp.json())["access_token"]


async def _onboard(session: aiohttp.ClientSession) -> str:
    """Create the owner, finish onboarding, and mint a long-lived token."""
    async with session.post(
        f"{BASE}/api/onboarding/users",
        json={
            "client_id": CLIENT_ID,
            "name": "Harness",
            "username": "harness",
            "password": "harness-password",
            "language": "en",
        },
    ) as resp:
        resp.raise_for_status()
        access = await _token(session, (await resp.json())["auth_code"])
    headers = {"Authorization": f"Bearer {access}"}
    for step, body in (
        ("core_config", {}),
        ("analytics", {}),
        ("integration", {"client_id": CLIENT_ID, "redirect_uri": f"{BASE}/"}),
    ):
        async with session.post(
            f"{BASE}/api/onboarding/{step}", json=body, headers=headers
        ) as resp:
            resp.raise_for_status()
    result = await _ws(
        session,
        access,
        {
            "type": "auth/long_lived_access_token",
            "client_name": "upgrade-harness",
            "lifespan": 30,
        },
    )
    return result[0]


async def _ws(
    session: aiohttp.ClientSession, token: str, *commands: dict[str, Any]
) -> list[Any]:
    """Run websocket commands in order and return each one's result."""
    async with session.ws_connect(f"{BASE}/api/websocket") as ws:
        await ws.receive_json()  # auth_required
        await ws.send_json({"type": "auth", "access_token": token})
        reply = await ws.receive_json()
        if reply["type"] != "auth_ok":
            raise RuntimeError(f"websocket auth failed: {reply}")
        results = []
        for number, command in enumerate(commands, start=1):
            await ws.send_json({"id": number, **command})
            while True:
                message = await ws.receive_json()
                if message.get("id") == number and message["type"] == "result":
                    break
            if not message["success"]:
                raise RuntimeError(f"{command['type']} failed: {message['error']}")
            results.append(message["result"])
        return results


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {json.loads(STATE.read_text())['token']}"}


async def _add_entry(session: aiohttp.ClientSession, host: str, port: int) -> None:
    """Run the config flow with only the host and port, so the schema's own
    defaults fill every other field whichever version is installed.
    """
    async with session.post(
        f"{BASE}/api/config/config_entries/flow",
        json={"handler": DOMAIN, "show_advanced_options": False},
        headers=_headers(),
    ) as resp:
        resp.raise_for_status()
        flow = await resp.json()
    async with session.post(
        f"{BASE}/api/config/config_entries/flow/{flow['flow_id']}",
        json={"host": host, "port": port},
        headers=_headers(),
    ) as resp:
        resp.raise_for_status()
        result = await resp.json()
    if result["type"] != "create_entry":
        raise RuntimeError(f"config flow did not create an entry: {result}")
    print(f"added entry {result['result']['title']!r}")


async def _wait_for_entry(session: aiohttp.ClientSession, timeout: float = 120) -> None:
    """Wait until the entry has loaded and its entities have settled."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with session.get(
            f"{BASE}/api/config/config_entries/entry", headers=_headers()
        ) as resp:
            if resp.status == 200:
                entries = [e for e in await resp.json() if e["domain"] == DOMAIN]
                if entries and all(e["state"] == "loaded" for e in entries):
                    # A tier or two of polling, so first-sight entities exist.
                    await asyncio.sleep(30)
                    return
                if any(
                    e["state"] in ("setup_error", "migration_error") for e in entries
                ):
                    raise RuntimeError(f"entry failed to load: {entries}")
        await asyncio.sleep(2)
    raise TimeoutError("the entry did not load")


# ── commands ──────────────────────────────────────────────────────────────────


async def up(ref: str, image: str, host: str, port: int) -> None:
    if _docker("inspect", CONTAINER, check=False).returncode == 0:
        raise SystemExit(f"{CONTAINER} already exists; run `down` first")
    _clear()
    config = RUN / f"config-{time.time_ns()}"
    config.mkdir(parents=True)
    STATE.write_text(json.dumps({"config": str(config)}))
    _install(ref)
    _docker(
        "run", "-d", "--name", CONTAINER,
        "-p", f"{PORT}:8123",
        "-v", f"{config}:/config",
        "-e", "TZ=America/Chicago",
        image,
    )  # fmt: skip
    async with aiohttp.ClientSession() as session:
        await _wait_for_http(session)
        token = await _onboard(session)
        STATE.write_text(json.dumps({"config": str(config), "token": token}))
        await _add_entry(session, host, port)
        await _wait_for_entry(session)
    print(f"up: {BASE} (harness / harness-password)")


async def upgrade(ref: str) -> None:
    _install(ref)
    _docker("restart", CONTAINER)
    async with aiohttp.ClientSession() as session:
        await _wait_for_http(session)
        await _wait_for_entry(session)
    print("upgraded")


async def snapshot(name: str) -> None:
    token = json.loads(STATE.read_text())["token"]
    async with aiohttp.ClientSession() as session:
        entities, devices, states, entries = await _ws(
            session,
            token,
            {"type": "config/entity_registry/list"},
            {"type": "config/device_registry/list"},
            {"type": "get_states"},
            {"type": "config_entries/get", "domain": DOMAIN},
        )
    ours = [e for e in entities if e["platform"] == DOMAIN]
    record = {
        "entries": entries,
        "entities": ours,
        "devices": [
            d for d in devices if any(i[0] == DOMAIN for i in d["identifiers"])
        ],
        "states": {
            s["entity_id"]: s
            for s in states
            if s["entity_id"] in {e["entity_id"] for e in ours}
        },
    }
    path = RUN / f"{name}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    print(f"{name}: {len(ours)} entities, {len(record['devices'])} devices -> {path}")


def _renames() -> tuple[dict[str, str], dict[str, str]]:
    """What `docs/2.0-renames.md` says 2.0 does with each 1.4.5 entity: a new
    id, or `removed`.

    Keyed two ways: by 1.4.5 entity id, one row each, and by `unique_id`
    suffix, which is how a row's "Why" names the siblings it stands for ("Same
    for `_frame_last_max_adu`").
    """
    by_id: dict[str, str] = {}
    by_suffix: dict[str, str] = {}
    for line in RENAMES.read_text().splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not re.fullmatch(r"`[a-z_]+\.[a-z0-9_]+`", cells[0]):
            continue
        fate = "removed" if cells[1].strip("*").startswith("removed") else cells[1]
        by_id[cells[0].strip("`")] = fate.strip("`")
        for suffix in re.findall(r"`_([a-z0-9_]+)`", cells[2]):
            by_suffix.setdefault(suffix, fate.strip("`"))
    return by_id, by_suffix


def _live(state: dict[str, Any] | None) -> bool:
    return state is not None and not state["attributes"].get("restored")


def check(before_name: str, after_name: str) -> None:
    """Hold an upgrade to the promises `docs/2.0-renames.md` makes.

    Every 1.4.5 row keeps its entity id; one the doc marks removed is left an
    orphan, and every other is still backed by an entity after the upgrade.
    """
    before = json.loads((RUN / f"{before_name}.json").read_text())
    after = json.loads((RUN / f"{after_name}.json").read_text())
    by_id, by_suffix = _renames()
    after_by_uid = {e["unique_id"]: e for e in after["entities"]}
    after_devices = {d["id"]: d["name_by_user"] or d["name"] for d in after["devices"]}
    problems: list[str] = []
    for old in sorted(before["entities"], key=lambda e: e["entity_id"]):
        eid = old["entity_id"]
        new = after_by_uid.get(old["unique_id"])
        suffix = old["unique_id"].removeprefix(f"{old['config_entry_id']}_")
        fate = by_id.get(eid, by_suffix.get(suffix))
        if fate is None:
            problems.append(f"{eid}: not in docs/2.0-renames.md")
        if new is None:
            problems.append(f"{eid}: its registry row is gone")
            continue
        if new["entity_id"] != eid:
            problems.append(f"{eid}: renamed to {new['entity_id']}")
        device = after_devices.get(new["device_id"], "no device")
        if new["disabled_by"]:
            # A disabled row has no state to tell an orphan from a survivor.
            print(f"off    {eid:70} {device}")
            continue
        live = _live(after["states"].get(new["entity_id"]))
        if fate == "removed" and live:
            problems.append(
                f"{eid}: the doc says removed, but an entity still backs it"
            )
        if fate not in (None, "removed") and not live:
            problems.append(f"{eid}: the doc says it survives, but nothing backs it")
        print(f"{'live  ' if live else 'orphan'} {eid:70} {device}")
    new_rows = {e["unique_id"] for e in after["entities"]} - {
        e["unique_id"] for e in before["entities"]
    }
    print(
        f"\n{len(before['entities'])} rows before, {len(new_rows)} new after the upgrade"
    )
    print("\n".join(problems) or "every 1.4.5 row matches docs/2.0-renames.md")
    if problems:
        raise SystemExit(1)


def _clear() -> None:
    """Empty `.run/` but keep the directory: sharing a freshly recreated parent
    into a container is what Docker Desktop gets wrong.
    """
    RUN.mkdir(exist_ok=True)
    for child in RUN.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def down() -> None:
    _docker("rm", "-f", CONTAINER, check=False)
    _clear()
    print("down")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("up", help="start Home Assistant and add the rig")
    start.add_argument("--ref", default="origin/main", help="git ref to install")
    start.add_argument("--image", default=IMAGE)
    start.add_argument("--host", default=SIM_HOST)
    start.add_argument("--port", type=int, default=SIM_PORT)
    move = commands.add_parser("upgrade", help="install another ref and restart")
    move.add_argument("--ref", default="origin/v2")
    take = commands.add_parser("snapshot", help="record the registry and states")
    take.add_argument("name")
    compare = commands.add_parser("check", help="hold an upgrade to the renames doc")
    compare.add_argument("before")
    compare.add_argument("after")
    commands.add_parser("down", help="remove the container and everything in .run/")
    args = parser.parse_args()

    if args.command == "up":
        asyncio.run(up(args.ref, args.image, args.host, args.port))
    elif args.command == "upgrade":
        asyncio.run(upgrade(args.ref))
    elif args.command == "snapshot":
        asyncio.run(snapshot(args.name))
    elif args.command == "check":
        check(args.before, args.after)
    else:
        down()


if __name__ == "__main__":
    main()

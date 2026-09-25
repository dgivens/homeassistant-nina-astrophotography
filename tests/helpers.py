"""Test doubles for the N.I.N.A. HTTP API, the captured-fixture loader, and a
runner for the shipped `www/` modules under node.

`responses` maps a path fragment to a payload, a FakeResponse, or an exception
to raise; the first fragment found in the URL wins, so register the more
specific fragment first. `default` covers everything else.

`run_node` runs a shipped `www/` module under node, through a driver script that
reads its input from a JSON file and prints its result as JSON.

Imports neither Home Assistant nor the integration at runtime, so both suites
can use it.
"""

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant, State

FIXTURES = Path(__file__).resolve().parent / "fixtures"

needs_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="needs node to run a shipped www/ module"
)


class FakeResponse:
    """Stands in for an aiohttp response."""

    def __init__(
        self, payload, status: int = 200, content_type: str = "application/json"
    ):
        self._payload = payload
        self.status = status
        self.content_type = content_type

    async def json(self, **_kwargs):
        if isinstance(self._payload, (dict, list)):
            return self._payload
        return json.loads(self._payload)

    async def read(self):
        return (
            self._payload
            if isinstance(self._payload, bytes)
            else str(self._payload).encode()
        )

    async def text(self):
        return (
            self._payload
            if isinstance(self._payload, str)
            else json.dumps(self._payload)
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class FakeSession:
    """Minimal aiohttp.ClientSession stand-in.

    `responses` maps a path fragment to a payload, a FakeResponse, or an
    exception to raise. `default` covers everything else.
    """

    def __init__(self, responses=None, default=None):
        self.responses = responses or {}
        self.default = default if default is not None else ok()
        self.requests: list[tuple[str, dict | None]] = []

    def _respond(self, url, params=None):
        self.requests.append((url, params))
        value = next(
            (v for fragment, v in self.responses.items() if fragment in url),
            self.default,
        )
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, FakeResponse) else FakeResponse(value)

    def get(self, url, params=None, timeout=None):
        return self._respond(url, params)

    def post(self, url, json=None, params=None, timeout=None):
        return self._respond(url, params)


def ok(response=None):
    """A successful N.I.N.A. envelope."""
    return {
        "Response": {} if response is None else response,
        "Error": "",
        "StatusCode": 200,
        "Success": True,
        "Type": "API",
    }


def failure(error="Camera not connected", status=409):
    """A failed N.I.N.A. envelope. Note the HTTP status is still 200."""
    return {
        "Response": "",
        "Error": error,
        "StatusCode": status,
        "Success": False,
        "Type": "API",
    }


def _read(name: str) -> Any:
    """A captured document, re-read on every call so a caller may edit it."""
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_envelope(name: str) -> dict:
    """A captured envelope as the wire sent it, less our own `_meta` block."""
    document = _read(name)
    document.pop("_meta", None)
    return document


def load_fixture(name: str) -> Any:
    """The `Response` of a captured envelope — the payload the mappers take.

    A capture with no envelope around it (`image_history_session.json` is a
    bare list) is returned as it stands, as is a document with no `Response`.
    """
    document = _read(name)
    if not isinstance(document, dict):
        return document
    document.pop("_meta", None)
    return document.get("Response", document)


def state_of(hass: HomeAssistant, entity_id: str) -> State:
    """The entity's current state, failing the test if it has none."""
    state = hass.states.get(entity_id)
    assert state is not None, f"{entity_id} has no state"
    return state


def run_node(driver: Path, payload: Any, *args: str) -> Any:
    """`node driver <payload.json> *args`, its stdout parsed as JSON."""
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "payload.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            ["node", str(driver), str(path), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode:
        pytest.fail(f"node {driver.name} exited {result.returncode}:\n{result.stderr}")
    return json.loads(result.stdout)

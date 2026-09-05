"""Test doubles for the N.I.N.A. HTTP API, and the captured-fixture loader.

`responses` maps a path fragment to a payload, a FakeResponse, or an exception
to raise; the first fragment found in the URL wins, so register the more
specific fragment first. `default` covers everything else.

Imports neither Home Assistant nor the integration, so both suites can use it.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class FakeResponse:
    """Stands in for an aiohttp response."""

    def __init__(self, payload, status: int = 200, content_type: str = "application/json"):
        self._payload = payload
        self.status = status
        self.content_type = content_type

    async def json(self, **_kwargs):
        if isinstance(self._payload, (dict, list)):
            return self._payload
        return json.loads(self._payload)

    async def read(self):
        return self._payload if isinstance(self._payload, bytes) else str(self._payload).encode()

    async def text(self):
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)

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


def load_envelope(name: str) -> dict:
    """A captured envelope as the wire sent it, less our own `_meta` block.

    Re-read from disk on every call, so a test may edit what it gets back.
    """
    document = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    document.pop("_meta", None)
    return document


def load_fixture(name: str) -> Any:
    """The `Response` of a captured envelope — the payload the mappers take."""
    return load_envelope(name)["Response"]

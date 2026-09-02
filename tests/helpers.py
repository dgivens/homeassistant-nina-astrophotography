"""Test doubles for the N.I.N.A. HTTP API.

`responses` maps a path fragment to a payload, a FakeResponse, or an exception
to raise; the first fragment found in the URL wins, so register the more
specific fragment first. `default` covers everything else.
"""
from __future__ import annotations

import json


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

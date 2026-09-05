"""A fake N.I.N.A. rig, at the transport level.

`FakeRig` answers requests from one named state at a time, so the real
`NinaClientV2` runs above it: envelope classification, the `"NaN"` rule and the
wire→model mapper all run against captured bytes. `goto()` moves to a state;
`advance()` walks an ordered sequence.

Dispatch is on the path AND its single query parameter, because three endpoints
answer differently by parameter — `/image-history` bare, `?count=true` and
`?all=true` — and matching the path alone cannot tell them apart. Parameters do
not appear in the URL: the client passes them to `session.get` separately.

Imports nothing from Home Assistant: `tests/unit` uses this too.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from helpers import FakeResponse, FakeSession, ok

_PREFIX = "/v2/api"

# Every path under these roots commands equipment except the reads named
# below — `/equipment/mount/info`, `/sequence/json`, `/flats/status`,
# `/equipment/focuser/last-af`. A command is recorded and answered
# `Success: true`: no command on this API can be confirmed from its own
# response, so no state carries one and the poll reads the result back.
_COMMAND_ROOTS = ("/equipment/", "/sequence/", "/flats/", "/livestack/", "/application/")
_READ_SEGMENTS = frozenset({"info", "json", "last-af", "show", "state", "status"})

# What EmbedIO answers for a route it does not serve: HTML, not an envelope.
_NOT_FOUND = "<html>404</html>"


def _is_command(path: str) -> bool:
    return path.startswith(_COMMAND_ROOTS) and path.rsplit("/", 1)[-1] not in _READ_SEGMENTS


class FakeRig(FakeSession):
    """Serves one state of a catalogue, keyed by (path, single parameter).

    A path the current state does not name answers 404, so an endpoint missing
    from a state fails loud as `NinaEndpointError` rather than quietly
    succeeding with an empty envelope.
    """

    def __init__(
        self,
        states: Mapping[str, Mapping[str, object]],
        start: str = "imaging",
        *,
        sequence: Iterable[str] | None = None,
    ) -> None:
        # Not FakeSession.__init__: its `responses`/`default` are the fragment
        # matcher this class replaces, and a second lookup table would rot.
        self.requests: list[tuple[str, dict | None]] = []
        self.states = states
        self._sequence = list(sequence or ())
        self.sent: list[tuple[str, dict | None]] = []
        self.state_name = ""
        self.goto(start)
        self._step = self._sequence.index(start) if start in self._sequence else -1

    def goto(self, name: str) -> None:
        if name not in self.states:
            raise KeyError(f"unknown rig state: {name!r}")
        self.state_name = name

    def advance(self) -> str:
        """Move to the next state of the ordered sequence, and name it."""
        if not self._sequence:
            raise RuntimeError("this FakeRig was built without a sequence")
        self._step += 1
        if self._step >= len(self._sequence):
            raise RuntimeError(f"the sequence ends at {self.state_name!r}")
        self.goto(self._sequence[self._step])
        return self.state_name

    def _lookup(self, path: str, params: dict | None):
        state = self.states[self.state_name]
        if params is not None and len(params) == 1:
            ((key, value),) = params.items()
            keyed = state.get(f"{path}?{key}={value}")
            if keyed is not None:
                return keyed
        if path in state:
            return state[path]
        # "*" is how a state answers every path the same way — an unreachable
        # rig refuses paths it has never been asked for.
        return state.get("*")

    def _respond(self, url, params=None):
        self.requests.append((url, params))
        path = url.split(_PREFIX, 1)[-1] if _PREFIX in url else url
        value = self._lookup(path, params)
        if _is_command(path):
            self.sent.append((path, params))
            if value is None:
                value = ok()
        if value is None:
            return FakeResponse(_NOT_FOUND, status=404, content_type="text/html")
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, FakeResponse) else FakeResponse(value)

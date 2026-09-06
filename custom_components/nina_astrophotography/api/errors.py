"""The error taxonomy.

Subclasses builtins only — never HomeAssistantError — so the fast suite stays
HA-free. Mapping to Home Assistant happens in __init__.py and coordinator.py.

Definitions are semantic, not HTTP: the Advanced API answers HTTP 200 for
almost everything and carries the real outcome in the envelope's StatusCode.
"""
from __future__ import annotations


class NinaError(Exception):
    """Base for everything the client raises."""

    retryable: bool = False


class NinaConnectionError(NinaError):
    """Socket refused, DNS failure, or timeout."""

    retryable = True


class NinaUnavailableError(NinaError):
    """Envelope 5xx, or N.I.N.A. answering while still starting up."""

    retryable = True


class NinaEndpointError(NinaError):
    """This N.I.N.A. build does not serve the requested capability.

    A wrong path never becomes right, so failing the config entry beats
    retrying forever.
    """


class NinaRequestError(NinaError):
    """The request itself was malformed.

    Only routing and parameter-binding failures produce a real 4xx, and those
    return EmbedIO's HTML error page rather than an envelope.
    """


class NinaCommandError(NinaError):
    """The handler ran and refused.

    Retryability depends on the command: `status_code` and `api_error` are the
    envelope's, never HTTP's. Note that the envelope's code alone cannot
    classify a failure — "Sequence is not initialized" is raised with 409 on
    seven routes and 400 on two.
    """

    def __init__(self, message: str, *, status_code: int | None = None,
                 api_error: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_error = api_error

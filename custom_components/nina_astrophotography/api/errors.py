"""The error taxonomy, by meaning rather than HTTP status: the API answers
HTTP 200 for almost everything, with the outcome in the envelope's StatusCode.

Builtin subclasses only, so `api/` stays free of Home Assistant.
"""


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
    """This N.I.N.A. build does not serve the requested route; retrying will
    not change that.
    """


class NinaRequestError(NinaError):
    """The request itself was malformed.

    Only routing and parameter-binding failures produce a real 4xx, and those
    return EmbedIO's HTML error page rather than an envelope.
    """


class NinaNoImageError(NinaError):
    """The rig has nothing to render at this index or for this stack, as an
    idle rig's empty image history does. Not an outage.
    """


class NinaCommandError(NinaError):
    """The handler ran and refused.

    `status_code` and `api_error` are the envelope's. The code alone does not
    classify a failure: "Sequence is not initialized" is 409 on some routes
    and 400 on others.
    """

    def __init__(
        self, message: str, *, status_code: int | None = None, api_error: str = ""
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.api_error = api_error

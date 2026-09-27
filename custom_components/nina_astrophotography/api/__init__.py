"""The client seam: nothing above it knows a wire format, and no dict crosses
it. The wire lives under `api/<version>/`.
"""

from .errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaError,
    NinaRequestError,
    NinaUnavailableError,
)

__all__ = [
    "NinaCommandError",
    "NinaConnectionError",
    "NinaEndpointError",
    "NinaError",
    "NinaRequestError",
    "NinaUnavailableError",
]

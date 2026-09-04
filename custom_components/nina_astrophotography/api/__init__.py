"""Version-independent client seam.

Nothing above this package knows a wire format, and no dict crosses this
boundary. Everything that does live under api/<version>/.
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

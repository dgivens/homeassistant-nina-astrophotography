"""The error taxonomy is semantic, not HTTP."""
import pytest

from nina_astrophotography.api.errors import (
    NinaCommandError,
    NinaConnectionError,
    NinaEndpointError,
    NinaError,
    NinaRequestError,
    NinaUnavailableError,
)


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (NinaConnectionError("refused"), True),
        (NinaUnavailableError("booting"), True),
        (NinaEndpointError("no such capability"), False),
        (NinaRequestError("malformed"), False),
    ],
)
def test_retryability_is_a_property_of_the_type(error: NinaError, retryable: bool) -> None:
    assert error.retryable is retryable


def test_command_error_carries_the_envelope_status_not_the_http_one() -> None:
    error = NinaCommandError("refused", status_code=409, api_error="Camera not connected")
    assert (error.status_code, error.api_error) == (409, "Camera not connected")


def test_errors_subclass_builtins_only() -> None:
    """api/ must stay importable without Home Assistant (§7.1)."""
    for cls in (NinaConnectionError, NinaUnavailableError, NinaEndpointError,
                NinaRequestError, NinaCommandError):
        assert all(base.__module__ in ("builtins", "nina_astrophotography.api.errors")
                   for base in cls.__mro__)

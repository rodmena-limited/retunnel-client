from __future__ import annotations

"""ReTunnel client exceptions."""

from functools import wraps
from typing import Any, Callable, TypeVar


class ReTunnelError(Exception):
    """Base exception for all ReTunnel errors."""


class ConnectionError(ReTunnelError):
    """Connection-related errors."""


class AuthenticationError(ReTunnelError):
    """Authentication-related errors."""


class TunnelError(ReTunnelError):
    """Tunnel creation/management errors."""


class ConfigurationError(ReTunnelError):
    """Configuration-related errors."""


class ProtocolError(ReTunnelError):
    """Protocol/message errors."""


class ProxyError(ReTunnelError):
    """Proxy-related errors."""


class ValidationError(ReTunnelError):
    """Input validation errors."""


class APIError(ReTunnelError):
    """API request errors."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


F = TypeVar("F", bound=Callable[..., Any])


def handle_api_error(func: F) -> F:
    """Decorator to handle API errors."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as e:
            raise APIError(f"API operation failed: {e!s}")

    return wrapper  # type: ignore[return-value]

"""ReTunnel client exceptions."""

from functools import wraps
from typing import Any, Callable, Optional, TypeVar


class ReTunnelError(Exception):
    """Base exception for all ReTunnel errors."""

    pass


class ConnectionError(ReTunnelError):
    """Connection-related errors."""

    pass


class AuthenticationError(ReTunnelError):
    """Authentication-related errors."""

    pass


class TunnelError(ReTunnelError):
    """Tunnel creation/management errors."""

    pass


class ConfigurationError(ReTunnelError):
    """Configuration-related errors."""

    pass


class ProtocolError(ReTunnelError):
    """Protocol/message errors."""

    pass


class ProxyError(ReTunnelError):
    """Proxy-related errors."""

    pass


class ValidationError(ReTunnelError):
    """Input validation errors."""

    pass


class APIError(ReTunnelError):
    """API request errors."""

    def __init__(self, message: str, status_code: Optional[int] = None):
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
            raise APIError(f"API operation failed: {str(e)}")

    return wrapper  # type: ignore[return-value]

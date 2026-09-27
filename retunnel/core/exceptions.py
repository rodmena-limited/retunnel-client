"""ReTunnel client exceptions."""

from __future__ import annotations


class ReTunnelError(Exception):
    """Base exception for all ReTunnel errors."""


class ConnectionError(ReTunnelError):
    """Connection-related errors."""


class AuthenticationError(ReTunnelError):
    """Authentication-related errors."""


class TunnelError(ReTunnelError):
    """Tunnel creation/management errors (transient: the client retries)."""


class TerminalError(ReTunnelError):
    """The server refused permanently; retrying cannot help.

    Carries the process exit code the CLI should use (69 EX_UNAVAILABLE for
    auth/availability refusals, 2 EX_USAGE for invalid requests).
    """

    def __init__(self, code: str, message: str, exit_code: int = 69) -> None:
        super().__init__(f"{message} [{code}]")
        self.code = code
        self.exit_code = exit_code


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

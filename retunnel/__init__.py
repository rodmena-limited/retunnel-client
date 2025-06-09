"""ReTunnel - Securely expose local servers to the internet."""

__version__ = "2.0.0"
__author__ = "ReTunnel Team"
__email__ = "support@retunnel.com"
__url__ = "https://retunnel.com"

from .client.client import ReTunnelClient, Tunnel, TunnelConfig
from .core.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ReTunnelError,
    TunnelError,
)

__all__ = [
    "ReTunnelClient",
    "Tunnel",
    "TunnelConfig",
    "ReTunnelError",
    "ConnectionError",
    "AuthenticationError",
    "TunnelError",
    "ConfigurationError",
    "__version__",
]

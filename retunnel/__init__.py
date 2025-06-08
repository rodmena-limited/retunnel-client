"""
ReTunnel - A placeholder package for ReTunnel services.

ReTunnel is a platform for securely exposing local servers to the internet.
This package serves as a placeholder for future ReTunnel client functionality.
"""

__version__ = "0.1.0"
__author__ = "ReTunnel Team"
__email__ = "support@retunnel.com"
__url__ = "https://retunnel.com"

from .client import ReTunnelClient, hello

__all__ = ["ReTunnelClient", "hello", "__version__"]

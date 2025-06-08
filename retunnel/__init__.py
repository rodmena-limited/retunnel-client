"""
ReTunnel - A placeholder package for ReTunnel services.

ReTunnel is a platform for securely exposing local servers to the internet.
This package serves as a placeholder for future ReTunnel client functionality.
"""

__version__ = "0.1.0"
__author__ = "ReTunnel Team"
__email__ = "support@retunnel.com"
__url__ = "https://retunnel.com"

from .client import start_client

__all__ = ["start_client", "__version__"]

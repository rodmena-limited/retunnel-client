"""ReTunnel client module."""

from .high_performance_model import HighPerformanceClient, Tunnel, TunnelConfig

ReTunnelClient = HighPerformanceClient  # Alias for backward compatibility

__all__ = ["ReTunnelClient", "Tunnel", "TunnelConfig"]

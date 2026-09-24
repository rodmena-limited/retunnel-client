"""
Client configuration management for ReTunnel

Handles ~/.retunnel.conf for storing authentication tokens
and server configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core import conf_store


@dataclass
class ClientConfig:
    """ReTunnel client configuration"""

    auth_token: str | None = None
    server_url: str = "wss://retunnel.net"  # WebSocket endpoint for tunnels
    api_url: str = "https://retunnel.net"  # REST API endpoint
    ssl_verify: bool = True  # Verify SSL certificates by default (#27)
    max_message_size: int = 10 * 1024 * 1024  # 10MB default (#29)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClientConfig:
        """Create config from dictionary"""
        # Handle missing fields for backward compatibility
        return cls(
            auth_token=data.get("auth_token"),
            server_url=data.get("server_url", "wss://retunnel.net"),
            api_url=data.get("api_url", "https://retunnel.net"),
            ssl_verify=data.get("ssl_verify", True),
            max_message_size=data.get("max_message_size", 10 * 1024 * 1024),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary"""
        return {
            "auth_token": self.auth_token,
            "server_url": self.server_url,
            "api_url": self.api_url,
            "ssl_verify": self.ssl_verify,
            "max_message_size": self.max_message_size,
        }


class ConfigManager:
    """Manages client configuration file"""

    def __init__(self, config_path: Path | None = None):
        """Initialize config manager

        Args:
            config_path: Path to config file. Defaults to ~/.retunnel.conf
        """
        if config_path is None:
            home = Path.home()
            config_path = home / ".retunnel.conf"

        self.config_path = config_path
        self._config: ClientConfig | None = None

    async def load(self) -> ClientConfig:
        """Load configuration; raises conf_store.ConfigUnreadable.

        A missing file yields defaults and is NOT created: reading never
        writes.
        """
        if self._config is not None:
            return self._config
        data = conf_store.read(self.config_path)
        self._config = ClientConfig.from_dict(data or {})
        return self._config

    async def save(self) -> None:
        """Merge this configuration into the file atomically."""
        if self._config is None:
            return
        values = self._config.to_dict()
        conf_store.update(self.config_path, lambda d: d.update(values))

    async def get_auth_token(self) -> str | None:
        """Get authentication token"""
        config = await self.load()
        return config.auth_token

    async def set_auth_token(self, token: str) -> None:
        """Set authentication token"""
        config = await self.load()
        config.auth_token = token
        await self.save()

    async def clear_auth_token(self) -> None:
        """Clear authentication token"""
        config = await self.load()
        config.auth_token = None
        await self.save()

    async def get_server_url(self) -> str:
        """Get server URL"""
        config = await self.load()
        return config.server_url

    async def set_server_url(self, url: str) -> None:
        """Set server URL"""
        config = await self.load()
        config.server_url = url
        await self.save()

    async def get_api_url(self) -> str:
        """Get API URL"""
        config = await self.load()
        return config.api_url

    async def set_api_url(self, url: str) -> None:
        """Set API URL"""
        config = await self.load()
        config.api_url = url
        await self.save()

    async def get_ssl_verify(self) -> bool:
        """Get SSL verification setting"""
        config = await self.load()
        return config.ssl_verify

    async def set_ssl_verify(self, verify: bool) -> None:
        """Set SSL verification setting"""
        config = await self.load()
        config.ssl_verify = verify
        await self.save()

    async def get_max_message_size(self) -> int:
        """Get maximum message size in bytes"""
        config = await self.load()
        return config.max_message_size

    async def set_max_message_size(self, size: int) -> None:
        """Set maximum message size in bytes"""
        config = await self.load()
        config.max_message_size = size
        await self.save()


# Global config manager instance
config_manager = ConfigManager()

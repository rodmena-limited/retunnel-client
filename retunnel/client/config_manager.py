"""
Client configuration management for ReTunnel

Handles ~/.retunnel.conf for storing authentication tokens
and server configuration.
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiofiles


@dataclass
class ClientConfig:
    """ReTunnel client configuration"""

    auth_token: Optional[str] = None
    server_url: str = "wss://retunnel.net"  # WebSocket endpoint for tunnels
    api_url: str = "https://retunnel.net"  # REST API endpoint

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ClientConfig":
        """Create config from dictionary"""
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary"""
        return {
            "auth_token": self.auth_token,
            "server_url": self.server_url,
            "api_url": self.api_url,
        }


class ConfigManager:
    """Manages client configuration file"""

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize config manager

        Args:
            config_path: Path to config file. Defaults to ~/.retunnel.conf
        """
        if config_path is None:
            home = Path.home()
            config_path = home / ".retunnel.conf"

        self.config_path = config_path
        self._config: Optional[ClientConfig] = None

    async def load(self) -> ClientConfig:
        """Load configuration from file

        Returns:
            ClientConfig instance
        """
        if self._config is not None:
            return self._config

        if not self.config_path.exists():
            # Create default config
            # Use logger instead of print to avoid output pollution
            self._config = ClientConfig()
            await self.save()
            return self._config

        try:
            async with aiofiles.open(self.config_path, "r") as f:
                data = json.loads(await f.read())
                self._config = ClientConfig.from_dict(data)
                # Remove print statement that was polluting output
        except Exception as e:
            # If config is corrupted, create new one
            print(f"Error loading config: {e}", file=sys.stderr)
            self._config = ClientConfig()
            await self.save()

        return self._config

    async def save(self) -> None:
        """Save configuration to file"""
        if self._config is None:
            return

        # Ensure directory exists
        self.config_path.parent.mkdir(exist_ok=True)

        # Save with restricted permissions (600)
        async with aiofiles.open(self.config_path, "w") as f:
            await f.write(json.dumps(self._config.to_dict(), indent=2))

        # Set file permissions to 600 (read/write for owner only)
        os.chmod(self.config_path, 0o600)

    async def get_auth_token(self) -> Optional[str]:
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


# Global config manager instance
config_manager = ConfigManager()

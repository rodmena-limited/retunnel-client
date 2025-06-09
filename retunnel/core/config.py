"""Configuration management for ReTunnel client."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_config_dir() -> Path:
    """Get the configuration directory path."""
    config_dir = os.environ.get("RETUNNEL_CONFIG_DIR")
    if config_dir:
        return Path(config_dir)
    return Path.home() / ".retunnel"


class TunnelDefinition(BaseModel):
    """Configuration for a single tunnel."""

    name: str = Field(description="Tunnel name")
    protocol: str = Field(description="Protocol (http/tcp)")
    local_port: int = Field(description="Local port to expose")
    subdomain: Optional[str] = Field(default=None)
    hostname: Optional[str] = Field(default=None)
    auth: Optional[str] = Field(default=None)
    inspect: bool = Field(default=True)

    @field_validator("protocol")
    def validate_protocol(cls, v: str) -> str:
        """Validate protocol is supported."""
        if v not in ("http", "tcp"):
            raise ValueError(f"Unsupported protocol: {v}")
        return v


class ClientConfig(BaseSettings):
    """ReTunnel client configuration."""

    model_config = SettingsConfigDict(
        env_prefix="RETUNNEL_",
        env_file=".env",
        extra="ignore",
    )

    server_addr: str = Field(
        default="localhost:6400",
        description="ReTunnel server address",
    )
    auth_token: Optional[str] = Field(
        default=None,
        description="Authentication token",
    )
    region: Optional[str] = Field(
        default=None,
        description="Preferred region",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level",
    )
    tunnels: List[TunnelDefinition] = Field(
        default_factory=list,
        description="Tunnel definitions",
    )

    @classmethod
    def from_yaml(cls, path: Path) -> ClientConfig:
        """Load configuration from YAML file."""
        with open(path, "r") as f:
            data = yaml.safe_load(f)

        # Support environment variable substitution
        data = cls._substitute_env_vars(data)

        return cls(**data)

    @staticmethod
    def _substitute_env_vars(data: Any) -> Any:
        """Recursively substitute environment variables."""
        if isinstance(data, str):
            # Check for ${VAR_NAME} pattern
            if data.startswith("${") and data.endswith("}"):
                var_name = data[2:-1]
                return os.environ.get(var_name, data)
            return data
        elif isinstance(data, dict):
            return {
                k: ClientConfig._substitute_env_vars(v)
                for k, v in data.items()
            }
        elif isinstance(data, list):
            return [ClientConfig._substitute_env_vars(item) for item in data]
        return data

    def save(self, path: Optional[Path] = None) -> None:
        """Save configuration to file."""
        if path is None:
            path = self.get_default_config_file()

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Save as JSON
        with open(path, "w") as f:
            json.dump(self.model_dump(exclude_none=True), f, indent=2)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> ClientConfig:
        """Load configuration from file."""
        if path is None:
            path = cls().get_default_config_file()

        if not path.exists():
            # Return defaults if file doesn't exist
            return cls()

        with open(path, "r") as f:
            data = json.load(f)

        return cls(**data)

    def get_default_config_file(self) -> Path:
        """Get the default configuration file path."""
        return get_config_dir() / "config.json"


class AuthConfig:
    """Authentication configuration stored in user home."""

    CONFIG_PATH = Path.home() / ".retunnel.conf"

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        """Load configuration from file."""
        if self.CONFIG_PATH.exists():
            try:
                with open(self.CONFIG_PATH, "r") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {}

    def save(self) -> None:
        """Save configuration to file."""
        self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

        with open(self.CONFIG_PATH, "w") as f:
            json.dump(self._data, f, indent=2)

        # Set secure permissions (owner read/write only)
        os.chmod(self.CONFIG_PATH, 0o600)

    @property
    def auth_token(self) -> Optional[str]:
        """Get stored authentication token."""
        return self._data.get("auth_token")

    @auth_token.setter
    def auth_token(self, value: Optional[str]) -> None:
        """Set authentication token."""
        if value:
            self._data["auth_token"] = value
        else:
            self._data.pop("auth_token", None)
        self.save()

    @property
    def api_key(self) -> Optional[str]:
        """Get API key (legacy support)."""
        return self._data.get("api_key")

    @api_key.setter
    def api_key(self, value: Optional[str]) -> None:
        """Set API key (legacy support)."""
        if value:
            self._data["api_key"] = value
        else:
            self._data.pop("api_key", None)
        self.save()

    def clear(self) -> None:
        """Clear all configuration."""
        self._data = {}
        self.save()

"""Fast config tests."""

from pathlib import Path
from unittest.mock import mock_open, patch

from retunnel.core.config import (
    AuthConfig,
    ClientConfig,
    get_config_dir
)


def test_auth_config():
    """Test AuthConfig."""
    config = AuthConfig(
        token="test_token",
        user_id="123",
        email="test@example.com"
    )
    assert config.token == "test_token"
    assert config.user_id == "123"
    assert config.email == "test@example.com"


def test_client_config_defaults():
    """Test ClientConfig defaults."""
    config = ClientConfig()
    assert config.server_url == "wss://localhost:6400/api/v1/ws/tunnel"
    assert config.api_url == "http://localhost:6400"
    assert config.timeout == 30.0
    assert config.auto_register is True


def test_client_config_custom():
    """Test ClientConfig with custom values."""
    config = ClientConfig(
        server_url="wss://custom.com/ws",
        api_url="https://custom.com",
        timeout=60.0,
        auto_register=False
    )
    assert config.server_url == "wss://custom.com/ws"
    assert config.api_url == "https://custom.com"
    assert config.timeout == 60.0
    assert config.auto_register is False


def test_get_config_dir():
    """Test config directory."""
    path = get_config_dir()
    assert isinstance(path, Path)
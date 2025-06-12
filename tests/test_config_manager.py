"""Comprehensive tests for config_manager module to achieve 95%+ coverage."""

import json
import os
from pathlib import Path

import pytest

from retunnel.client.config_manager import ClientConfig, ConfigManager


class TestClientConfig:
    """Test ClientConfig dataclass."""

    def test_client_config_defaults(self):
        """Test ClientConfig with default values."""
        config = ClientConfig()
        assert config.auth_token is None
        assert config.server_url == "wss://retunnel.net"
        assert config.api_url == "https://retunnel.net"

    def test_client_config_custom_values(self):
        """Test ClientConfig with custom values."""
        config = ClientConfig(
            auth_token="test-token",
            server_url="wss://custom.server.com",
            api_url="https://custom.api.com",
        )
        assert config.auth_token == "test-token"
        assert config.server_url == "wss://custom.server.com"
        assert config.api_url == "https://custom.api.com"

    def test_from_dict(self):
        """Test creating ClientConfig from dictionary."""
        data = {
            "auth_token": "dict-token",
            "server_url": "wss://from.dict.com",
            "api_url": "https://from.dict.com",
        }
        config = ClientConfig.from_dict(data)
        assert config.auth_token == "dict-token"
        assert config.server_url == "wss://from.dict.com"
        assert config.api_url == "https://from.dict.com"

    def test_from_dict_partial(self):
        """Test from_dict with partial data."""
        data = {"auth_token": "partial-token"}
        config = ClientConfig.from_dict(data)
        assert config.auth_token == "partial-token"
        assert config.server_url == "wss://retunnel.net"  # default
        assert config.api_url == "https://retunnel.net"  # default

    def test_to_dict(self):
        """Test converting ClientConfig to dictionary."""
        config = ClientConfig(
            auth_token="to-dict-token",
            server_url="wss://to.dict.com",
            api_url="https://to.dict.com",
        )
        data = config.to_dict()
        assert data == {
            "auth_token": "to-dict-token",
            "server_url": "wss://to.dict.com",
            "api_url": "https://to.dict.com",
        }


class TestConfigManager:
    """Test ConfigManager class."""

    def test_init_default_path(self):
        """Test ConfigManager initialization with default path."""
        manager = ConfigManager()
        assert manager.config_path == Path.home() / ".retunnel.conf"
        assert manager._config is None

    def test_init_custom_path(self):
        """Test ConfigManager initialization with custom path."""
        custom_path = Path("/tmp/custom.conf")
        manager = ConfigManager(config_path=custom_path)
        assert manager.config_path == custom_path
        assert manager._config is None

    @pytest.mark.asyncio
    async def test_load_non_existing_file(self, tmp_path):
        """Test loading when config file doesn't exist."""
        config_path = tmp_path / "non_existent.conf"
        manager = ConfigManager(config_path=config_path)

        config = await manager.load()

        assert config.auth_token is None
        assert config.server_url == "wss://retunnel.net"
        assert config.api_url == "https://retunnel.net"
        assert config_path.exists()  # Should create file
        assert manager._config is config

    @pytest.mark.asyncio
    async def test_load_existing_file(self, tmp_path):
        """Test loading existing config file."""
        config_path = tmp_path / "existing.conf"
        config_data = {
            "auth_token": "existing-token",
            "server_url": "wss://existing.com",
            "api_url": "https://existing.com",
        }
        config_path.write_text(json.dumps(config_data))

        manager = ConfigManager(config_path=config_path)
        config = await manager.load()

        assert config.auth_token == "existing-token"
        assert config.server_url == "wss://existing.com"
        assert config.api_url == "https://existing.com"

    @pytest.mark.asyncio
    async def test_load_cached_config(self, tmp_path):
        """Test loading returns cached config if already loaded."""
        config_path = tmp_path / "cached.conf"
        manager = ConfigManager(config_path=config_path)

        # First load
        config1 = await manager.load()
        # Second load should return same instance
        config2 = await manager.load()

        assert config1 is config2
        assert manager._config is config1

    @pytest.mark.asyncio
    async def test_load_corrupted_file(self, tmp_path, capsys):
        """Test loading corrupted config file."""
        config_path = tmp_path / "corrupted.conf"
        config_path.write_text("not valid json")

        manager = ConfigManager(config_path=config_path)
        config = await manager.load()

        # Should create default config
        assert config.auth_token is None
        assert config.server_url == "wss://retunnel.net"

        # Check error message was printed to stderr
        captured = capsys.readouterr()
        assert "Error loading config:" in captured.err

    @pytest.mark.asyncio
    async def test_save_no_config(self, tmp_path):
        """Test save when no config is loaded."""
        config_path = tmp_path / "no_config.conf"
        manager = ConfigManager(config_path=config_path)

        # Should do nothing
        await manager.save()
        assert not config_path.exists()

    @pytest.mark.asyncio
    async def test_save_with_config(self, tmp_path):
        """Test saving configuration."""
        config_path = tmp_path / "save_test.conf"
        manager = ConfigManager(config_path=config_path)

        # Load to create config
        await manager.load()
        manager._config.auth_token = "save-token"

        await manager.save()

        # Verify file contents
        saved_data = json.loads(config_path.read_text())
        assert saved_data["auth_token"] == "save-token"

        # Check file permissions (Unix only)
        if os.name != "nt":
            stat_info = os.stat(config_path)
            assert stat_info.st_mode & 0o777 == 0o600

    @pytest.mark.asyncio
    async def test_get_auth_token(self, tmp_path):
        """Test getting auth token."""
        config_path = tmp_path / "auth_token.conf"
        config_data = {"auth_token": "get-token"}
        config_path.write_text(json.dumps(config_data))

        manager = ConfigManager(config_path=config_path)
        token = await manager.get_auth_token()

        assert token == "get-token"

    @pytest.mark.asyncio
    async def test_set_auth_token(self, tmp_path):
        """Test setting auth token."""
        config_path = tmp_path / "set_token.conf"
        manager = ConfigManager(config_path=config_path)

        await manager.set_auth_token("new-token")

        # Verify token was set
        config = await manager.load()
        assert config.auth_token == "new-token"

        # Verify file was saved
        saved_data = json.loads(config_path.read_text())
        assert saved_data["auth_token"] == "new-token"

    @pytest.mark.asyncio
    async def test_clear_auth_token(self, tmp_path):
        """Test clearing auth token."""
        config_path = tmp_path / "clear_token.conf"
        config_data = {"auth_token": "to-be-cleared"}
        config_path.write_text(json.dumps(config_data))

        manager = ConfigManager(config_path=config_path)
        await manager.clear_auth_token()

        # Verify token was cleared
        config = await manager.load()
        assert config.auth_token is None

        # Verify file was saved
        saved_data = json.loads(config_path.read_text())
        assert saved_data["auth_token"] is None

    @pytest.mark.asyncio
    async def test_get_server_url(self, tmp_path):
        """Test getting server URL."""
        config_path = tmp_path / "server_url.conf"
        config_data = {"server_url": "wss://custom.server.com"}
        config_path.write_text(json.dumps(config_data))

        manager = ConfigManager(config_path=config_path)
        url = await manager.get_server_url()

        assert url == "wss://custom.server.com"

    @pytest.mark.asyncio
    async def test_set_server_url(self, tmp_path):
        """Test setting server URL."""
        config_path = tmp_path / "set_server.conf"
        manager = ConfigManager(config_path=config_path)

        await manager.set_server_url("wss://new.server.com")

        # Verify URL was set
        config = await manager.load()
        assert config.server_url == "wss://new.server.com"

        # Verify file was saved
        saved_data = json.loads(config_path.read_text())
        assert saved_data["server_url"] == "wss://new.server.com"

    @pytest.mark.asyncio
    async def test_get_api_url(self, tmp_path):
        """Test getting API URL."""
        config_path = tmp_path / "api_url.conf"
        config_data = {"api_url": "https://custom.api.com"}
        config_path.write_text(json.dumps(config_data))

        manager = ConfigManager(config_path=config_path)
        url = await manager.get_api_url()

        assert url == "https://custom.api.com"

    @pytest.mark.asyncio
    async def test_set_api_url(self, tmp_path):
        """Test setting API URL."""
        config_path = tmp_path / "set_api.conf"
        manager = ConfigManager(config_path=config_path)

        await manager.set_api_url("https://new.api.com")

        # Verify URL was set
        config = await manager.load()
        assert config.api_url == "https://new.api.com"

        # Verify file was saved
        saved_data = json.loads(config_path.read_text())
        assert saved_data["api_url"] == "https://new.api.com"

    @pytest.mark.asyncio
    async def test_save_creates_parent_directory(self, tmp_path):
        """Test that save creates parent directory if it doesn't exist."""
        config_path = tmp_path / "subdir" / "config.conf"
        manager = ConfigManager(config_path=config_path)

        # Load to create config
        await manager.load()

        # Parent directory should be created
        assert config_path.parent.exists()
        assert config_path.exists()

    @pytest.mark.asyncio
    async def test_global_config_manager(self):
        """Test global config_manager instance."""
        from retunnel.client.config_manager import config_manager

        assert isinstance(config_manager, ConfigManager)
        assert config_manager.config_path == Path.home() / ".retunnel.conf"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

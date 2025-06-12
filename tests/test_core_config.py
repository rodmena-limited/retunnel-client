"""Comprehensive tests for core.config module to achieve 90%+ coverage."""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from retunnel.core.config import (
    AuthConfig,
    ClientConfig,
    TunnelDefinition,
    get_config_dir,
)


class TestGetConfigDir:
    """Test get_config_dir function."""

    def test_default_config_dir(self):
        """Test default config directory."""
        with patch.dict(os.environ, {}, clear=True):
            config_dir = get_config_dir()
            assert config_dir == Path.home() / ".retunnel"

    def test_custom_config_dir_from_env(self):
        """Test custom config directory from environment."""
        with patch.dict(os.environ, {"RETUNNEL_CONFIG_DIR": "/custom/config"}):
            config_dir = get_config_dir()
            assert config_dir == Path("/custom/config")

    def test_empty_env_var(self):
        """Test empty environment variable falls back to default."""
        with patch.dict(os.environ, {"RETUNNEL_CONFIG_DIR": ""}):
            config_dir = get_config_dir()
            assert config_dir == Path.home() / ".retunnel"


class TestTunnelDefinition:
    """Test TunnelDefinition model."""

    def test_basic_tunnel(self):
        """Test creating basic tunnel definition."""
        tunnel = TunnelDefinition(name="web", protocol="http", local_port=8080)
        assert tunnel.name == "web"
        assert tunnel.protocol == "http"
        assert tunnel.local_port == 8080
        assert tunnel.subdomain is None
        assert tunnel.hostname is None
        assert tunnel.auth is None
        assert tunnel.inspect is True

    def test_full_tunnel(self):
        """Test tunnel with all fields."""
        tunnel = TunnelDefinition(
            name="api",
            protocol="tcp",
            local_port=3000,
            subdomain="myapi",
            hostname="api.example.com",
            auth="user:pass",
            inspect=False,
        )
        assert tunnel.name == "api"
        assert tunnel.protocol == "tcp"
        assert tunnel.local_port == 3000
        assert tunnel.subdomain == "myapi"
        assert tunnel.hostname == "api.example.com"
        assert tunnel.auth == "user:pass"
        assert tunnel.inspect is False

    def test_protocol_validation_valid(self):
        """Test valid protocol values."""
        for protocol in ["http", "tcp"]:
            tunnel = TunnelDefinition(
                name=f"test-{protocol}", protocol=protocol, local_port=8080
            )
            assert tunnel.protocol == protocol

    def test_protocol_validation_invalid(self):
        """Test invalid protocol values."""
        with pytest.raises(ValidationError) as exc_info:
            TunnelDefinition(name="invalid", protocol="udp", local_port=8080)
        assert "Unsupported protocol: udp" in str(exc_info.value)

    def test_model_dump(self):
        """Test model serialization."""
        tunnel = TunnelDefinition(
            name="test", protocol="http", local_port=8080, subdomain="test"
        )
        data = tunnel.model_dump()
        assert data["name"] == "test"
        assert data["protocol"] == "http"
        assert data["local_port"] == 8080
        assert data["subdomain"] == "test"


class TestClientConfig:
    """Test ClientConfig model."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ClientConfig()
        assert config.server_addr == "localhost:6400"
        assert config.auth_token is None
        assert config.region is None
        assert config.log_level == "INFO"
        assert config.tunnels == []

    def test_custom_config(self):
        """Test custom configuration values."""
        tunnel = TunnelDefinition(name="web", protocol="http", local_port=8080)
        config = ClientConfig(
            server_addr="custom.server:7000",
            auth_token="test-token",
            region="us-west",
            log_level="DEBUG",
            tunnels=[tunnel],
        )
        assert config.server_addr == "custom.server:7000"
        assert config.auth_token == "test-token"
        assert config.region == "us-west"
        assert config.log_level == "DEBUG"
        assert len(config.tunnels) == 1
        assert config.tunnels[0].name == "web"

    def test_env_var_override(self):
        """Test environment variable override."""
        with patch.dict(
            os.environ,
            {
                "RETUNNEL_SERVER_ADDR": "env.server:8000",
                "RETUNNEL_AUTH_TOKEN": "env-token",
                "RETUNNEL_REGION": "eu-west",
                "RETUNNEL_LOG_LEVEL": "WARNING",
            },
        ):
            config = ClientConfig()
            assert config.server_addr == "env.server:8000"
            assert config.auth_token == "env-token"
            assert config.region == "eu-west"
            assert config.log_level == "WARNING"

    def test_from_yaml(self, tmp_path):
        """Test loading configuration from YAML file."""
        yaml_content = """
server_addr: yaml.server:9000
auth_token: yaml-token
region: ap-south
log_level: ERROR
tunnels:
  - name: web
    protocol: http
    local_port: 8080
    subdomain: web
  - name: api
    protocol: tcp
    local_port: 3000
"""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml_content)

        config = ClientConfig.from_yaml(yaml_file)
        assert config.server_addr == "yaml.server:9000"
        assert config.auth_token == "yaml-token"
        assert config.region == "ap-south"
        assert config.log_level == "ERROR"
        assert len(config.tunnels) == 2
        assert config.tunnels[0].name == "web"
        assert config.tunnels[1].name == "api"

    def test_from_yaml_with_env_vars(self, tmp_path):
        """Test YAML with environment variable substitution."""
        yaml_content = """
server_addr: ${TEST_SERVER_ADDR}
auth_token: ${TEST_AUTH_TOKEN}
tunnels:
  - name: ${TEST_TUNNEL_NAME}
    protocol: http
    local_port: 8080
"""
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(yaml_content)

        with patch.dict(
            os.environ,
            {
                "TEST_SERVER_ADDR": "env.server:1234",
                "TEST_AUTH_TOKEN": "env-auth-token",
                "TEST_TUNNEL_NAME": "env-tunnel",
            },
        ):
            config = ClientConfig.from_yaml(yaml_file)
            assert config.server_addr == "env.server:1234"
            assert config.auth_token == "env-auth-token"
            assert config.tunnels[0].name == "env-tunnel"

    def test_substitute_env_vars_string(self):
        """Test environment variable substitution for strings."""
        # Test with existing env var
        with patch.dict(os.environ, {"MY_VAR": "my-value"}):
            result = ClientConfig._substitute_env_vars("${MY_VAR}")
            assert result == "my-value"

        # Test with non-existing env var (returns original)
        result = ClientConfig._substitute_env_vars("${NON_EXISTING}")
        assert result == "${NON_EXISTING}"

        # Test normal string (no substitution)
        result = ClientConfig._substitute_env_vars("normal string")
        assert result == "normal string"

    def test_substitute_env_vars_dict(self):
        """Test environment variable substitution in dictionaries."""
        with patch.dict(os.environ, {"KEY1": "value1", "KEY2": "value2"}):
            data = {
                "field1": "${KEY1}",
                "field2": "${KEY2}",
                "field3": "static",
            }
            result = ClientConfig._substitute_env_vars(data)
            assert result == {
                "field1": "value1",
                "field2": "value2",
                "field3": "static",
            }

    def test_substitute_env_vars_list(self):
        """Test environment variable substitution in lists."""
        with patch.dict(os.environ, {"ITEM1": "first", "ITEM2": "second"}):
            data = ["${ITEM1}", "${ITEM2}", "third"]
            result = ClientConfig._substitute_env_vars(data)
            assert result == ["first", "second", "third"]

    def test_substitute_env_vars_nested(self):
        """Test environment variable substitution in nested structures."""
        with patch.dict(os.environ, {"VAR1": "val1", "VAR2": "val2"}):
            data = {"level1": {"level2": ["${VAR1}", {"level3": "${VAR2}"}]}}
            result = ClientConfig._substitute_env_vars(data)
            assert result == {
                "level1": {"level2": ["val1", {"level3": "val2"}]}
            }

    def test_substitute_env_vars_other_types(self):
        """Test environment variable substitution with other types."""
        # Numbers, booleans, None should pass through unchanged
        assert ClientConfig._substitute_env_vars(42) == 42
        assert ClientConfig._substitute_env_vars(3.14) == 3.14
        assert ClientConfig._substitute_env_vars(True) is True
        assert ClientConfig._substitute_env_vars(None) is None

    def test_save(self, tmp_path):
        """Test saving configuration to file."""
        config = ClientConfig(
            server_addr="save.server:5000",
            auth_token="save-token",
            log_level="DEBUG",
        )

        save_path = tmp_path / "saved_config.json"
        config.save(save_path)

        assert save_path.exists()
        with open(save_path) as f:
            data = json.load(f)

        assert data["server_addr"] == "save.server:5000"
        assert data["auth_token"] == "save-token"
        assert data["log_level"] == "DEBUG"

    def test_save_default_path(self, tmp_path):
        """Test saving to default path."""
        with patch.object(
            ClientConfig,
            "get_default_config_file",
            return_value=tmp_path / "default.json",
        ):
            config = ClientConfig()
            config.save()

            assert (tmp_path / "default.json").exists()

    def test_save_creates_directories(self, tmp_path):
        """Test save creates parent directories."""
        save_path = tmp_path / "subdir1" / "subdir2" / "config.json"
        config = ClientConfig()
        config.save(save_path)

        assert save_path.exists()
        assert save_path.parent.exists()

    def test_load(self, tmp_path):
        """Test loading configuration from file."""
        config_data = {
            "server_addr": "load.server:6000",
            "auth_token": "load-token",
            "region": "us-east",
            "tunnels": [
                {"name": "loaded", "protocol": "http", "local_port": 9000}
            ],
        }

        load_path = tmp_path / "load_config.json"
        with open(load_path, "w") as f:
            json.dump(config_data, f)

        config = ClientConfig.load(load_path)
        assert config.server_addr == "load.server:6000"
        assert config.auth_token == "load-token"
        assert config.region == "us-east"
        assert len(config.tunnels) == 1
        assert config.tunnels[0].name == "loaded"

    def test_load_non_existing(self, tmp_path):
        """Test loading non-existing file returns defaults."""
        non_existing = tmp_path / "non_existing.json"
        config = ClientConfig.load(non_existing)

        assert config.server_addr == "localhost:6400"
        assert config.auth_token is None
        assert config.tunnels == []

    def test_load_default_path(self, tmp_path):
        """Test loading from default path."""
        default_path = tmp_path / "default.json"
        config_data = {"server_addr": "default.server:7000"}

        with open(default_path, "w") as f:
            json.dump(config_data, f)

        with patch.object(
            ClientConfig, "get_default_config_file", return_value=default_path
        ):
            config = ClientConfig.load()
            assert config.server_addr == "default.server:7000"

    def test_get_default_config_file(self):
        """Test getting default config file path."""
        with patch(
            "retunnel.core.config.get_config_dir",
            return_value=Path("/test/config"),
        ):
            config = ClientConfig()
            path = config.get_default_config_file()
            assert path == Path("/test/config/config.json")


class TestAuthConfig:
    """Test AuthConfig class."""

    def test_init_no_existing_file(self, tmp_path):
        """Test initialization when config file doesn't exist."""
        with patch.object(AuthConfig, "CONFIG_PATH", tmp_path / "auth.conf"):
            auth = AuthConfig()
            assert auth._data == {}

    def test_init_with_existing_file(self, tmp_path):
        """Test initialization with existing config file."""
        config_path = tmp_path / "auth.conf"
        config_data = {
            "auth_token": "existing-token",
            "api_key": "existing-key",
        }
        with open(config_path, "w") as f:
            json.dump(config_data, f)

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()
            assert auth._data == config_data

    def test_load_corrupted_file(self, tmp_path):
        """Test loading corrupted config file."""
        config_path = tmp_path / "corrupted.conf"
        config_path.write_text("not valid json")

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()
            assert auth._data == {}

    def test_save(self, tmp_path):
        """Test saving configuration."""
        config_path = tmp_path / "save_auth.conf"

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()
            auth._data = {"auth_token": "save-token"}
            auth.save()

            assert config_path.exists()
            with open(config_path) as f:
                data = json.load(f)
            assert data == {"auth_token": "save-token"}

            # Check file permissions (Unix only)
            if os.name != "nt":
                stat_info = os.stat(config_path)
                assert stat_info.st_mode & 0o777 == 0o600

    def test_save_creates_directories(self, tmp_path):
        """Test save creates parent directories."""
        config_path = tmp_path / "subdir" / "auth.conf"

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()
            auth.save()

            assert config_path.exists()
            assert config_path.parent.exists()

    def test_auth_token_property(self, tmp_path):
        """Test auth_token property getter/setter."""
        config_path = tmp_path / "auth_token.conf"

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()

            # Test getter with no token
            assert auth.auth_token is None

            # Test setter
            auth.auth_token = "new-token"
            assert auth._data["auth_token"] == "new-token"
            assert config_path.exists()

            # Test getter with token
            assert auth.auth_token == "new-token"

            # Test clearing token
            auth.auth_token = None
            assert "auth_token" not in auth._data

            # Verify saved
            with open(config_path) as f:
                data = json.load(f)
            assert "auth_token" not in data

    def test_api_key_property(self, tmp_path):
        """Test api_key property getter/setter (legacy support)."""
        config_path = tmp_path / "api_key.conf"

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()

            # Test getter with no key
            assert auth.api_key is None

            # Test setter
            auth.api_key = "new-api-key"
            assert auth._data["api_key"] == "new-api-key"

            # Test getter with key
            assert auth.api_key == "new-api-key"

            # Test clearing key
            auth.api_key = None
            assert "api_key" not in auth._data

    def test_clear(self, tmp_path):
        """Test clearing all configuration."""
        config_path = tmp_path / "clear.conf"

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            auth = AuthConfig()
            auth._data = {
                "auth_token": "token-to-clear",
                "api_key": "key-to-clear",
                "other": "data",
            }

            auth.clear()

            assert auth._data == {}

            # Verify saved
            with open(config_path) as f:
                data = json.load(f)
            assert data == {}

    def test_multiple_operations(self, tmp_path):
        """Test multiple operations in sequence."""
        config_path = tmp_path / "multi.conf"

        with patch.object(AuthConfig, "CONFIG_PATH", config_path):
            # Create new auth config
            auth = AuthConfig()

            # Set auth token
            auth.auth_token = "token1"

            # Set API key
            auth.api_key = "key1"

            # Create new instance to test persistence
            auth2 = AuthConfig()
            assert auth2.auth_token == "token1"
            assert auth2.api_key == "key1"

            # Clear and verify
            auth2.clear()

            auth3 = AuthConfig()
            assert auth3.auth_token is None
            assert auth3.api_key is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

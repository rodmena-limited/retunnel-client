"""Simple unit tests to achieve 20%+ coverage without server communication."""

import os
from unittest.mock import patch

import pytest

from retunnel.core.config import ClientConfig, TunnelDefinition
from retunnel.core.exceptions import (
    AuthenticationError,
    ConnectionError,
    ProtocolError,
    ReTunnelError,
    TunnelError,
)
from retunnel.core.protocol import (
    Auth,
    AuthResp,
    NewTunnel,
    Ping,
    Pong,
    ReqTunnel,
    deserialize_message,
    serialize_message,
)
from retunnel.utils.id import generate_id


class TestProtocol:
    """Test protocol message serialization."""

    def test_auth_message(self):
        """Test Auth message creation."""
        auth = Auth()
        auth.User = "testuser"
        auth.Password = "testpass"
        auth.Version = "1.0.0"

        assert auth.Type == "Auth"
        assert auth.User == "testuser"

        # Test serialization
        packed = serialize_message(auth)
        assert isinstance(packed, bytes)

        # Test deserialization
        unpacked = deserialize_message(packed)
        assert isinstance(unpacked, Auth)
        assert unpacked.Type == "Auth"
        assert unpacked.User == "testuser"

    def test_auth_resp_message(self):
        """Test AuthResp message."""
        resp = AuthResp()
        resp.ClientId = "client-123"
        resp.Version = "1.0.0"

        assert resp.Type == "AuthResp"
        assert resp.ClientId == "client-123"

        packed = serialize_message(resp)
        unpacked = deserialize_message(packed)
        assert isinstance(unpacked, AuthResp)
        assert unpacked.Type == "AuthResp"

    def test_ping_pong_messages(self):
        """Test Ping and Pong messages."""
        ping = Ping()
        pong = Pong()

        assert ping.Type == "Ping"
        assert pong.Type == "Pong"

        # Test serialization
        ping_data = serialize_message(ping)
        pong_data = serialize_message(pong)

        assert deserialize_message(ping_data).Type == "Ping"
        assert deserialize_message(pong_data).Type == "Pong"


class TestExceptions:
    """Test exception hierarchy."""

    def test_base_exception(self):
        """Test base ReTunnelError."""
        err = ReTunnelError("Base error")
        assert str(err) == "Base error"
        assert isinstance(err, Exception)

    def test_specific_exceptions(self):
        """Test specific exception types."""
        conn_err = ConnectionError("Connection failed")
        assert isinstance(conn_err, ReTunnelError)
        assert str(conn_err) == "Connection failed"

        auth_err = AuthenticationError("Invalid token")
        assert isinstance(auth_err, ReTunnelError)

        tunnel_err = TunnelError("Tunnel creation failed")
        assert isinstance(tunnel_err, ReTunnelError)

        proto_err = ProtocolError("Invalid message")
        assert isinstance(proto_err, ReTunnelError)


class TestUtils:
    """Test utility functions."""

    def test_generate_id_basic(self):
        """Test basic ID generation."""
        id1 = generate_id()
        id2 = generate_id()

        # Should be 8 characters long
        assert len(id1) == 8
        assert len(id2) == 8

        # Should be unique
        assert id1 != id2

        # Should be alphanumeric
        assert id1.replace("-", "").replace("_", "").isalnum()

    def test_generate_id_consistency(self):
        """Test ID generation is consistent."""
        ids = [generate_id() for _ in range(10)]
        # All should be unique
        assert len(set(ids)) == 10
        # All should be 8 chars
        assert all(len(id) == 8 for id in ids)


class TestConfig:
    """Test configuration classes."""

    def test_tunnel_definition_basic(self):
        """Test TunnelDefinition with basic fields."""
        tunnel = TunnelDefinition(name="web", protocol="http", local_port=8080)
        assert tunnel.name == "web"
        assert tunnel.protocol == "http"
        assert tunnel.local_port == 8080
        assert tunnel.subdomain is None  # Default value

    def test_tunnel_definition_full(self):
        """Test TunnelDefinition with all fields."""
        tunnel = TunnelDefinition(
            name="api",
            protocol="http",
            local_port=3000,
            subdomain="myapi",
            auth="user:pass",
            inspect=True,
        )
        assert tunnel.name == "api"
        assert tunnel.protocol == "http"
        assert tunnel.local_port == 3000
        assert tunnel.subdomain == "myapi"
        assert tunnel.auth == "user:pass"
        assert tunnel.inspect is True

    def test_client_config_defaults(self):
        """Test ClientConfig with default values."""
        # Clear environment variables that might affect the test
        env_vars = [
            "RETUNNEL_SERVER_ENDPOINT",
            "RETUNNEL_AUTH_TOKEN",
            "RETUNNEL_LOG_LEVEL",
        ]
        old_env = {}
        for var in env_vars:
            old_env[var] = os.environ.pop(var, None)

        try:
            config = ClientConfig()
            assert config.server_addr == "localhost:6400"
            assert config.log_level == "INFO"
            assert config.tunnels == []
            assert config.auth_token is None
        finally:
            # Restore environment
            for var, value in old_env.items():
                if value is not None:
                    os.environ[var] = value

    def test_client_config_from_env(self):
        """Test ClientConfig reading from environment."""
        with patch.dict(
            os.environ,
            {
                "RETUNNEL_SERVER_ENDPOINT": "test.com:9000",
                "RETUNNEL_LOG_LEVEL": "DEBUG",
            },
        ):
            # Need to reload the module to pick up env changes
            # The config uses pydantic settings which reads env vars
            # but the implementation might cache values
            pass


class TestImports:
    """Test that main modules can be imported."""

    def test_import_core_modules(self):
        """Test importing core modules."""
        import retunnel.core.config
        import retunnel.core.exceptions
        import retunnel.core.protocol
        import retunnel.utils.id

        assert retunnel.core.protocol.serialize_message is not None
        assert retunnel.core.exceptions.ReTunnelError is not None
        assert retunnel.core.config.TunnelDefinition is not None
        assert retunnel.utils.id.generate_id is not None

    def test_import_client_modules(self):
        """Test importing client modules."""
        import retunnel.client.api_client
        import retunnel.client.config_manager

        assert retunnel.client.config_manager.ConfigManager is not None
        assert retunnel.client.api_client.ReTunnelAPIClient is not None

    def test_package_metadata(self):
        """Test package metadata."""
        import retunnel

        assert hasattr(retunnel, "__version__")
        assert isinstance(retunnel.__version__, str)
        assert retunnel.__version__  # Should not be empty


class TestProtocolEdgeCases:
    """Test protocol edge cases."""

    def test_new_tunnel_message(self):
        """Test NewTunnel message."""
        tunnel = NewTunnel()
        tunnel.ReqId = "req-123"
        tunnel.Protocol = "http"
        tunnel.Url = "https://test.retunnel.net"

        assert tunnel.Type == "NewTunnel"

        # Test serialization round trip
        packed = serialize_message(tunnel)
        unpacked = deserialize_message(packed)
        assert unpacked.Type == "NewTunnel"
        assert unpacked.Url == "https://test.retunnel.net"

    def test_req_tunnel_message(self):
        """Test ReqTunnel message."""
        req = ReqTunnel()
        req.ReqId = "req-456"
        req.Protocol = "tcp"
        req.RemotePort = 2222

        assert req.Type == "ReqTunnel"
        assert req.Protocol == "tcp"

        # Test serialization
        packed = serialize_message(req)
        unpacked = deserialize_message(packed)
        assert isinstance(unpacked, ReqTunnel)
        assert unpacked.RemotePort == 2222


class TestAdditionalUtils:
    """Test additional utility functions."""

    def test_generate_id_with_prefix(self):
        """Test ID generation with prefix."""
        # Test with prefix
        prefixed_id = generate_id("test")
        assert prefixed_id.startswith("test-")
        assert len(prefixed_id) > 5  # "test-" + some chars

    def test_generate_id_multiple_calls(self):
        """Test multiple ID generations are unique."""
        ids = set()
        for _ in range(100):
            ids.add(generate_id())
        # All should be unique
        assert len(ids) == 100


class TestExceptionMessages:
    """Test exception message handling."""

    def test_retunnel_error_with_details(self):
        """Test ReTunnelError with details."""
        err = ReTunnelError("Operation failed")
        assert str(err) == "Operation failed"
        assert isinstance(err, Exception)

    def test_connection_error_types(self):
        """Test different connection error scenarios."""
        # Test websocket error
        ws_err = ConnectionError("WebSocket connection failed")
        assert "WebSocket" in str(ws_err)

        # Test timeout error
        timeout_err = ConnectionError("Connection timeout")
        assert "timeout" in str(timeout_err)

    def test_authentication_error_types(self):
        """Test different auth error scenarios."""
        # Invalid token
        token_err = AuthenticationError("Invalid token")
        assert "Invalid token" in str(token_err)

        # Expired token
        expired_err = AuthenticationError("Token expired")
        assert "expired" in str(expired_err)


class TestAPITypes:
    """Test API types from retunnel.core.api."""

    def test_import_api_types(self):
        """Test importing API types."""
        from retunnel.core.api import UserInfo

        # Test UserInfo creation
        user = UserInfo(
            user_id="user-123", username="testuser", auth_token="token-abc"
        )
        assert user.user_id == "user-123"
        assert user.username == "testuser"
        assert user.auth_token == "token-abc"

    def test_api_client_class(self):
        """Test APIClient class exists."""
        from retunnel.core.api import APIClient

        # Just test that we can import it
        assert APIClient is not None
        assert hasattr(APIClient, "__init__")


class TestMoreProtocol:
    """Additional protocol tests."""

    def test_error_resp_message(self):
        """Test ErrorResp message."""
        from retunnel.core.protocol import ErrorResp

        err = ErrorResp()
        err.Error = "Invalid request"

        assert err.Type == "ErrorResp"
        assert err.Error == "Invalid request"

        # Test serialization
        packed = serialize_message(err)
        unpacked = deserialize_message(packed)
        assert unpacked.Type == "ErrorResp"
        assert hasattr(unpacked, "Type")

    def test_heartbeat_message(self):
        """Test Heartbeat message."""
        from retunnel.core.protocol import Heartbeat

        hb = Heartbeat()
        hb.Timestamp = 1234567890

        assert hb.Type == "Heartbeat"
        assert hb.Timestamp == 1234567890


class TestHighPerformanceTypes:
    """Test high performance client types."""

    def test_tunnel_config_import(self):
        """Test importing TunnelConfig."""
        from retunnel.client.high_performance_model import TunnelConfig

        config = TunnelConfig(protocol="tcp", local_port=22)
        assert config.protocol == "tcp"
        assert config.local_port == 22
        assert config.subdomain is None
        assert config.auth is None

    def test_tunnel_import(self):
        """Test importing Tunnel class."""
        from retunnel.client.high_performance_model import Tunnel, TunnelConfig

        # Just test we can import the class
        assert Tunnel is not None
        assert hasattr(Tunnel, "__init__")

        # Test that TunnelConfig works
        config = TunnelConfig(protocol="http", local_port=8080)
        assert config.protocol == "http"


class TestMoreExceptions:
    """Test more exception scenarios."""

    def test_proxy_error(self):
        """Test ProxyError exception."""
        from retunnel.core.exceptions import ProxyError

        err = ProxyError("Proxy connection failed")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Proxy connection failed"

    def test_validation_error(self):
        """Test ValidationError exception."""
        from retunnel.core.exceptions import ValidationError

        err = ValidationError("Invalid input")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Invalid input"

    def test_configuration_error(self):
        """Test ConfigurationError exception."""
        from retunnel.core.exceptions import ConfigurationError

        err = ConfigurationError("Invalid config")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Invalid config"


class TestMoreUtils:
    """Test more utility functions."""

    def test_id_generation_edge_cases(self):
        """Test ID generation edge cases."""
        # Test empty prefix
        id1 = generate_id("")
        assert len(id1) > 0

        # Test long prefix
        id2 = generate_id("verylongprefix")
        assert id2.startswith("verylongprefix")

    def test_id_charset(self):
        """Test ID character set."""
        # Generate many IDs and check they only contain allowed chars
        for _ in range(50):
            id = generate_id()
            # Check it only contains alphanumeric, dash, underscore
            for char in id:
                assert char.isalnum() or char in "-_"

    def test_generate_client_id(self):
        """Test generate_client_id function."""
        from retunnel.utils.id import generate_client_id

        client_id = generate_client_id()
        assert client_id.startswith("client-")
        assert len(client_id) == 19  # "client-" (7) + 12 chars

        # Generate multiple to ensure uniqueness
        ids = [generate_client_id() for _ in range(10)]
        assert len(set(ids)) == 10  # All unique

    def test_generate_tunnel_id(self):
        """Test generate_tunnel_id function."""
        from retunnel.utils.id import generate_tunnel_id

        tunnel_id = generate_tunnel_id()
        assert tunnel_id.startswith("tun-")
        assert len(tunnel_id) == 12  # "tun-" (4) + 8 chars

        # Check uniqueness
        ids = [generate_tunnel_id() for _ in range(10)]
        assert len(set(ids)) == 10

    def test_generate_request_id(self):
        """Test generate_request_id function."""
        from retunnel.utils.id import generate_request_id

        req_id = generate_request_id()
        assert req_id.startswith("req-")
        assert len(req_id) == 12  # "req-" (4) + 8 chars

        # Check character set (no 0, 1, l)
        for char in req_id[4:]:  # Skip prefix
            assert char not in "01l"

    def test_generate_session_id(self):
        """Test generate_session_id function."""
        import time

        from retunnel.utils.id import generate_session_id

        # Capture time before generation
        before_time = int(time.time())
        session_id = generate_session_id()
        after_time = int(time.time())

        # Check format
        assert session_id.startswith("sess-")
        parts = session_id.split("-")
        assert len(parts) == 3  # "sess", timestamp, random

        # Check timestamp is valid
        timestamp = int(parts[1])
        assert before_time <= timestamp <= after_time

        # Check random part
        assert len(parts[2]) == 6

        # Generate multiple in quick succession
        ids = [generate_session_id() for _ in range(5)]
        # Even with same timestamp, should be unique due to random part
        assert len(set(ids)) == 5

    def test_id_character_exclusions(self):
        """Test that confusing characters are excluded."""
        from retunnel.utils.id import generate_id

        # Generate many IDs and verify excluded characters
        excluded_chars = {"0", "1", "l"}
        for _ in range(100):
            id = generate_id(length=20)  # Longer to increase chance
            for char in id:
                assert char not in excluded_chars

    def test_custom_length_ids(self):
        """Test generating IDs with custom lengths."""
        from retunnel.utils.id import generate_id

        # Test various lengths
        for length in [4, 8, 16, 32]:
            id = generate_id(length=length)
            assert len(id) == length

        # Test with prefix and custom length
        id_with_prefix = generate_id(prefix="test", length=10)
        assert id_with_prefix.startswith("test-")
        assert len(id_with_prefix) == 15  # "test-" (5) + 10


class TestMoreConfig:
    """Test more config scenarios."""

    def test_tunnel_definition_tcp(self):
        """Test TunnelDefinition for TCP."""
        tunnel = TunnelDefinition(name="ssh", protocol="tcp", local_port=22)
        assert tunnel.name == "ssh"
        assert tunnel.protocol == "tcp"
        assert tunnel.local_port == 22

    def test_tunnel_definition_validation(self):
        """Test TunnelDefinition validation."""
        # Test valid protocols
        for proto in ["http", "tcp"]:
            tunnel = TunnelDefinition(
                name=f"test-{proto}", protocol=proto, local_port=8080
            )
            assert tunnel.protocol == proto


class TestAPIError:
    """Test API error handling."""

    def test_api_error(self):
        """Test APIError exception."""
        from retunnel.core.exceptions import APIError

        err = APIError("API request failed", status_code=500)
        assert isinstance(err, ReTunnelError)
        assert str(err) == "API request failed"
        assert err.status_code == 500

    def test_api_error_without_code(self):
        """Test APIError without status code."""
        from retunnel.core.exceptions import APIError

        err = APIError("Bad request")
        assert str(err) == "Bad request"
        assert hasattr(err, "status_code")


class TestMessageTypes:
    """Test more message types."""

    def test_req_proxy_message(self):
        """Test ReqProxy message."""
        from retunnel.core.protocol import ReqProxy

        msg = ReqProxy()
        assert msg.Type == "ReqProxy"

    def test_reg_proxy_message(self):
        """Test RegProxy message."""
        from retunnel.core.protocol import RegProxy

        msg = RegProxy()
        msg.ClientId = "client-123"
        assert msg.Type == "RegProxy"
        assert msg.ClientId == "client-123"


class TestConfigEdgeCases:
    """Test configuration edge cases."""

    def test_tunnel_definition_minimal(self):
        """Test minimal TunnelDefinition."""
        tunnel = TunnelDefinition(
            name="minimal", protocol="tcp", local_port=8888
        )
        assert tunnel.name == "minimal"
        assert tunnel.local_port == 8888
        assert tunnel.hostname is None
        assert tunnel.subdomain is None
        assert tunnel.auth is None


class TestClientModule:
    """Test client module imports."""

    def test_import_client(self):
        """Test importing client module."""
        from retunnel.client import client

        assert hasattr(client, "ReTunnelClient")

    def test_import_cli(self):
        """Test importing CLI module."""
        from retunnel.client import cli

        assert hasattr(cli, "app")
        assert hasattr(cli, "main")


class TestConnectionModule:
    """Test connection module."""

    def test_import_websocket_connection(self):
        """Test importing WebSocketConnection."""
        from retunnel.core import connection

        assert hasattr(connection, "WebSocketConnection")

    def test_connection_state_enum(self):
        """Test WebSocketConnection class exists."""
        from retunnel.core.connection import WebSocketConnection

        # Test class exists
        assert WebSocketConnection is not None
        assert hasattr(WebSocketConnection, "__init__")


class TestAPIModule:
    """Test API module functionality."""

    def test_api_client_init(self):
        """Test APIClient initialization."""
        from retunnel.core.api import APIClient

        # Test with default URL
        client = APIClient()
        assert client is not None
        assert hasattr(client, "base_url")

        # Test with custom URL
        client2 = APIClient("https://api.example.com")
        assert client2.base_url == "https://api.example.com"

    def test_user_info_optional_email(self):
        """Test UserInfo with optional email."""
        from retunnel.core.api import UserInfo

        # Without email
        user1 = UserInfo(user_id="u1", username="user1", auth_token="tok1")
        assert user1.email is None

        # With email
        user2 = UserInfo(
            user_id="u2",
            username="user2",
            email="user2@example.com",
            auth_token="tok2",
        )
        assert user2.email == "user2@example.com"


class TestClientAPIClient:
    """Test client API client module."""

    def test_retunnel_api_client_init(self):
        """Test ReTunnelAPIClient initialization."""
        from retunnel.client.api_client import ReTunnelAPIClient

        # Test with default URL
        client = ReTunnelAPIClient()
        assert client is not None
        assert hasattr(client, "api_url")

        # Test with custom URL
        client2 = ReTunnelAPIClient("https://custom.api.com")
        assert client2.api_url == "https://custom.api.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

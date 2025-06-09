"""Fast exception tests."""

import pytest

from retunnel.core.exceptions import (
    ReTunnelError,
    ConnectionError,
    AuthenticationError,
    TunnelError,
    ProxyError,
    APIError,
    ProtocolError,
    ValidationError
)


def test_base_exception():
    """Test base exception."""
    error = ReTunnelError("test message")
    assert str(error) == "test message"


def test_connection_error():
    """Test connection error."""
    error = ConnectionError("connection failed")
    assert str(error) == "connection failed"


def test_authentication_error():
    """Test authentication error."""
    error = AuthenticationError("auth failed")
    assert str(error) == "auth failed"


def test_tunnel_error():
    """Test tunnel error."""
    error = TunnelError("tunnel failed")
    assert str(error) == "tunnel failed"




def test_proxy_error():
    """Test proxy error."""
    error = ProxyError("proxy failed")
    assert str(error) == "proxy failed"


def test_api_error():
    """Test API error."""
    error = APIError("API failed")
    assert str(error) == "API failed"


def test_protocol_error():
    """Test protocol error."""
    error = ProtocolError("protocol failed")
    assert str(error) == "protocol failed"


def test_validation_error():
    """Test validation error."""
    error = ValidationError("validation failed")
    assert str(error) == "validation failed"



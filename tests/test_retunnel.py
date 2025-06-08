"""
Tests for the ReTunnel package.
"""

import pytest
from retunnel import ReTunnelClient, hello, __version__


def test_version():
    """Test that version is properly set."""
    assert __version__ == "0.1.0"


def test_hello():
    """Test the hello function."""
    message = hello()
    assert "Hello from ReTunnel!" in message
    assert "https://retunnel.com" in message


def test_client_initialization():
    """Test ReTunnelClient initialization."""
    # Without API key
    client = ReTunnelClient()
    assert client.api_key is None
    assert not client.connected
    
    # With API key
    client_with_key = ReTunnelClient(api_key="test-key")
    assert client_with_key.api_key == "test-key"
    assert not client_with_key.connected


def test_client_connect():
    """Test client connection."""
    client = ReTunnelClient()
    assert not client.connected
    
    result = client.connect()
    assert result is True
    assert client.connected
    
    client.close()
    assert not client.connected


def test_create_tunnel():
    """Test tunnel creation."""
    client = ReTunnelClient()
    
    # Should raise error if not connected
    with pytest.raises(RuntimeError, match="Not connected"):
        client.create_tunnel()
    
    # Connect and create tunnel
    client.connect()
    tunnel_url = client.create_tunnel(port=8080)
    assert "placeholder.retunnel.com:8080" in tunnel_url
    
    # Test with different port
    tunnel_url_2 = client.create_tunnel(port=3000)
    assert "placeholder.retunnel.com:3000" in tunnel_url_2
    
    client.close()


def test_context_manager():
    """Test ReTunnelClient as context manager."""
    with ReTunnelClient() as client:
        assert client.connected
        tunnel_url = client.create_tunnel(port=5000)
        assert "placeholder.retunnel.com:5000" in tunnel_url
    
    # After exiting context, should be disconnected
    assert not client.connected


def test_context_manager_with_exception():
    """Test context manager handles exceptions properly."""
    try:
        with ReTunnelClient() as client:
            assert client.connected
            raise ValueError("Test exception")
    except ValueError:
        pass
    
    # Should still be disconnected after exception
    assert not client.connected
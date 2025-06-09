"""Fast utils tests."""

from retunnel.utils.id import (
    generate_id,
    generate_tunnel_id,
    generate_client_id,
    generate_session_id
)


def test_generate_id():
    """Test ID generation."""
    id1 = generate_id()
    id2 = generate_id()
    assert len(id1) == 16  # Default length is 16
    assert len(id2) == 16
    assert id1 != id2
    assert id1.isalnum()


def test_generate_tunnel_id():
    """Test tunnel ID generation."""
    tunnel_id = generate_tunnel_id()
    assert tunnel_id.startswith("tun_")
    assert len(tunnel_id) > 4


def test_generate_client_id():
    """Test client ID generation."""
    client_id = generate_client_id()
    assert client_id.startswith("cli_")
    assert len(client_id) > 4


def test_generate_session_id():
    """Test session ID generation."""
    session_id = generate_session_id()
    assert "_" in session_id
    assert len(session_id) > 10
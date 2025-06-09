"""Fast protocol tests."""

import msgpack

from retunnel.core.protocol import (
    Message,
    Auth,
    AuthResp,
    Ping,
    Pong,
    ReqTunnel,
    NewTunnel,
    ReqProxy,
    StartProxy,
    RegProxy
)


def test_auth_message():
    """Test Auth message."""
    msg = Auth(
        msg_type="Auth",
        token="test_token",
        client_id="cl_12345678",
        version="1.0.0"
    )
    assert msg.msg_type == "Auth"
    assert msg.token == "test_token"


def test_auth_resp_message():
    """Test AuthResp message."""
    msg = AuthResp(
        msg_type="AuthResp",
        success=True,
        client_id="cl_12345678"
    )
    assert msg.msg_type == "AuthResp"
    assert msg.success is True


def test_ping_pong():
    """Test Ping/Pong messages."""
    ping = Ping(msg_type="Ping")
    pong = Pong(msg_type="Pong")
    assert ping.msg_type == "Ping"
    assert pong.msg_type == "Pong"


def test_req_tunnel():
    """Test ReqTunnel message."""
    msg = ReqTunnel(
        msg_type="ReqTunnel",
        protocol="http",
        local_port=8080
    )
    assert msg.msg_type == "ReqTunnel"
    assert msg.protocol == "http"
    assert msg.local_port == 8080


def test_new_tunnel():
    """Test NewTunnel message."""
    msg = NewTunnel(
        msg_type="NewTunnel",
        tunnel_id="tn_12345678",
        url="http://test.ngrok.io",
        protocol="http"
    )
    assert msg.msg_type == "NewTunnel"
    assert msg.tunnel_id == "tn_12345678"


def test_req_proxy():
    """Test ReqProxy message."""
    msg = ReqProxy(
        msg_type="ReqProxy",
        tunnel_id="tn_12345678"
    )
    assert msg.msg_type == "ReqProxy"
    assert msg.tunnel_id == "tn_12345678"


def test_start_proxy():
    """Test StartProxy message."""
    msg = StartProxy(
        msg_type="StartProxy",
        tunnel_id="tn_12345678",
        conn_id="cn_12345678"
    )
    assert msg.msg_type == "StartProxy"
    assert msg.tunnel_id == "tn_12345678"


def test_reg_proxy():
    """Test RegProxy message."""
    msg = RegProxy(
        msg_type="RegProxy",
        client_id="cl_12345678",
        tunnel_id="tn_12345678"
    )
    assert msg.msg_type == "RegProxy"
    assert msg.client_id == "cl_12345678"


def test_message_pack_unpack():
    """Test message packing/unpacking."""
    msg = Ping(msg_type="Ping")
    packed = msg.pack()
    assert isinstance(packed, bytes)
    
    # Should be 8-byte length prefix + msgpack data
    assert len(packed) >= 8


def test_message_creation():
    """Test basic message creation."""
    msg = Message(msg_type="Test")
    assert msg.type == "Test"
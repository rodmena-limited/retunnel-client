"""
Message definitions for retunnel protocol
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import msgpack  # type: ignore[import-untyped]


@dataclass
class Message:
    """Base class for all protocol messages"""

    Type: str


@dataclass
class Auth(Message):
    """Authentication request from client to server"""

    Type: str = field(default="Auth", init=False)
    ClientId: str = ""
    OS: str = ""
    Arch: str = ""
    Version: str = ""
    MmVersion: str = ""
    User: str = ""
    Password: str = ""


@dataclass
class AuthResp(Message):
    """Authentication response from server to client"""

    Type: str = field(default="AuthResp", init=False)
    ClientId: str = ""
    Version: str = ""
    MmVersion: str = ""
    Error: str = ""


@dataclass
class ReqTunnel(Message):
    """Request to create a new tunnel"""

    Type: str = field(default="ReqTunnel", init=False)
    ReqId: str = ""
    Protocol: str = ""  # http, https, tcp
    Hostname: str = ""
    Subdomain: str = ""
    HttpAuth: str = ""
    RemotePort: int = 0
    Config: Optional[Dict[str, Any]] = None


@dataclass
class NewTunnel(Message):
    """Response for successful tunnel creation"""

    Type: str = field(default="NewTunnel", init=False)
    ReqId: str = ""
    Url: str = ""
    Protocol: str = ""
    Error: str = ""
    Subdomain: str = ""  # Added subdomain field


@dataclass
class ReqProxy(Message):
    """Request from server for client to open a new proxy connection"""

    Type: str = field(default="ReqProxy", init=False)


@dataclass
class RegProxy(Message):
    """Registration of a new proxy connection from client"""

    Type: str = field(default="RegProxy", init=False)
    ClientId: str = ""


@dataclass
class StartProxy(Message):
    """Server's instruction to start proxying on a connection"""

    Type: str = field(default="StartProxy", init=False)
    Url: str = ""
    ClientAddr: str = ""


@dataclass
class Ping(Message):
    """Heartbeat ping message"""

    Type: str = field(default="Ping", init=False)


@dataclass
class Pong(Message):
    """Heartbeat pong response"""

    Type: str = field(default="Pong", init=False)


@dataclass
class Heartbeat(Message):
    """Heartbeat for subdomain keep-alive"""

    Type: str = field(default="Heartbeat", init=False)
    Subdomain: str = ""
    Timestamp: float = 0.0


@dataclass
class ErrorResp(Message):
    """Error response from server"""

    Type: str = field(default="ErrorResp", init=False)
    ErrorCode: str = ""  # OVER_CAPACITY, LIMIT_EXCEEDED, etc.
    Message: str = ""
    ReqId: str = ""


# Message type registry for deserialization
MESSAGE_TYPES = {
    "Auth": Auth,
    "AuthResp": AuthResp,
    "ReqTunnel": ReqTunnel,
    "NewTunnel": NewTunnel,
    "ReqProxy": ReqProxy,
    "RegProxy": RegProxy,
    "StartProxy": StartProxy,
    "Ping": Ping,
    "Pong": Pong,
    "Heartbeat": Heartbeat,
    "ErrorResp": ErrorResp,
}


def serialize_message(msg: Message) -> bytes:
    """Serialize a message to msgpack bytes"""
    # Convert dataclass to dict
    data = {}
    for field_name in msg.__dataclass_fields__:
        value = getattr(msg, field_name)
        # Only include non-None values and non-empty strings
        if value is not None and value != "":
            data[field_name] = value

    return bytes(msgpack.packb(data, use_bin_type=True))


def deserialize_message(data: bytes) -> Message:
    """Deserialize msgpack bytes to a message object"""
    msg_dict = msgpack.unpackb(data, raw=False)

    # Get message type
    msg_type = msg_dict.get("Type")
    if not msg_type:
        raise ValueError("Message missing Type field")

    # Get message class
    msg_class = MESSAGE_TYPES.get(msg_type)
    if not msg_class:
        raise ValueError(f"Unknown message type: {msg_type}")

    # Remove Type from dict as it's set by the class
    msg_dict.pop("Type", None)

    # Create message instance
    return msg_class(**msg_dict)  # type: ignore[no-any-return]

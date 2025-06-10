"""Message protocol for ReTunnel client-server communication."""

from __future__ import annotations

import struct
from typing import Dict, Optional, Type, TypeVar

import msgpack  # type: ignore[import-untyped]
from pydantic import BaseModel, Field

T = TypeVar("T", bound="Message")


class Message(BaseModel):
    """Base message class for all protocol messages."""

    type: str = Field(description="Message type identifier", alias="msg_type")

    def pack(self) -> bytes:
        """Serialize message to msgpack format with length prefix."""
        # Get dict and manually rename msg_type to type
        msg_dict = self.model_dump()
        if "msg_type" in msg_dict:
            msg_dict["type"] = msg_dict.pop("msg_type")
        data: bytes = msgpack.packb(msg_dict)
        length = struct.pack(">Q", len(data))
        return length + data

    @classmethod
    def unpack(cls: Type[T], data: bytes) -> T:
        """Deserialize message from msgpack format."""
        msg_dict = msgpack.unpackb(data, raw=False)
        return cls(**msg_dict)

    class Config:
        """Pydantic configuration."""

        arbitrary_types_allowed = True


class Auth(Message):
    """Authentication request message."""

    type: str = Field(default="Auth", alias="msg_type")
    token: str = Field(description="Authentication token")
    client_id: str = Field(description="Client identifier")
    version: str = Field(description="Client version")
    user: str = Field(default="")
    password: str = Field(default="")
    os: str = Field(default="")
    arch: str = Field(default="")


class AuthResp(Message):
    """Authentication response message."""

    type: str = Field(default="AuthResp", alias="msg_type")
    client_id: str = Field(description="Assigned client ID")
    version: str = Field(default="")
    error: Optional[str] = Field(default=None)


class ReqTunnel(Message):
    """Request tunnel creation message."""

    type: str = Field(default="ReqTunnel", alias="msg_type")
    req_id: str = Field(default="")
    protocol: str = Field(description="Tunnel protocol (http/tcp)")
    subdomain: Optional[str] = Field(default="")
    hostname: Optional[str] = Field(default="")
    remote_port: int = Field(default=0)
    auth: str = Field(default="")


class NewTunnel(Message):
    """New tunnel created response."""

    type: str = Field(default="NewTunnel", alias="msg_type")
    req_id: str = Field(description="Request ID")
    tunnel_id: str = Field(description="Tunnel identifier", default="")
    url: str = Field(description="Public tunnel URL")
    protocol: str = Field(description="Tunnel protocol")
    error: Optional[str] = Field(default="")


class ReqProxy(Message):
    """Request proxy connection."""

    type: str = Field(default="ReqProxy", alias="msg_type")
    tunnel_id: str = Field(default="", description="Tunnel ID to proxy")


class RegProxy(Message):
    """Register proxy connection."""

    type: str = Field(default="RegProxy", alias="msg_type")
    client_id: str = Field(description="Client ID")
    tunnel_id: str = Field(description="Tunnel ID", default="")


class StartProxy(Message):
    """Start proxying data."""

    type: str = Field(default="StartProxy", alias="msg_type")
    tunnel_id: str = Field(description="Tunnel ID")
    conn_id: str = Field(description="Connection ID")


class Ping(Message):
    """Heartbeat ping message."""

    type: str = Field(default="Ping", alias="msg_type")


class Pong(Message):
    """Heartbeat pong response."""

    type: str = Field(default="Pong", alias="msg_type")


MESSAGE_TYPES: Dict[str, Type[Message]] = {
    "Auth": Auth,
    "AuthResp": AuthResp,
    "ReqTunnel": ReqTunnel,
    "NewTunnel": NewTunnel,
    "ReqProxy": ReqProxy,
    "RegProxy": RegProxy,
    "StartProxy": StartProxy,
    "Ping": Ping,
    "Pong": Pong,
}


def decode_message(data: bytes) -> Message:
    """Decode a message from bytes."""
    msg_dict = msgpack.unpackb(data, raw=False, strict_map_key=False)

    # Server sends messages in PascalCase format
    # Convert PascalCase fields to snake_case
    converted_dict = {}
    for key, value in msg_dict.items():
        # Convert common PascalCase fields
        if key == "Type":
            converted_dict["type"] = value
        elif key == "ClientId":
            converted_dict["client_id"] = value
        elif key == "Version":
            converted_dict["version"] = value
        elif key == "Error":
            converted_dict["error"] = value
        elif key == "ReqId":
            converted_dict["req_id"] = value
        elif key == "TunnelId":
            converted_dict["tunnel_id"] = value
        elif key == "Url":
            converted_dict["url"] = value
        elif key == "Protocol":
            converted_dict["protocol"] = value
        elif key == "ConnId":
            converted_dict["conn_id"] = value
        else:
            # Keep as-is for unknown fields
            converted_dict[key.lower()] = value

    # Get message type
    msg_type = converted_dict.get("type")
    if not msg_type or msg_type not in MESSAGE_TYPES:
        raise ValueError(f"Unknown message type: {msg_type}")

    message_class = MESSAGE_TYPES[msg_type]
    # Map "type" to "msg_type" for our model
    converted_dict["msg_type"] = converted_dict.get("type", "")

    return message_class(**converted_dict)

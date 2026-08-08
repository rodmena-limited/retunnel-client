from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, ClassVar

import msgpack


class StreamMode(str):
    HTTP = "http"
    WS = "ws"
    TCP = "tcp"


class WsMessageType(str):
    TEXT = "text"
    BINARY = "binary"


class MessageType(str):
    AUTH = "Auth"
    TUNNEL_CREATE = "TunnelCreate"
    TUNNEL_CREATED = "TunnelCreated"
    STREAM_OPEN = "StreamOpen"
    STREAM_DATA = "StreamData"
    STREAM_CLOSE = "StreamClose"
    STREAM_RESET = "StreamReset"
    HEARTBEAT = "Heartbeat"
    HEARTBEAT_ACK = "HeartbeatAck"
    ERROR = "Error"


MAX_CHUNK_SIZE = 64 * 1024
MAX_STREAMS_PER_CLIENT = 256
MAX_MESSAGE_SIZE = 10 * 1024 * 1024


@dataclass
class Auth:
    token: str
    Type: str = field(default=MessageType.AUTH, init=False, repr=False)


@dataclass
class TunnelCreate:
    protocol: str
    subdomain: str | None = None
    path: str | None = None
    remote_port: int | None = None
    Type: str = field(
        default=MessageType.TUNNEL_CREATE, init=False, repr=False
    )


@dataclass
class TunnelCreated:
    url: str
    subdomain: str
    path: str | None = None
    remote_port: int | None = None
    Type: str = field(
        default=MessageType.TUNNEL_CREATED, init=False, repr=False
    )


@dataclass
class StreamOpen:
    stream_id: int
    tunnel_id: str
    mode: str
    path: str = "/"
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    Type: str = field(default=MessageType.STREAM_OPEN, init=False, repr=False)


@dataclass
class StreamData:
    stream_id: int
    data: bytes
    ws_type: str | None = None
    Type: str = field(default=MessageType.STREAM_DATA, init=False, repr=False)


@dataclass
class StreamClose:
    stream_id: int
    code: int | None = None
    reason: str | None = None
    Type: str = field(default=MessageType.STREAM_CLOSE, init=False, repr=False)


@dataclass
class StreamReset:
    stream_id: int
    reason: str = ""
    Type: str = field(default=MessageType.STREAM_RESET, init=False, repr=False)


@dataclass
class Heartbeat:
    Type: str = field(default=MessageType.HEARTBEAT, init=False, repr=False)


@dataclass
class HeartbeatAck:
    Type: str = field(
        default=MessageType.HEARTBEAT_ACK, init=False, repr=False
    )


@dataclass
class Error:
    code: str
    message: str
    Type: str = field(default=MessageType.ERROR, init=False, repr=False)


Message = (
    Auth
    | TunnelCreate
    | TunnelCreated
    | StreamOpen
    | StreamData
    | StreamClose
    | StreamReset
    | Heartbeat
    | HeartbeatAck
    | Error
)

MESSAGE_TYPES: dict[str, type] = {
    MessageType.AUTH: Auth,
    MessageType.TUNNEL_CREATE: TunnelCreate,
    MessageType.TUNNEL_CREATED: TunnelCreated,
    MessageType.STREAM_OPEN: StreamOpen,
    MessageType.STREAM_DATA: StreamData,
    MessageType.STREAM_CLOSE: StreamClose,
    MessageType.STREAM_RESET: StreamReset,
    MessageType.HEARTBEAT: Heartbeat,
    MessageType.HEARTBEAT_ACK: HeartbeatAck,
    MessageType.ERROR: Error,
}

_DATA_CLASS_FIELDS: ClassVar = frozenset({"Type"})


def serialize(msg: Any) -> bytes:
    data: dict[str, object] = {}
    for f in fields(msg):
        if f.name in _DATA_CLASS_FIELDS:
            continue
        value = getattr(msg, f.name)
        if value is None:
            continue
        data[f.name] = value
    data["Type"] = getattr(msg, "Type")
    return msgpack.packb(data, use_bin_type=True)


def deserialize(data: bytes) -> Message:
    msg_dict = msgpack.unpackb(
        data,
        raw=False,
        strict_map_key=True,
        max_bin_len=MAX_MESSAGE_SIZE,
        max_str_len=MAX_MESSAGE_SIZE,
    )
    if not isinstance(msg_dict, dict):
        raise ValueError("Expected dict, got %r" % type(msg_dict))
    msg_type = msg_dict.get("Type")
    if not isinstance(msg_type, str):
        raise ValueError("Message missing or invalid Type field")
    msg_class = MESSAGE_TYPES.get(msg_type)
    if msg_class is None:
        raise ValueError("Unknown message type: %s" % msg_type)
    msg_dict.pop("Type", None)
    field_names = {f.name for f in fields(msg_class)}
    kwargs = {k: v for k, v in msg_dict.items() if k in field_names}
    return msg_class(**kwargs)

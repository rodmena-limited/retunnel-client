from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Final, Union, cast

import msgpack
from typing_extensions import TypeAlias


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


# Wire-format version (issuedb #48).
#
# v1 is what every 3.0.x client speaks: the HTTP verb rides in a "Method"
# header, headers are a dict (so duplicates collapse), a request body travels
# inside the StreamOpen frame, and every StreamData frame is a complete unit
# (so a WebSocket message larger than MAX_CHUNK_SIZE arrives as several).
#
# v2 adds a first-class `method`, ordered header pairs, `fin`-framed StreamData
# (messages of any size are reassembled before delivery) and request bodies
# streamed as StreamData after the StreamOpen.
#
# Negotiation: the client advertises the highest version it supports in
# Auth.version; the server answers with the version in force in
# HeartbeatAck.version. A field that is unset means v1, so a peer that has
# never heard of the field keeps working unchanged -- every v2 addition is an
# OPTIONAL field on an EXISTING message type, never a new type, because a v1
# deserializer raises on an unknown Type but silently drops unknown fields.
PROTOCOL_VERSION = 2

MAX_CHUNK_SIZE = 64 * 1024
MAX_STREAMS_PER_CLIENT = 256
MAX_MESSAGE_SIZE = 10 * 1024 * 1024
# Largest single frame either side may put on the wire: the biggest payload
# plus msgpack/header overhead. Both transports must accept at least this much
# (the client passes it to websockets as max_size). The 3.0.x client left the
# library default of 1 MiB in place, so any request body above that closed the
# control connection with 1009 (audit #47 B1).
MAX_FRAME_SIZE = MAX_MESSAGE_SIZE + 64 * 1024

# Headers on the wire: v1 dict, v2 ordered list of [name, value] pairs.
Headers: TypeAlias = Union["dict[str, str]", "list[list[str]]"]


def negotiate_version(peer_version: int | None) -> int:
    """Version in force for a connection given what the peer advertised."""
    if not isinstance(peer_version, int) or peer_version < 1:
        return 1
    return min(PROTOCOL_VERSION, peer_version)


def header_pairs(headers: Any) -> list[tuple[str, str]]:
    """Normalise either wire form to an ordered list of (name, value).

    Tolerates malformed entries (a pair with the wrong arity, a non-str value)
    by skipping them rather than failing the whole request.
    """
    if not headers:
        return []
    if isinstance(headers, dict):
        return [(str(k), str(v)) for k, v in headers.items()]
    pairs: list[tuple[str, str]] = []
    for item in headers:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            pairs.append((str(item[0]), str(item[1])))
    return pairs


# Header fields whose duplicates must NOT be comma-joined (RFC 9110 s5.3 /
# RFC 6265): Set-Cookie cannot be combined at all and Cookie uses "; ".
_SEMICOLON_JOIN: Final = frozenset({"cookie"})
_NEVER_JOIN: Final = frozenset({"set-cookie"})


def headers_dict(pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Collapse ordered pairs to the v1 dict form, combining duplicates the
    way RFC 9110 allows (comma-joined, "; " for Cookie, first-wins for
    Set-Cookie). Used only when talking to a v1 peer.
    """
    out: dict[str, str] = {}
    seen_lower: dict[str, str] = {}
    for name, value in pairs:
        lower = name.lower()
        key = seen_lower.get(lower)
        if key is None:
            seen_lower[lower] = name
            out[name] = value
        elif lower in _NEVER_JOIN:
            continue
        elif lower in _SEMICOLON_JOIN:
            out[key] = f"{out[key]}; {value}"
        else:
            out[key] = f"{out[key]}, {value}"
    return out


@dataclass
class Auth:
    token: str
    # v2: highest protocol version the client supports (absent => v1).
    version: int | None = None
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
    headers: Headers = field(default_factory=dict)
    body: bytes = b""
    # v2: the HTTP verb. v1 carries it as a leading "Method" header.
    method: str | None = None
    # v2: True => the request body follows as StreamData frames ending with
    # fin=True (the StreamOpen itself carries no body).
    has_body: bool | None = None
    Type: str = field(default=MessageType.STREAM_OPEN, init=False, repr=False)


@dataclass
class StreamData:
    stream_id: int
    data: bytes
    ws_type: str | None = None
    # v2 framing: False => more frames of this message follow; True => last
    # frame of the message. None => v1, every frame is a complete unit.
    fin: bool | None = None
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
    # v2: sent by the server right after a successful Auth with the protocol
    # version in force for this connection (absent => v1).
    version: int | None = None
    Type: str = field(
        default=MessageType.HEARTBEAT_ACK, init=False, repr=False
    )


@dataclass
class Error:
    code: str
    message: str
    Type: str = field(default=MessageType.ERROR, init=False, repr=False)


Message: TypeAlias = Union[
    Auth,
    TunnelCreate,
    TunnelCreated,
    StreamOpen,
    StreamData,
    StreamClose,
    StreamReset,
    Heartbeat,
    HeartbeatAck,
    Error,
]

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

_DATA_CLASS_FIELDS: Final = frozenset({"Type"})


def serialize(msg: Any) -> bytes:
    data: dict[str, object] = {}
    for f in fields(msg):
        if f.name in _DATA_CLASS_FIELDS:
            continue
        value = getattr(msg, f.name)
        if value is None:
            continue
        data[f.name] = value
    data["Type"] = msg.Type
    return cast(bytes, msgpack.packb(data, use_bin_type=True))


def deserialize(data: bytes) -> Message:
    msg_dict = msgpack.unpackb(
        data,
        raw=False,
        strict_map_key=True,
        max_bin_len=MAX_MESSAGE_SIZE,
        max_str_len=MAX_MESSAGE_SIZE,
    )
    if not isinstance(msg_dict, dict):
        raise TypeError(f"Expected dict, got {type(msg_dict)!r}")
    msg_type = msg_dict.get("Type")
    if not isinstance(msg_type, str):
        raise TypeError("Message missing or invalid Type field")
    msg_class = MESSAGE_TYPES.get(msg_type)
    if msg_class is None:
        raise ValueError(f"Unknown message type: {msg_type}")
    msg_dict.pop("Type", None)
    # Unknown fields are dropped on purpose: that is what lets a newer peer
    # add optional fields without breaking an older one.
    field_names = {f.name for f in fields(msg_class)}
    kwargs = {k: v for k, v in msg_dict.items() if k in field_names}
    return cast(Message, msg_class(**kwargs))

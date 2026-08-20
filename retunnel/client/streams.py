"""Per-stream plumbing shared by the HTTP, WebSocket and TCP handlers.

A StreamState holds the frames the server sent for one stream; `next_message`
reassembles v2 `fin` framing so a handler always sees whole messages.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
from typing import Union

from typing_extensions import TypeAlias

from retunnel.msg.messages import (
    MAX_CHUNK_SIZE,
    StreamClose,
    StreamData,
    StreamOpen,
    StreamReset,
    header_pairs,
    serialize,
)

# Per-stream inbound queue cap for server->client frames. A local consumer that
# is slower than the server must not let memory grow without bound.
MAX_STREAM_QUEUE = 256

InboundMsg: TypeAlias = Union[StreamData, StreamClose, StreamReset]
# A reassembled item: ("data", payload, ws_type) or ("close", code, reason).
Message: TypeAlias = "tuple[str, bytes | int | None, str | None]"
SendRaw: TypeAlias = "Callable[[bytes], Awaitable[None]]"


class StreamState:
    def __init__(self, stream_id: int) -> None:
        self.stream_id = stream_id
        self.queue: asyncio.Queue[InboundMsg] = asyncio.Queue(
            maxsize=MAX_STREAM_QUEUE
        )
        self.task: asyncio.Task[None] | None = None
        self._partial: list[bytes] = []
        self._partial_type: str | None = None

    async def next_frame(self) -> InboundMsg:
        return await self.queue.get()

    async def next_message(self) -> Message:
        """Next whole message: ("data", bytes, ws_type) or ("close", code,
        reason). v2 frames are accumulated until fin=True; a v1 frame (fin is
        None) is a whole message by itself."""
        while True:
            msg = await self.queue.get()
            if isinstance(msg, StreamClose):
                return ("close", msg.code, msg.reason)
            if isinstance(msg, StreamReset):
                return ("close", 1011, msg.reason or "reset by server")
            if msg.fin is None and not self._partial:
                return ("data", msg.data, msg.ws_type)
            self._partial.append(msg.data)
            if self._partial_type is None:
                self._partial_type = msg.ws_type
            if msg.fin is None or msg.fin:
                whole = b"".join(self._partial)
                whole_type = self._partial_type
                self._partial = []
                self._partial_type = None
                return ("data", whole, whole_type)


class Sender:
    """Outbound side of one stream: frames the payload for the negotiated
    protocol version and writes to the control socket."""

    def __init__(self, send_raw: SendRaw, stream_id: int, v2: bool) -> None:
        self._send_raw = send_raw
        self.stream_id = stream_id
        self.v2 = v2

    async def message(self, data: bytes, ws_type: str | None = None) -> None:
        """One whole message, split into MAX_CHUNK_SIZE frames. With a v2
        peer the frames carry `fin` so the server reassembles; with a v1 peer
        a large message is sent as one frame (the server's limit is 16 MiB)
        because splitting would break its boundaries."""
        if not self.v2:
            await self._send_raw(
                serialize(StreamData(self.stream_id, data, ws_type))
            )
            return
        chunks = [
            data[i : i + MAX_CHUNK_SIZE]
            for i in range(0, len(data), MAX_CHUNK_SIZE)
        ] or [b""]
        last = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            await self._send_raw(
                serialize(
                    StreamData(self.stream_id, chunk, ws_type, fin=(i == last))
                )
            )

    async def chunk(self, data: bytes) -> None:
        """One body chunk of a byte stream (HTTP response body)."""
        await self._send_raw(serialize(StreamData(self.stream_id, data)))

    async def close(
        self, code: int | None = None, reason: str | None = None
    ) -> None:
        await self._send_raw(
            serialize(StreamClose(self.stream_id, code=code, reason=reason))
        )

    async def reset(self, reason: str) -> None:
        await self._send_raw(
            serialize(StreamReset(self.stream_id, reason=reason[:200]))
        )


def open_headers(msg: StreamOpen) -> list[tuple[str, str]]:
    """Request headers from a StreamOpen in either wire form, minus the verb
    a v1 server smuggles in as a header."""
    return [
        (k, v)
        for k, v in header_pairs(msg.headers)
        if k.lower() not in ("method", ":method")
    ]


def open_method(msg: StreamOpen) -> str:
    if msg.method:
        return msg.method
    for k, v in header_pairs(msg.headers):
        if k.lower() in ("method", ":method"):
            return v
    return "GET"


def basic_auth_ok(headers: list[tuple[str, str]], expected: str) -> bool:
    """`expected` is "user:pass" from -a/--auth."""
    want = "Basic " + base64.b64encode(expected.encode()).decode()
    for k, v in headers:
        if k.lower() == "authorization" and v.strip() == want:
            return True
    return False

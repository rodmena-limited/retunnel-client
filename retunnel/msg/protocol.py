from __future__ import annotations

import asyncio
import logging
from typing import Callable, Coroutine

from .messages import (
    MAX_CHUNK_SIZE,
    MAX_STREAMS_PER_CLIENT,
    Message,
    StreamClose,
    StreamData,
    StreamOpen,
    StreamReset,
    deserialize,
    serialize,
)

logger = logging.getLogger(__name__)


class StreamClosedError(Exception):
    pass


class Stream:
    def __init__(self, stream_id: int, tunnel_id: str, mode: str) -> None:
        self.stream_id = stream_id
        self.tunnel_id = tunnel_id
        self.mode = mode
        self._inbound: asyncio.Queue[tuple[bytes, str | None]] = asyncio.Queue()
        self._closed = False
        self._close_code: int | None = None
        self._close_reason: str | None = None
        self._close_event = asyncio.Event()

    def feed_data(self, data: bytes, ws_type: str | None = None) -> None:
        if self._closed:
            return
        self._inbound.put_nowait((data, ws_type))

    def feed_close(self, code: int | None = None, reason: str | None = None) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_code = code
        self._close_reason = reason
        self._close_event.set()
        self._inbound.put_nowait((b"", None))

    async def read(self) -> tuple[bytes, str | None] | None:
        if self._closed and self._inbound.empty():
            return None
        item = await self._inbound.get()
        if self._closed and item == (b"", None):
            return None
        return item

    async def read_all(self) -> bytes:
        chunks: list[bytes] = []
        while True:
            item = await self.read()
            if item is None:
                break
            chunks.append(item[0])
        return b"".join(chunks)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def close_code(self) -> int | None:
        return self._close_code

    @property
    def close_reason(self) -> str | None:
        return self._close_reason

    async def wait_closed(self) -> None:
        await self._close_event.wait()


SendFn = Callable[[Message], Coroutine[None, None, None]]


class StreamMultiplexer:
    def __init__(self, send_fn: SendFn) -> None:
        self._send = send_fn
        self._streams: dict[int, Stream] = {}
        self._next_stream_id = 0
        self._lock = asyncio.Lock()
        self._closed = False

    @property
    def active_streams(self) -> int:
        return len(self._streams)

    @property
    def stream_ids(self) -> set[int]:
        return set(self._streams.keys())

    def get_stream(self, stream_id: int) -> Stream | None:
        return self._streams.get(stream_id)

    async def allocate_stream(
        self, tunnel_id: str, mode: str, path: str = "/",
        headers: dict[str, str] | None = None, body: bytes = b"",
    ) -> Stream:
        async with self._lock:
            if len(self._streams) >= MAX_STREAMS_PER_CLIENT:
                raise RuntimeError("Max streams (%d) exceeded" % MAX_STREAMS_PER_CLIENT)
            stream_id = self._next_stream_id
            self._next_stream_id += 1
            stream = Stream(stream_id, tunnel_id, mode)
            self._streams[stream_id] = stream
        msg = StreamOpen(
            stream_id=stream_id,
            tunnel_id=tunnel_id,
            mode=mode,
            path=path,
            headers=headers or {},
            body=body,
        )
        await self._send(msg)
        return stream

    async def send_data(self, stream_id: int, data: bytes,
                        ws_type: str | None = None) -> None:
        if self._closed:
            raise StreamClosedError("Multiplexer closed")
        for i in range(0, len(data), MAX_CHUNK_SIZE):
            chunk = data[i:i + MAX_CHUNK_SIZE]
            await self._send(StreamData(
                stream_id=stream_id,
                data=chunk,
                ws_type=ws_type,
            ))

    async def send_close(self, stream_id: int, code: int | None = None,
                          reason: str | None = None) -> None:
        await self._send(StreamClose(
            stream_id=stream_id,
            code=code,
            reason=reason,
        ))
        self._remove_stream(stream_id)

    async def send_reset(self, stream_id: int, reason: str = "") -> None:
        await self._send(StreamReset(stream_id=stream_id, reason=reason))
        stream = self._streams.get(stream_id)
        if stream:
            stream.feed_close()
        self._remove_stream(stream_id)

    async def dispatch(self, msg: Message) -> None:
        if isinstance(msg, StreamData):
            stream = self._streams.get(msg.stream_id)
            if stream is None:
                logger.warning("Data for unknown stream %d", msg.stream_id)
                return
            stream.feed_data(msg.data, msg.ws_type)
        elif isinstance(msg, StreamClose):
            stream = self._streams.get(msg.stream_id)
            if stream is None:
                return
            stream.feed_close(msg.code, msg.reason)
            self._remove_stream(msg.stream_id)
        elif isinstance(msg, StreamReset):
            stream = self._streams.get(msg.stream_id)
            if stream is None:
                return
            stream.feed_close()
            self._remove_stream(msg.stream_id)
        elif isinstance(msg, StreamOpen):
            stream = Stream(msg.stream_id, msg.tunnel_id, msg.mode)
            self._streams[msg.stream_id] = stream
        else:
            logger.debug("Non-stream message dispatched to multiplexer: %s",
                          type(msg).__name__)

    def _remove_stream(self, stream_id: int) -> None:
        self._streams.pop(stream_id, None)

    def close_all(self) -> None:
        self._closed = True
        for stream in list(self._streams.values()):
            stream.feed_close()
        self._streams.clear()


def encode(msg: Message) -> bytes:
    return serialize(msg)


def decode(data: bytes) -> Message:
    return deserialize(data)
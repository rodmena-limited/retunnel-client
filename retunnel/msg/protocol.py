from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

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

# Per-stream inbound safety valve. This is NOT the flow-control mechanism --
# real backpressure is applied by the transport read loop (see
# StreamMultiplexer.wait_for_capacity), which stops reading the socket while
# buffered bytes are above the high-water mark, so TCP pushes back on the peer
# and NO data is lost. This per-stream ceiling only guards against a bug in
# which one stream grows without the global accounting noticing, and is set far
# above the global high-water mark so it is not reached in normal operation.
MAX_INBOUND_BYTES = 64 * 1024 * 1024

# Global (per-connection) backpressure thresholds. The read loop pauses at the
# high-water mark and resumes once buffered bytes fall to the low-water mark;
# the hysteresis avoids thrashing on every chunk.
GLOBAL_INBOUND_HIGH_WATER = 16 * 1024 * 1024
GLOBAL_INBOUND_LOW_WATER = 4 * 1024 * 1024


class StreamClosedError(Exception):
    pass


def _is_power_of_two(n: int) -> bool:
    """Used to log the 1st, 2nd, 4th, 8th... occurrence of a repeating event.

    A misbehaving or hostile peer can drive a rejected code path as fast as it
    can send frames; one log line per frame converts that into unbounded disk
    consumption. Backing off exponentially keeps the signal (it is visible, and
    the count is exact) without letting the peer choose the log volume.
    """
    return n > 0 and (n & (n - 1)) == 0


class Stream:
    def __init__(
        self,
        stream_id: int,
        tunnel_id: str,
        mode: str,
        on_release: Callable[[int], None] | None = None,
    ) -> None:
        self.stream_id = stream_id
        self.tunnel_id = tunnel_id
        self.mode = mode
        self._inbound: asyncio.Queue[tuple[bytes, str | None]] = (
            asyncio.Queue()
        )
        self._inbound_bytes = 0
        self._closed = False
        self._aborted = False
        self._close_code: int | None = None
        self._close_reason: str | None = None
        self._close_event = asyncio.Event()
        # Notifies the owning multiplexer that N buffered bytes were released,
        # so global backpressure accounting stays accurate.
        self._on_release = on_release

    @property
    def buffered_bytes(self) -> int:
        return self._inbound_bytes

    def feed_data(self, data: bytes, ws_type: str | None = None) -> bool:
        """Queue one chunk. Returns False when closed or past the safety valve."""
        if self._closed:
            return False
        if self._inbound_bytes + len(data) > MAX_INBOUND_BYTES:
            return False
        self._inbound.put_nowait((data, ws_type))
        self._inbound_bytes += len(data)
        return True

    def feed_close(
        self, code: int | None = None, reason: str | None = None
    ) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_code = code
        self._close_reason = reason
        self._close_event.set()
        try:
            self._inbound.put_nowait((b"", None))
        except asyncio.QueueFull:
            # Buffer already full of data; the reader will observe `closed`
            # and `empty` after draining and return None.
            pass

    def feed_abort(self, reason: str | None = None) -> None:
        """Close the stream ABNORMALLY (peer reset / buffer blowout).

        A reader that drains to the end must be able to tell "the response
        finished" from "the response was cut off", otherwise a truncated body
        is indistinguishable from a complete one and gets served as a clean
        200 -- silent data corruption.
        """
        self._aborted = True
        self.feed_close(code=1011, reason=reason)

    @property
    def aborted(self) -> bool:
        """True when the stream ended abnormally rather than completing."""
        return self._aborted

    def _release(self, n: int) -> None:
        self._inbound_bytes -= n
        if self._on_release is not None and n:
            self._on_release(n)

    def drain_accounting(self) -> None:
        """Release all buffered bytes from global accounting (on teardown)."""
        if self._inbound_bytes:
            self._release(self._inbound_bytes)

    async def read(self) -> tuple[bytes, str | None] | None:
        if self._closed and self._inbound.empty():
            return None
        item = await self._inbound.get()
        if self._closed and item == (b"", None):
            return None
        self._release(len(item[0]))
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
    def __init__(
        self, send_fn: SendFn, accept_peer_streams: bool = True
    ) -> None:
        self._send = send_fn
        self._streams: dict[int, Stream] = {}
        self._next_stream_id = 0
        self._lock = asyncio.Lock()
        self._closed = False
        # The server never expects a peer to open streams: every stream is
        # allocated server-side for an inbound public request. Leaving the
        # peer-initiated path open let an authenticated client register
        # unbounded server-side Stream objects, because the
        # MAX_STREAMS_PER_CLIENT cap lived only in allocate_stream().
        self._accept_peer_streams = accept_peer_streams
        self._rejected_peer_opens = 0
        self._buffered_bytes = 0
        self._capacity = asyncio.Event()
        self._capacity.set()

    @property
    def active_streams(self) -> int:
        return len(self._streams)

    @property
    def buffered_bytes(self) -> int:
        """Total inbound bytes buffered across all streams on this connection."""
        return self._buffered_bytes

    @property
    def has_capacity(self) -> bool:
        """False while buffered data is above the high-water mark."""
        return self._capacity.is_set()

    def _account_reserve(self, n: int) -> None:
        self._buffered_bytes += n
        if self._buffered_bytes >= GLOBAL_INBOUND_HIGH_WATER:
            self._capacity.clear()

    def _account_release(self, n: int) -> None:
        self._buffered_bytes -= n
        if self._buffered_bytes < 0:
            self._buffered_bytes = 0
        if self._buffered_bytes <= GLOBAL_INBOUND_LOW_WATER:
            self._capacity.set()

    async def wait_for_capacity(self, timeout: float | None = None) -> bool:
        """Block while buffered data is above the high-water mark.

        The transport read loop awaits this before reading the next frame. Not
        reading stops draining the socket, so TCP flow control pushes back on
        the peer and it stops sending -- which is what real backpressure is.
        Returns False if the timeout expired while still over budget.
        """
        if self._capacity.is_set():
            return True
        try:
            if timeout is None:
                await self._capacity.wait()
            else:
                await asyncio.wait_for(self._capacity.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def stream_ids(self) -> set[int]:
        return set(self._streams.keys())

    def get_stream(self, stream_id: int) -> Stream | None:
        return self._streams.get(stream_id)

    async def allocate_stream(
        self,
        tunnel_id: str,
        mode: str,
        path: str = "/",
        headers: dict[str, str] | None = None,
        body: bytes = b"",
    ) -> Stream:
        async with self._lock:
            if len(self._streams) >= MAX_STREAMS_PER_CLIENT:
                raise RuntimeError(
                    f"Max streams ({MAX_STREAMS_PER_CLIENT}) exceeded"
                )
            stream_id = self._next_stream_id
            self._next_stream_id += 1
            stream = Stream(
                stream_id, tunnel_id, mode, on_release=self._account_release
            )
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

    async def send_data(
        self, stream_id: int, data: bytes, ws_type: str | None = None
    ) -> None:
        if self._closed:
            raise StreamClosedError("Multiplexer closed")
        for i in range(0, len(data), MAX_CHUNK_SIZE):
            chunk = data[i : i + MAX_CHUNK_SIZE]
            await self._send(
                StreamData(
                    stream_id=stream_id,
                    data=chunk,
                    ws_type=ws_type,
                )
            )

    async def send_close(
        self,
        stream_id: int,
        code: int | None = None,
        reason: str | None = None,
    ) -> None:
        await self._send(
            StreamClose(
                stream_id=stream_id,
                code=code,
                reason=reason,
            )
        )
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
                logger.debug("Data for unknown stream %d", msg.stream_id)
                return
            if stream.feed_data(msg.data, msg.ws_type):
                self._account_reserve(len(msg.data))
            elif not stream.closed:
                # Past the per-stream safety valve. Backpressure should have
                # prevented this, so treat it as abnormal: mark the stream
                # ABORTED so the reader reports a truncated body as an error
                # rather than serving a short response as a clean success.
                logger.warning(
                    "Stream %d exceeded per-stream buffer ceiling; aborting",
                    msg.stream_id,
                )
                stream.feed_abort(reason="buffer overflow")
                await self.send_reset(msg.stream_id, reason="buffer overflow")
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
            # A reset is an abnormal end, not a graceful one.
            stream.feed_abort(reason=msg.reason or "peer reset")
            self._remove_stream(msg.stream_id)
        elif isinstance(msg, StreamOpen):
            if not self._accept_peer_streams:
                # Server side: peers never open streams. Registering them here
                # bypassed MAX_STREAMS_PER_CLIENT entirely (the cap lives in
                # allocate_stream), letting one authenticated connection grow
                # server memory without bound.
                self._rejected_peer_opens += 1
                # Log the first rejection per connection, then back off
                # exponentially. Emitting a line per rejected frame turns a
                # cheap client-side loop into unbounded log growth -- a
                # disk-fill vector with the same shape as the bug being fixed.
                if _is_power_of_two(self._rejected_peer_opens):
                    logger.warning(
                        "Rejected %d peer-initiated StreamOpen frame(s) on "
                        "this connection (latest stream %d)",
                        self._rejected_peer_opens,
                        msg.stream_id,
                    )
                await self.send_reset(
                    msg.stream_id, reason="peer-initiated streams not accepted"
                )
                return
            if msg.stream_id in self._streams:
                # A client cannot open a stream id the server already owns;
                # silently dropping prevents stream hijacking via id collision.
                logger.warning(
                    "Duplicate StreamOpen for stream %d", msg.stream_id
                )
                return
            if len(self._streams) >= MAX_STREAMS_PER_CLIENT:
                # Same cap as allocate_stream. Enforcing it on only one of the
                # two registration paths is how the limit was bypassed.
                self._rejected_peer_opens += 1
                if _is_power_of_two(self._rejected_peer_opens):
                    logger.warning(
                        "Peer exceeded MAX_STREAMS_PER_CLIENT (%d); rejected "
                        "%d StreamOpen frame(s) on this connection",
                        MAX_STREAMS_PER_CLIENT,
                        self._rejected_peer_opens,
                    )
                await self.send_reset(msg.stream_id, reason="too many streams")
                return
            stream = Stream(
                msg.stream_id,
                msg.tunnel_id,
                msg.mode,
                on_release=self._account_release,
            )
            self._streams[msg.stream_id] = stream
        else:
            logger.debug(
                "Non-stream message dispatched to multiplexer: %s",
                type(msg).__name__,
            )

    def _remove_stream(self, stream_id: int) -> None:
        stream = self._streams.pop(stream_id, None)
        if stream is not None:
            # Release whatever this stream still had buffered. Without this the
            # global counter only ever grows for streams torn down before being
            # fully drained (public client disconnects mid-response), and the
            # read loop would stay paused forever -- a wedged tunnel.
            stream.drain_accounting()

    def close_all(self) -> None:
        self._closed = True
        for stream in list(self._streams.values()):
            stream.feed_close()
            stream.drain_accounting()
        self._streams.clear()
        self._buffered_bytes = 0
        self._capacity.set()


def encode(msg: Message) -> bytes:
    return serialize(msg)


def decode(data: bytes) -> Message:
    return deserialize(data)

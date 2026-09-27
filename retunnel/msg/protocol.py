from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

from .messages import (
    MAX_CHUNK_SIZE,
    MAX_STREAMS_PER_CLIENT,
    Headers,
    Message,
    StreamClose,
    StreamData,
    StreamOpen,
    StreamReset,
    deserialize,
    serialize,
)
from .stream import (
    MAX_INBOUND_BYTES,
    MAX_MESSAGE_BYTES,
    MessageTooLarge,
    Stream,
    StreamClosedError,
)

logger = logging.getLogger(__name__)

# Global (per-connection) backpressure thresholds. The read loop pauses at the
# high-water mark and resumes once buffered bytes fall to the low-water mark;
# the hysteresis avoids thrashing on every chunk.
GLOBAL_INBOUND_HIGH_WATER = 16 * 1024 * 1024
GLOBAL_INBOUND_LOW_WATER = 4 * 1024 * 1024


def _is_power_of_two(n: int) -> bool:
    """Used to log the 1st, 2nd, 4th, 8th... occurrence of a repeating event.

    A misbehaving or hostile peer can drive a rejected code path as fast as it
    can send frames; one log line per frame converts that into unbounded disk
    consumption. Backing off exponentially keeps the signal (it is visible, and
    the count is exact) without letting the peer choose the log volume.
    """
    return n > 0 and (n & (n - 1)) == 0


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
        # Protocol version negotiated with the peer (messages.PROTOCOL_VERSION
        # semantics). Decides whether send_data() frames messages with `fin`.
        self.peer_version = 1
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
        headers: Headers | None = None,
        body: bytes = b"",
        *,
        method: str | None = None,
        has_body: bool | None = None,
    ) -> Stream:
        """Register a new stream and send its StreamOpen.

        `headers` is a dict for a v1 peer or a list of [name, value] pairs
        for a v2 peer; `method`/`has_body` are the v2 fields (left unset for
        a v1 peer so they never appear on the wire).
        """
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
            headers=headers if headers is not None else {},
            body=body,
            method=method,
            has_body=has_body,
        )
        await self._send(msg)
        return stream

    async def send_frame(
        self,
        stream_id: int,
        data: bytes,
        ws_type: str | None = None,
        *,
        fin: bool | None,
    ) -> None:
        """Send ONE frame of a message (used to stream a body whose total
        size is not known up front: fin=False per chunk, then an empty frame
        with fin=True)."""
        if self._closed:
            raise StreamClosedError("Multiplexer closed")
        await self._send(
            StreamData(
                stream_id=stream_id, data=data, ws_type=ws_type, fin=fin
            )
        )

    async def send_data(
        self,
        stream_id: int,
        data: bytes,
        ws_type: str | None = None,
        *,
        framed: bool | None = None,
    ) -> None:
        """Send one message, split into MAX_CHUNK_SIZE frames.

        With a v2 peer (`framed`, defaulting to peer_version >= 2) every
        frame carries `fin` so the receiver reassembles the message; an empty
        message is one frame with fin=True. With a v1 peer frames carry no
        `fin` and an empty message sends nothing (its historical behaviour).
        """
        if self._closed:
            raise StreamClosedError("Multiplexer closed")
        if framed is None:
            framed = self.peer_version >= 2
        chunks = [
            data[i : i + MAX_CHUNK_SIZE]
            for i in range(0, len(data), MAX_CHUNK_SIZE)
        ]
        if not chunks and framed:
            chunks = [b""]
        last = len(chunks) - 1
        for i, chunk in enumerate(chunks):
            await self.send_frame(
                stream_id,
                chunk,
                ws_type,
                fin=(i == last) if framed else None,
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
            # A reset is abnormal on our side too: a local reader must not
            # mistake it for a clean end.
            stream.feed_abort(reason=reason or "reset")
        self._remove_stream(stream_id)

    async def dispatch(self, msg: Message) -> None:
        if isinstance(msg, StreamData):
            stream = self._streams.get(msg.stream_id)
            if stream is None:
                logger.debug("Data for unknown stream %d", msg.stream_id)
                return
            if stream.feed_data(msg.data, msg.ws_type, msg.fin):
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

    def close_all(self, reason: str = "connection closed") -> None:
        """Tear down every stream because the CONNECTION is gone.

        Streams are ABORTED, not closed cleanly: a response that was still
        being relayed has been cut off, and a clean close made proxy_stream
        finish a short body as if it were complete (audit #47 B3 -- the
        "Response content shorter than Content-Length" ASGI errors).
        """
        self._closed = True
        for stream in list(self._streams.values()):
            stream.feed_abort(reason=reason)
            stream.drain_accounting()
        self._streams.clear()
        self._buffered_bytes = 0
        self._capacity.set()


def encode(msg: Message) -> bytes:
    return serialize(msg)


def decode(data: bytes) -> Message:
    return deserialize(data)


__all__ = [
    "GLOBAL_INBOUND_HIGH_WATER",
    "GLOBAL_INBOUND_LOW_WATER",
    "MAX_INBOUND_BYTES",
    "MAX_MESSAGE_BYTES",
    "MessageTooLarge",
    "Stream",
    "StreamClosedError",
    "StreamMultiplexer",
    "decode",
    "encode",
]

"""One multiplexed stream's inbound buffer and reader (split from protocol.py)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from typing_extensions import TypeAlias

# One queued item: (payload, ws_type, fin). See Stream.feed_data.
Frame: TypeAlias = "tuple[bytes, str | None, bool | None]"
# End-of-stream marker. A distinct object (not an empty frame) so an empty
# WebSocket message or an empty chunk is never mistaken for EOF.
_EOF = None

# Per-stream inbound safety valve. This is NOT the flow-control mechanism --
# real backpressure is applied by the transport read loop (see
# StreamMultiplexer.wait_for_capacity), which stops reading the socket while
# buffered bytes are above the high-water mark, so TCP pushes back on the peer
# and NO data is lost. This per-stream ceiling only guards against a bug in
# which one stream grows without the global accounting noticing, and is set far
# above the global high-water mark so it is not reached in normal operation.
MAX_INBOUND_BYTES = 64 * 1024 * 1024
MAX_MESSAGE_BYTES = 16 * 1024 * 1024


class StreamClosedError(Exception):
    pass


class MessageTooLarge(Exception):
    """A reassembled message exceeded its size cap; the stream is aborted."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f"message larger than {max_bytes} bytes")
        self.max_bytes = max_bytes


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
        # Items are (data, ws_type, fin) frames; end-of-stream is the
        # distinct _EOF sentinel, never an empty frame, so an empty payload
        # can never be mistaken for EOF (audit #47 G4).
        self._inbound: asyncio.Queue[Frame | None] = asyncio.Queue()
        # Frames of a v2 message being reassembled by read_message().
        self._partial: list[bytes] = []
        self._partial_type: str | None = None
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

    def feed_data(
        self,
        data: bytes,
        ws_type: str | None = None,
        fin: bool | None = None,
    ) -> bool:
        """Queue one frame. Returns False when closed or past the safety valve.

        `fin` is the v2 framing flag (False: more frames of this message
        follow, True: last frame, None: v1 -- the frame is a whole unit).
        """
        if self._closed:
            return False
        if self._inbound_bytes + len(data) > MAX_INBOUND_BYTES:
            return False
        self._inbound.put_nowait((data, ws_type, fin))
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
        self._inbound.put_nowait(_EOF)

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

    async def _next_item(self) -> Frame | None:
        if self._closed and self._inbound.empty():
            return None
        item = await self._inbound.get()
        if item is _EOF or item is None:
            return None
        return item

    async def read_frame(self) -> Frame | None:
        """Next raw frame as (data, ws_type, fin), or None at end of stream."""
        item = await self._next_item()
        if item is not None:
            self._release(len(item[0]))
        return item

    async def read(self) -> tuple[bytes, str | None] | None:
        """Next frame as (data, ws_type), or None at end of stream.

        Frame-level read: a v2 message split across several frames arrives
        here as several items. Use read_message() when boundaries matter.
        """
        frame = await self.read_frame()
        if frame is None:
            return None
        return frame[0], frame[1]

    async def read_message(
        self, max_bytes: int = MAX_MESSAGE_BYTES
    ) -> tuple[bytes, str | None] | None:
        """Next complete message, reassembling v2 `fin` framing.

        A v1 frame (fin is None) is a whole message by itself. For v2 frames,
        data is accumulated until a frame with fin=True. If the stream ends
        in the middle of a message, the stream is marked aborted and None is
        returned: a partial message must never be delivered as a whole one.

        Bytes of a message being reassembled stay counted against the
        stream's and the connection's inbound budget until the message is
        delivered, so a peer that never sends `fin` is held by backpressure
        and MAX_INBOUND_BYTES. A message larger than `max_bytes` aborts the
        stream and raises MessageTooLarge (issuedb #92).
        """
        pending = 0
        try:
            while True:
                frame = await self._next_item()
                if frame is None:
                    if self._partial:
                        self._partial = []
                        self._partial_type = None
                        self._aborted = True
                    return None
                data, ws_type, fin = frame
                pending += len(data)
                if fin is None and not self._partial:
                    if len(data) > max_bytes:
                        self._abort_oversize(max_bytes)
                    return data, ws_type
                self._partial.append(data)
                if self._partial_type is None:
                    self._partial_type = ws_type
                if pending > max_bytes:
                    self._abort_oversize(max_bytes)
                if fin is None or fin:
                    whole = b"".join(self._partial)
                    whole_type = self._partial_type
                    self._partial = []
                    self._partial_type = None
                    return whole, whole_type
        finally:
            if pending:
                self._release(pending)

    def _abort_oversize(self, max_bytes: int) -> None:
        self._partial = []
        self._partial_type = None
        self.feed_abort(reason=f"message larger than {max_bytes} bytes")
        raise MessageTooLarge(max_bytes)

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

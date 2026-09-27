"""HTTP stream handler: one public request -> local app -> response frames."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

import msgpack

from retunnel.msg.messages import StreamClose, StreamData, StreamOpen

from .streams import (
    Sender,
    StreamState,
    basic_auth_ok,
    open_headers,
    open_method,
)

if TYPE_CHECKING:
    from retunnel.local_proxy import LocalProxy, LocalProxyResponse

logger = logging.getLogger(__name__)

# Largest request body accepted from the server (matches the server's cap).
MAX_REQUEST_BODY = 10 * 1024 * 1024
# All request bodies buffered at once in this process (#93): 256 concurrent
# streams x 10 MiB would otherwise let the public exhaust a small client.
MAX_BUFFERED_BODIES = 64 * 1024 * 1024


class BodyBudget:
    in_use = 0

    def __init__(self) -> None:
        self.held = 0

    def take(self, n: int) -> None:
        if BodyBudget.in_use + n > MAX_BUFFERED_BODIES:
            raise ValueError("client busy: request bodies at their memory cap")
        BodyBudget.in_use += n
        self.held += n

    def release(self) -> None:
        BodyBudget.in_use -= self.held
        self.held = 0


async def _collect_body(
    msg: StreamOpen, state: StreamState, budget: BodyBudget
) -> bytes | None:
    """Request body: inline for v1, streamed frames ending with fin=True for
    v2. Returns None if the server closed/reset the stream before the body
    completed."""
    if not msg.has_body:
        return msg.body
    parts: list[bytes] = []
    total = 0
    while True:
        frame = await state.next_frame()
        if isinstance(frame, StreamData):
            if frame.data:
                total += len(frame.data)
                if total > MAX_REQUEST_BODY:
                    raise ValueError("request body larger than 10 MiB")
                budget.take(len(frame.data))
                parts.append(frame.data)
            if frame.fin:
                return b"".join(parts)
        elif isinstance(frame, (StreamClose,)):
            return None
        else:  # StreamReset
            return None


async def _open_unless_abandoned(
    local: LocalProxy,
    method: str,
    msg: StreamOpen,
    headers: list[tuple[str, str]],
    body: bytes,
    state: StreamState,
    sender: Sender,
) -> LocalProxyResponse | None:
    """Open the local request, dropping it if the server closes the stream
    first (#93): a hung local app must not pin a stream the server already
    abandoned at its first-byte timeout."""
    opening = asyncio.ensure_future(
        local.open_http(method, msg.path, headers, body)
    )
    gone = asyncio.ensure_future(state.next_frame())
    try:
        await asyncio.wait(
            {opening, gone}, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        if not gone.done():
            gone.cancel()
    if gone.done() and not gone.cancelled():
        opening.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            resp = await opening
            await resp.close()
        return None
    try:
        return opening.result()
    except Exception as e:
        logger.warning("local %s %s failed: %s", method, msg.path, e)
        await sender.reset(f"{type(e).__name__}: {e}")
        return None


def _meta(status: int, headers: list[tuple[str, str]]) -> bytes:
    return bytes(
        msgpack.packb(
            {"status": status, "headers": [[k, v] for k, v in headers]},
            use_bin_type=True,
        )
    )


async def handle_http_stream(
    msg: StreamOpen,
    state: StreamState,
    sender: Sender,
    local: LocalProxy,
    auth: str | None,
) -> None:
    method = open_method(msg)
    headers = open_headers(msg)

    if auth and not basic_auth_ok(headers, auth):
        # -a user:pass: answer 401 here; the local app is never contacted.
        await sender.message(
            _meta(
                401,
                [
                    ("WWW-Authenticate", 'Basic realm="retunnel"'),
                    ("Content-Type", "text/plain; charset=utf-8"),
                    ("Content-Length", "12"),
                ],
            )
        )
        await sender.chunk(b"Unauthorized")
        await sender.close()
        return

    budget = BodyBudget()
    try:
        try:
            body = await _collect_body(msg, state, budget)
        except ValueError as e:
            await sender.reset(str(e))
            return
        if body is None:
            return  # server gave up on the request before the body arrived
        resp = await _open_unless_abandoned(
            local, method, msg, headers, body, state, sender
        )
    finally:
        budget.release()
    if resp is None:
        return

    try:
        await sender.message(_meta(resp.status_code, resp.header_pairs))
        async for chunk in resp.iter_chunks():
            if not state.queue.empty():
                # Only close/reset can arrive here: the server lost interest.
                break
            await sender.chunk(chunk)
        else:
            await sender.close()
            return
    except Exception as e:
        logger.error(
            "stream %d: relaying response failed: %s", msg.stream_id, e
        )
        try:
            await sender.reset(f"{type(e).__name__}: {e}")
        except Exception:
            logger.debug(
                "stream %d: reset not delivered", msg.stream_id, exc_info=True
            )
    finally:
        await resp.close()

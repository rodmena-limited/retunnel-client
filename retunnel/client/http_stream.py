"""HTTP stream handler: one public request -> local app -> response frames."""

from __future__ import annotations

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
    from retunnel.local_proxy import LocalProxy

logger = logging.getLogger(__name__)

# Largest request body accepted from the server (matches the server's cap).
MAX_REQUEST_BODY = 10 * 1024 * 1024


async def _collect_body(msg: StreamOpen, state: StreamState) -> bytes | None:
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
                parts.append(frame.data)
            if frame.fin:
                return b"".join(parts)
        elif isinstance(frame, (StreamClose,)):
            return None
        else:  # StreamReset
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

    try:
        body = await _collect_body(msg, state)
    except ValueError as e:
        await sender.reset(str(e))
        return
    if body is None:
        return  # server gave up on the request before the body arrived

    try:
        resp = await local.open_http(method, msg.path, headers, body)
    except Exception as e:
        logger.warning("local %s %s failed: %s", method, msg.path, e)
        await sender.reset(f"{type(e).__name__}: {e}")
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

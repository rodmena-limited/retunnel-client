"""WebSocket stream handler: public WS <-> local app WS, via the tunnel.

With a v2 server the local upgrade happens FIRST and its result (101 + the
negotiated subprotocol, or the app's refusal status) is reported back before
the public socket is accepted. Messages are reassembled from `fin` frames so
boundaries and UTF-8 survive any size (audit #47 D1-D5, B2).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import aiohttp
import msgpack

from retunnel.msg.messages import StreamOpen

from .streams import Sender, StreamState, basic_auth_ok, open_headers

if TYPE_CHECKING:
    from retunnel.local_proxy import LocalProxy

logger = logging.getLogger(__name__)


def _subprotocols(headers: list[tuple[str, str]]) -> list[str]:
    out: list[str] = []
    for k, v in headers:
        if k.lower() == "sec-websocket-protocol":
            out.extend(p.strip() for p in v.split(",") if p.strip())
    return out


def _meta(status: int, **extra: object) -> bytes:
    return bytes(msgpack.packb({"status": status, **extra}, use_bin_type=True))


async def _pump_local_to_server(
    ws: aiohttp.ClientWebSocketResponse, sender: Sender
) -> tuple[int | None, str | None]:
    """Relay local messages until the local side closes; returns close info."""
    async for m in ws:
        if m.type == aiohttp.WSMsgType.TEXT:
            await sender.message(m.data.encode("utf-8"), "text")
        elif m.type == aiohttp.WSMsgType.BINARY:
            await sender.message(m.data, "binary")
        elif m.type in (
            aiohttp.WSMsgType.CLOSE,
            aiohttp.WSMsgType.CLOSING,
            aiohttp.WSMsgType.CLOSED,
        ):
            break
        elif m.type == aiohttp.WSMsgType.ERROR:
            raise RuntimeError(f"local websocket error: {ws.exception()}")
    return ws.close_code, None


async def _pump_server_to_local(
    state: StreamState, ws: aiohttp.ClientWebSocketResponse
) -> tuple[int | None, str | None]:
    """Relay reassembled server messages until the server closes the stream."""
    while True:
        kind, payload, ws_type = await state.next_message()
        if kind == "close":
            return (payload if isinstance(payload, int) else None), ws_type
        data = payload if isinstance(payload, bytes) else b""
        if ws_type == "text":
            await ws.send_str(data.decode("utf-8"))
        else:
            await ws.send_bytes(data)


async def handle_ws_stream(
    msg: StreamOpen,
    state: StreamState,
    sender: Sender,
    local: LocalProxy,
    auth: str | None,
) -> None:
    headers = open_headers(msg)
    if auth and not basic_auth_ok(headers, auth):
        if sender.v2:
            await sender.message(
                _meta(
                    401,
                    reason="Unauthorized",
                    headers=[["WWW-Authenticate", 'Basic realm="retunnel"']],
                )
            )
            await sender.close()
        else:
            await sender.reset("Unauthorized")
        return

    subprotocols = _subprotocols(headers)
    clean = [
        (k, v) for k, v in headers if k.lower() != "sec-websocket-protocol"
    ]
    try:
        ws = await local.open_ws(msg.path, clean, subprotocols)
    except aiohttp.WSServerHandshakeError as e:
        logger.info("local WS upgrade %s refused: HTTP %s", msg.path, e.status)
        if sender.v2:
            await sender.message(
                _meta(
                    e.status,
                    reason=e.message,
                    headers=[[k, v] for k, v in (e.headers or {}).items()],
                )
            )
            await sender.close()
        else:
            await sender.reset(
                f"server rejected WebSocket connection: HTTP {e.status}"
            )
        return
    except Exception as e:
        logger.warning("local WS connect %s failed: %s", msg.path, e)
        await sender.reset(f"{type(e).__name__}: {e}")
        return

    local_close: tuple[int | None, str | None] = (None, None)
    server_close: tuple[int | None, str | None] | None = None
    t_local = asyncio.ensure_future(_pump_local_to_server(ws, sender))
    t_server = asyncio.ensure_future(_pump_server_to_local(state, ws))
    try:
        if sender.v2:
            await sender.message(_meta(101, subprotocol=ws.protocol))
        done, _ = await asyncio.wait(
            [t_local, t_server], return_when=asyncio.FIRST_COMPLETED
        )
        for t in done:
            t.result()  # re-raise a pump failure
        if t_server in done:
            server_close = t_server.result()
        if t_local in done:
            local_close = t_local.result()
    except Exception as e:
        logger.error("stream %d: websocket relay failed: %s", msg.stream_id, e)
        try:
            await sender.reset(f"{type(e).__name__}: {e}")
        except Exception:
            logger.debug(
                "stream %d: reset not delivered", msg.stream_id, exc_info=True
            )
        return
    finally:
        for t in (t_local, t_server):
            if not t.done():
                t.cancel()
        await asyncio.gather(t_local, t_server, return_exceptions=True)
        if server_close is not None:
            code, reason = server_close
            await ws.close(code=code or 1000, message=(reason or "").encode())
        else:
            await ws.close()

    if server_close is None:
        # The local app closed first: tell the public side with its code.
        code = local_close[0] if local_close[0] is not None else ws.close_code
        await sender.close(code=code or 1000, reason=local_close[1] or "")

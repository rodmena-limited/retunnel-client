"""Raw TCP stream handler (server-side TCP tunnels are currently disabled)."""

from __future__ import annotations

import asyncio
import logging

from retunnel.local_proxy import LOCAL_HOST, LOCAL_HOSTS
from retunnel.msg.messages import StreamOpen

from .streams import Sender, StreamState

logger = logging.getLogger(__name__)


async def handle_tcp_stream(
    msg: StreamOpen, state: StreamState, sender: Sender, port: int
) -> None:
    reader = None
    writer = None
    last: Exception | None = None
    for host in LOCAL_HOSTS:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            break
        except OSError as e:  # nothing listening on this family
            last = e
    if reader is None or writer is None:
        logger.warning(
            "TCP connect to %s:%d failed on %s: %s",
            LOCAL_HOST,
            port,
            "/".join(LOCAL_HOSTS),
            last,
        )
        await sender.reset(f"{type(last).__name__}: {last}")
        return

    async def local_to_server() -> None:
        while True:
            data = await reader.read(65536)
            if not data:
                return
            await sender.chunk(data)

    async def server_to_local() -> None:
        while True:
            kind, payload, _ = await state.next_message()
            if kind == "close":
                return
            writer.write(payload if isinstance(payload, bytes) else b"")
            await writer.drain()

    t1 = asyncio.ensure_future(local_to_server())
    t2 = asyncio.ensure_future(server_to_local())
    try:
        done, _ = await asyncio.wait(
            [t1, t2], return_when=asyncio.FIRST_COMPLETED
        )
        for t in done:
            t.result()
        if t1 in done:
            await sender.close()
    except Exception as e:
        logger.debug("stream %d: tcp relay ended: %s", msg.stream_id, e)
        await sender.reset(f"{type(e).__name__}: {e}")
    finally:
        for t in (t1, t2):
            if not t.done():
                t.cancel()
        await asyncio.gather(t1, t2, return_exceptions=True)
        writer.close()

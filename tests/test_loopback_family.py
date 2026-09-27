"""issuedb #97 (audit R17): the local app may come back on the other loopback
family, and the client must follow it without a restart.
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from retunnel.local_proxy import LocalProxy


def _ipv6_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@asynccontextmanager
async def _serve(host: str, port: int, body: bytes) -> AsyncIterator[None]:
    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n"
            b"Connection: close\r\n\r\n%s" % (len(body), body)
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, host, port)
    try:
        yield
    finally:
        server.close()
        await server.wait_closed()


async def _get(local: LocalProxy) -> bytes:
    resp = await local.open_http("GET", "/", [("host", "x")], b"")
    try:
        return b"".join([chunk async for chunk in resp.iter_chunks()])
    finally:
        await resp.close()


@pytest.mark.asyncio
@pytest.mark.skipif(not _ipv6_loopback(), reason="no IPv6 loopback here")
async def test_app_rebinding_to_the_other_family_is_followed() -> None:
    port = _free_port()
    local = LocalProxy(port)
    try:
        async with _serve("127.0.0.1", port, b"v4"):
            assert await _get(local) == b"v4"
        async with _serve("::1", port, b"v6"):
            assert await _get(local) == b"v6"
        async with _serve("127.0.0.1", port, b"v4 again"):
            assert await _get(local) == b"v4 again"
    finally:
        await local.close()

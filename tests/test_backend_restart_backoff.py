"""issuedb #100: when the edge says the backend is restarting (502/503/504),
reconnect within FAST_BACKOFF, not after a backoff that has grown to 60 s.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import websockets

from retunnel.client import client as client_mod
from retunnel.client import refusals
from retunnel.client.client import ReTunnelClient, TunnelConfig

from .fake_server import Conn, FakeServer, hold_open


@asynccontextmanager
async def _edge(status: int) -> AsyncIterator[str]:
    async def handle(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(
            b"HTTP/1.1 %d Edge\r\nContent-Length: 0\r\n"
            b"Connection: close\r\n\r\n" % status
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"ws://127.0.0.1:{port}/api/v1/ws/tunnel"
    finally:
        server.close()
        await server.wait_closed()


async def _handshake_error(status: int) -> BaseException:
    async with _edge(status) as url:
        with pytest.raises(Exception) as ei:
            await websockets.connect(url, open_timeout=5)
        return ei.value


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_real_library_error_for_backend_down_is_recognised(
    status: int,
) -> None:
    assert refusals.backend_restarting(await _handshake_error(status))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [404, 429, 500])
async def test_other_statuses_are_not_fast_retried(status: int) -> None:
    assert not refusals.backend_restarting(await _handshake_error(status))


def test_unreachable_host_is_not_fast_retried() -> None:
    assert not refusals.backend_restarting(ConnectionRefusedError())
    assert not refusals.backend_restarting(None)


class _Status(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.response = type("R", (), {"status_code": code})()


@pytest.mark.parametrize("r", [0.0, 0.5, 0.999])
def test_backend_down_caps_a_grown_backoff(r: float) -> None:
    wait, following = refusals.schedule(60.0, _Status(502), r)
    assert wait <= refusals.FAST_BACKOFF == 10.0
    assert following <= refusals.FAST_BACKOFF


@pytest.mark.parametrize("r", [0.0, 0.5, 0.999])
def test_other_failures_keep_the_long_cap(r: float) -> None:
    wait, following = refusals.schedule(60.0, ConnectionRefusedError(), r)
    assert wait <= refusals.MAX_BACKOFF
    assert following == refusals.MAX_BACKOFF
    assert refusals.schedule(60.0, None, 0.999)[0] > refusals.FAST_BACKOFF


def test_fast_rate_fits_the_edge_budget() -> None:
    clients_per_address, edge_refill_per_minute = 10, 60
    assert clients_per_address * 60 / refusals.FAST_BACKOFF <= (
        edge_refill_per_minute
    )


async def _accept(conn: Conn) -> None:
    await conn.expect_auth()
    await conn.expect_create()
    await hold_open(conn)


@pytest.mark.asyncio
async def test_supervisor_retries_fast_after_edge_502(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = refusals.schedule
    waits: list[float] = []

    def grown(
        delay: float, exc: BaseException | None, r: float
    ) -> tuple[float, float]:
        wait, following = real(refusals.MAX_BACKOFF, exc, r)
        waits.append(wait)
        return 0.01, following

    monkeypatch.setattr(client_mod, "schedule", grown)
    async with FakeServer() as srv:
        srv.refuse_statuses = [502, 503]
        srv.on_connection(_accept)
        client = ReTunnelClient(srv.url, "tok")
        try:
            tunnel = await asyncio.wait_for(
                client.request_tunnel(TunnelConfig("http", 1)), 20
            )
            assert tunnel.url.startswith("https://")
        finally:
            await client.close()
    assert len(waits) == 2
    assert all(w <= refusals.FAST_BACKOFF for w in waits)

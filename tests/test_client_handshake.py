"""ReTunnelClient connection state machine (issuedb #50, audit #47 C1/C4/C5)."""

from __future__ import annotations

import asyncio

import pytest

from retunnel.client.client import ReTunnelClient, TunnelConfig
from retunnel.core.exceptions import TerminalError
from retunnel.msg.messages import Heartbeat, HeartbeatAck, serialize

from .fake_server import Conn, FakeServer, hold_open


def _cfg(**kw: object) -> TunnelConfig:
    base: dict[str, object] = {"protocol": "http", "local_port": 1}
    base.update(kw)
    return TunnelConfig(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_v2_negotiation_and_tunnel_created() -> None:
    async def script(conn: Conn) -> None:
        auth = await conn.expect_auth(version=2)
        assert getattr(auth, "version", None) == 2
        create = await conn.expect_create()
        assert getattr(create, "subdomain", None) == "wanted"
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(script)
        client = ReTunnelClient(srv.url, "tok")
        try:
            tunnels = await asyncio.wait_for(
                client.request_tunnel(_cfg(subdomain="wanted")), 5
            )
            assert tunnels.url == "https://wanted.example.test"
            assert client.protocol_version == 2
            assert client.is_connected
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_v1_server_without_version_field() -> None:
    async def script(conn: Conn) -> None:
        await conn.expect_auth(version=None)
        await conn.expect_create()
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(script)
        client = ReTunnelClient(srv.url, "tok")
        try:
            await asyncio.wait_for(client.request_tunnel(_cfg()), 5)
            assert client.protocol_version == 1
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_unauthorized_is_terminal_exit_69() -> None:
    async def script(conn: Conn) -> None:
        await conn.recv()
        from retunnel.msg.messages import Error

        await conn.send(
            Error(code="UNAUTHORIZED", message="Invalid auth token")
        )
        await conn.ws.close(code=1008)

    async with FakeServer() as srv:
        srv.on_connection(script)
        client = ReTunnelClient(srv.url, "bad")
        try:
            with pytest.raises(TerminalError) as ei:
                await asyncio.wait_for(client.request_tunnel(_cfg()), 5)
            assert ei.value.exit_code == 69
            assert await client.wait_closed() == 69
            assert len(srv.connections) == 1  # no retry loop
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_unavailable_subdomain_is_terminal() -> None:
    async def script(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.refuse_create("SUBDOMAIN_UNAVAILABLE", "not yours")
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(script)
        client = ReTunnelClient(srv.url, "tok")
        try:
            with pytest.raises(TerminalError) as ei:
                await asyncio.wait_for(
                    client.request_tunnel(_cfg(subdomain="taken")), 5
                )
            assert ei.value.code == "SUBDOMAIN_UNAVAILABLE"
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_taken_once_then_full_handshake_again() -> None:
    """C1 regression: after a refused TunnelCreate the client must drop the
    socket and redo Auth + TunnelCreate, never idle on a tunnel-less socket."""

    async def first(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.refuse_create("SUBDOMAIN_TAKEN", "in use by another client")
        await hold_open(conn)  # a buggy client would stay here forever

    async def second(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.expect_create()
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(first, second)
        client = ReTunnelClient(srv.url, "tok")
        try:
            tunnel = await asyncio.wait_for(
                client.request_tunnel(_cfg(subdomain="mine")), 10
            )
            assert tunnel.url == "https://mine.example.test"
            auths = [m for m in srv.all_received if type(m).__name__ == "Auth"]
            assert len(auths) == 2  # second connection re-authenticated
            assert len(srv.connections) == 2
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_reconnect_after_server_drop_recreates_same_tunnel() -> None:
    async def first(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.expect_create()
        await conn.ws.close(code=1012, reason="restart")

    async def second(conn: Conn) -> None:
        await conn.expect_auth()
        create = await conn.expect_create()
        assert getattr(create, "subdomain", None) == "fake-sub"
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(first, second)
        client = ReTunnelClient(srv.url, "tok")
        try:
            await asyncio.wait_for(client.request_tunnel(_cfg()), 5)
            for _ in range(100):
                if len(srv.connections) == 2 and client.is_connected:
                    break
                await asyncio.sleep(0.05)
            assert len(srv.connections) == 2
            assert client.is_connected
            assert client.tunnels[0].subdomain == "fake-sub"
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_undecodable_frame_is_ignored_and_heartbeat_answered() -> None:
    acked = asyncio.Event()

    async def script(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.expect_create()
        await conn.send_raw(b"\xc1garbage")
        await conn.send(Heartbeat())
        msg = await conn.recv()
        if isinstance(msg, HeartbeatAck):
            acked.set()
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(script)
        client = ReTunnelClient(srv.url, "tok")
        try:
            await asyncio.wait_for(client.request_tunnel(_cfg()), 5)
            await asyncio.wait_for(acked.wait(), 5)
            assert client.is_connected
        finally:
            await client.close()


@pytest.mark.asyncio
async def test_many_tunnels_one_connection() -> None:
    async def script(conn: Conn) -> None:
        await conn.expect_auth()
        await conn.expect_create()
        await conn.expect_create()
        await hold_open(conn)

    async with FakeServer() as srv:
        srv.on_connection(script)
        client = ReTunnelClient(srv.url, "tok")
        try:
            client.add_tunnel(_cfg(subdomain="a", name="web"))
            client.add_tunnel(_cfg(subdomain="b", name="api", local_port=2))
            tunnels = await asyncio.wait_for(client.start(), 5)
            assert [t.url for t in tunnels] == [
                "https://a.example.test",
                "https://b.example.test",
            ]
            assert len(srv.connections) == 1
        finally:
            await client.close()


def test_serialize_auth_carries_version() -> None:
    from retunnel.msg.messages import Auth, deserialize

    msg = deserialize(serialize(Auth(token="t", version=2)))
    assert getattr(msg, "version", None) == 2

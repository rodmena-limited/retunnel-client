"""A scripted ReTunnel control server for client tests.

Each accepted connection runs `script(conn)`; helpers reply to Auth and
TunnelCreate the way the real server does, so the CLIENT's state machine is
what gets exercised -- not a mock of it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection, serve

from retunnel.msg.messages import (
    Error,
    HeartbeatAck,
    Message,
    TunnelCreated,
    deserialize,
    serialize,
)

Script = Callable[["Conn"], Awaitable[None]]


class Conn:
    def __init__(self, ws: ServerConnection, server: FakeServer) -> None:
        self.ws = ws
        self.server = server
        self.received: list[Message] = []

    async def recv(self, timeout: float = 5.0) -> Message:
        raw = await asyncio.wait_for(self.ws.recv(), timeout)
        msg = deserialize(raw if isinstance(raw, bytes) else raw.encode())
        self.received.append(msg)
        self.server.all_received.append(msg)
        return msg

    async def send(self, msg: Message) -> None:
        await self.ws.send(serialize(msg))

    async def send_raw(self, data: bytes) -> None:
        await self.ws.send(data)

    async def expect_auth(self, version: int | None = 2) -> Message:
        msg = await self.recv()
        assert type(msg).__name__ == "Auth", msg
        await self.send(HeartbeatAck(version=version))
        return msg

    async def expect_create(self, reply: Message | None = None) -> Message:
        msg = await self.recv()
        assert type(msg).__name__ == "TunnelCreate", msg
        sub = getattr(msg, "subdomain", None) or "fake-sub"
        await self.send(
            reply
            or TunnelCreated(url=f"https://{sub}.example.test", subdomain=sub)
        )
        return msg

    async def refuse_create(self, code: str, message: str) -> None:
        await self.expect_create(Error(code=code, message=message))


class FakeServer:
    def __init__(self) -> None:
        self.scripts: list[Script] = []
        self.connections: list[Conn] = []
        self.all_received: list[Message] = []
        self._server: Any = None
        self.port = 0

    def on_connection(self, *scripts: Script) -> None:
        self.scripts.extend(scripts)

    async def _handler(self, ws: ServerConnection) -> None:
        conn = Conn(ws, self)
        self.connections.append(conn)
        idx = len(self.connections) - 1
        script = self.scripts[min(idx, len(self.scripts) - 1)]
        try:
            await script(conn)
        except (websockets.ConnectionClosed, asyncio.TimeoutError):
            return

    async def __aenter__(self) -> FakeServer:
        self._server = await serve(self._handler, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._server.close()
        await self._server.wait_closed()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"


async def hold_open(conn: Conn) -> None:
    """Keep the connection up until the client goes away."""
    while True:
        await conn.recv(timeout=30)

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiohttp
import websockets


class AsyncWsConnection:
    def __init__(self, ws: Any) -> None:
        self.ws = ws

    async def recv(self) -> tuple[bytes, str]:
        msg = await self.ws.recv()
        if isinstance(msg, str):
            return msg.encode("utf-8"), "text"
        return msg, "binary"

    async def send(self, data: bytes, ws_type: str) -> None:
        if ws_type == "text":
            await self.ws.send(data.decode("utf-8"))
        else:
            await self.ws.send(data)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self.ws.close(code, reason)


async def open_ws(
    port: int, path: str, headers: dict[str, str]
) -> AsyncWsConnection:
    url = f"ws://127.0.0.1:{port}{path}"
    subprotocols = []
    if "sec-websocket-protocol" in headers:
        protos = headers["sec-websocket-protocol"].split(",")
        subprotocols = [p.strip() for p in protos if p.strip()]

    # Filter out headers that shouldn't be passed to websockets.connect
    clean_headers = {
        k: v
        for k, v in headers.items()
        if k.lower()
        not in (
            "host",
            "connection",
            "upgrade",
            "sec-websocket-key",
            "sec-websocket-version",
        )
    }

    ws = await websockets.connect(
        url,
        additional_headers=list(clean_headers.items()),
        subprotocols=subprotocols or None,  # type: ignore[arg-type]
    )
    return AsyncWsConnection(ws)


class LocalProxyResponse:
    def __init__(
        self,
        status: int,
        headers: dict[str, str],
        content: aiohttp.StreamReader,
        session: aiohttp.ClientSession,
        resp: aiohttp.ClientResponse,
    ) -> None:
        self.status_code = status
        self.response_headers = headers
        self.response_body = content
        self._session = session
        self._resp = resp

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        async for chunk in self.response_body.iter_any():
            yield chunk

    async def close(self) -> None:
        self._resp.close()
        await self._session.close()


async def open_http(
    port: int, method: str, path: str, headers: dict[str, str], body: bytes
) -> LocalProxyResponse:
    url = f"http://127.0.0.1:{port}{path}"
    session = aiohttp.ClientSession(auto_decompress=False)
    try:
        resp = await session.request(
            method, url, headers=headers, data=body, allow_redirects=False
        )
        return LocalProxyResponse(
            resp.status, dict(resp.headers), resp.content, session, resp
        )
    except Exception:
        await session.close()
        raise

"""Local side of the tunnel: HTTP and WebSocket connections to the user's app.

One aiohttp session per client (keep-alive to the local app, no per-request
connector), requests built from the EXACT target bytes the server relayed
(`yarl.URL(..., encoded=True)` -- never decoded and re-encoded), and the
public Host header passed through on both HTTP and WebSocket upgrades.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import aiohttp
from multidict import CIMultiDict
from yarl import URL

# Automatic headers aiohttp would otherwise add when the public caller did
# not send them; the local app must see the caller's request, not ours.
_SKIP_AUTO = frozenset({"Accept", "Accept-Encoding", "User-Agent"})


class LocalProxyResponse:
    def __init__(self, resp: aiohttp.ClientResponse) -> None:
        self._resp = resp
        self.status_code = resp.status
        # Ordered, duplicates preserved (three Set-Cookie lines stay three).
        self.header_pairs: list[tuple[str, str]] = [
            (
                k.decode("utf-8", "surrogateescape"),
                v.decode("utf-8", "surrogateescape"),
            )
            for k, v in resp.raw_headers
        ]

    async def iter_chunks(self) -> AsyncIterator[bytes]:
        async for chunk in self._resp.content.iter_any():
            yield chunk

    async def close(self) -> None:
        self._resp.release()


class LocalProxy:
    """Connections to the local application on 127.0.0.1:<port>."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                auto_decompress=False,
                # No overall deadline: the server's idle timeout governs
                # long-lived responses (SSE, slow origins).
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
            )
        return self._session

    def url(self, target: str, scheme: str = "http") -> URL:
        if not target.startswith("/"):
            target = "/" + target
        return URL(f"{scheme}://127.0.0.1:{self.port}{target}", encoded=True)

    async def open_http(
        self,
        method: str,
        target: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> LocalProxyResponse:
        resp = await self._get_session().request(
            method,
            self.url(target),
            headers=CIMultiDict(headers),
            data=body if body else None,
            allow_redirects=False,
            skip_auto_headers=_SKIP_AUTO,
        )
        return LocalProxyResponse(resp)

    async def open_ws(
        self,
        target: str,
        headers: list[tuple[str, str]],
        subprotocols: list[str],
    ) -> aiohttp.ClientWebSocketResponse:
        """Upgrade to the local app. Raises aiohttp.WSServerHandshakeError
        (with .status and .headers) when the app refuses the upgrade."""
        return await self._get_session().ws_connect(
            self.url(target, "ws"),
            headers=CIMultiDict(headers),
            protocols=subprotocols,
            autoping=True,
            max_msg_size=0,
            compress=0,
        )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

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

# Loopback addresses tried, in order, when reaching the local application.
#
# Hardcoding 127.0.0.1 meant an app the user could browse at
# http://localhost:PORT answered 502 through the tunnel whenever it was bound
# to ::1 -- the common case on macOS, where localhost resolves to ::1 first and
# many dev servers bind IPv6 only (issuedb #59).
#
# Resolving the NAME "localhost" is NOT a fix: it depends on the host's
# /etc/hosts, and where localhost has no AAAA record (this build machine)
# getaddrinfo returns 127.0.0.1 alone and an IPv6-only app stays unreachable.
# Both literals are therefore tried explicitly, IPv4 first as the common case;
# whichever answers is remembered for the rest of the session.
LOCAL_HOSTS = ("127.0.0.1", "::1")
# The name used in logs and messages.
LOCAL_HOST = "localhost"


def _authority(host: str, port: int) -> str:
    """host:port, bracketing an IPv6 literal as a URL requires."""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


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
    """Connections to the local application on localhost:<port>."""

    def __init__(self, port: int) -> None:
        self.port = port
        self._session: aiohttp.ClientSession | None = None
        # The loopback address that last worked, so only the first request of
        # a session pays for probing both families.
        self._host: str | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                auto_decompress=False,
                # No overall deadline: the server's idle timeout governs
                # long-lived responses (SSE, slow origins).
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=10),
            )
        return self._session

    def hosts(self) -> tuple[str, ...]:
        """Loopback addresses to try, best-known first."""
        if self._host is not None:
            return (self._host,)
        return LOCAL_HOSTS

    def url(self, target: str, scheme: str = "http", host: str = "") -> URL:
        if not target.startswith("/"):
            target = "/" + target
        authority = _authority(host or self.hosts()[0], self.port)
        return URL(f"{scheme}://{authority}{target}", encoded=True)

    async def open_http(
        self,
        method: str,
        target: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> LocalProxyResponse:
        last: Exception | None = None
        for host in self.hosts():
            try:
                resp = await self._get_session().request(
                    method,
                    self.url(target, host=host),
                    headers=CIMultiDict(headers),
                    data=body if body else None,
                    allow_redirects=False,
                    skip_auto_headers=_SKIP_AUTO,
                )
            except aiohttp.ClientConnectorError as e:
                last = e  # nothing listening on this family; try the other
                continue
            self._host = host
            return LocalProxyResponse(resp)
        raise last if last is not None else RuntimeError("no loopback address")

    async def open_ws(
        self,
        target: str,
        headers: list[tuple[str, str]],
        subprotocols: list[str],
    ) -> aiohttp.ClientWebSocketResponse:
        """Upgrade to the local app. Raises aiohttp.WSServerHandshakeError
        (with .status and .headers) when the app refuses the upgrade."""
        last: Exception | None = None
        for host in self.hosts():
            try:
                ws = await self._get_session().ws_connect(
                    self.url(target, "ws", host=host),
                    headers=CIMultiDict(headers),
                    protocols=subprotocols,
                    autoping=True,
                    max_msg_size=0,
                    compress=0,
                )
            except aiohttp.ClientConnectorError as e:
                last = e
                continue
            self._host = host
            return ws
        raise last if last is not None else RuntimeError("no loopback address")

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

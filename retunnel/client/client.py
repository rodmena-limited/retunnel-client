"""ReTunnelClient: ONE control connection carrying every tunnel of this
process, supervised by a reconnect loop that redoes the WHOLE handshake
(connect -> Auth -> every TunnelCreate) after any failure.

The 3.0.x client kept an authenticated socket after a failed TunnelCreate and
then sat in its message loop answering heartbeats with no tunnel at all
(audit #47 C1). Here a connection is either fully established -- every
configured tunnel created -- or torn down and retried with jittered backoff;
permanent refusals (bad token, unavailable subdomain) end the client with a
distinct exit code instead of retrying forever (C4).
"""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import websockets
from websockets.protocol import State

from retunnel.core.exceptions import (
    AuthenticationError,
    TerminalError,
    TunnelError,
)
from retunnel.local_proxy import LocalProxy
from retunnel.msg.messages import (
    MAX_FRAME_SIZE,
    PROTOCOL_VERSION,
    Auth,
    Error,
    Heartbeat,
    HeartbeatAck,
    Message,
    StreamClose,
    StreamData,
    StreamOpen,
    StreamReset,
    TunnelCreate,
    TunnelCreated,
    deserialize,
    negotiate_version,
    serialize,
)

from .http_stream import handle_http_stream
from .streams import Sender, StreamState
from .tcp_stream import handle_tcp_stream
from .ws_stream import handle_ws_stream

logger = logging.getLogger(__name__)

HANDSHAKE_TIMEOUT = 20.0
# How long to wait for the peer's WebSocket close handshake on shutdown.
CLOSE_TIMEOUT = 2.0
MAX_BACKOFF = 60.0
# A refusal the server calls transient (SUBDOMAIN_TAKEN while it evicts this
# account's stale session, TUNNEL_CREATE_FAILED while the allocator is
# contended) is retried this many times before the client gives up.
RETRY_BUDGET = 6

# Server error codes that retrying cannot fix -> exit code.
TERMINAL_CODES: dict[str, int] = {
    "UNAUTHORIZED": 69,
    "AUTH_REQUIRED": 69,
    "SUBDOMAIN_UNAVAILABLE": 69,
    "PATH_TAKEN": 69,
    "TCP_DISABLED": 69,
    # Custom hostnames (issuedb #60). All four refusals are terminal: none of
    # them changes by reconnecting, so retrying would spin forever printing
    # the same message.
    "HOSTNAME_NOT_REGISTERED": 69,
    "HOSTNAME_NOT_VERIFIED": 69,
    "HOSTNAME_NO_CERTIFICATE": 69,
    "HOSTNAME_TAKEN": 69,
    "INVALID_PATH": 2,
    "INVALID_HOSTNAME": 2,
    "UNSUPPORTED_PROTOCOL": 2,
}


@dataclass
class TunnelConfig:
    protocol: str
    local_port: int
    name: str | None = None
    auth: str | None = None
    remote_port: int | None = None
    subdomain: str | None = None
    spa: bool = False
    path: str | None = None
    hostname: str | None = None
    inspect: bool = True


@dataclass
class Tunnel:
    id: str
    url: str
    protocol: str
    config: TunnelConfig
    tunnel_id: str = ""
    subdomain: str | None = None
    path: str | None = None


class ReTunnelClient:
    def __init__(
        self, server_addr: str, auth_token: str, ssl_verify: bool = True
    ) -> None:
        self.server_addr = server_addr or "wss://retunnel.net"
        if not self.server_addr.startswith("ws"):
            self.server_addr = f"wss://{self.server_addr}"
        if not self.server_addr.endswith("/api/v1/ws/tunnel"):
            self.server_addr = f"{self.server_addr}/api/v1/ws/tunnel"

        self.auth_token = auth_token
        self.ssl_verify = ssl_verify
        # Version-agnostic socket: websockets >= 11 exposes different protocol
        # classes across releases; guarded by _ws_open() at every access site.
        self.ws: Any = None
        self.protocol_version = 1
        self._running = False
        self._supervisor: asyncio.Task[None] | None = None
        self._configs: list[TunnelConfig] = []
        self._tunnels: dict[int, Tunnel] = {}
        self._ready = asyncio.Event()
        self._wakeup = asyncio.Event()
        self._failed: TerminalError | None = None
        self._streams: dict[int, StreamState] = {}
        self._locals: dict[int, LocalProxy] = {}
        self._bg: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ public API
    def _ws_open(self) -> bool:
        return self.ws is not None and self.ws.state == State.OPEN

    @property
    def is_connected(self) -> bool:
        return self._ws_open() and self._ready.is_set()

    @property
    def tunnels(self) -> list[Tunnel]:
        return [self._tunnels[i] for i in sorted(self._tunnels)]

    def add_tunnel(self, config: TunnelConfig) -> int:
        """Register a tunnel to be created on (re)connect; returns its index."""
        if self._supervisor is not None:
            raise TunnelError("tunnels must be added before start()")
        self._configs.append(config)
        return len(self._configs) - 1

    async def connect(self) -> None:
        """Obtain a token (anonymous registration) if none is configured."""
        if self.auth_token:
            return

        logger.info("No auth token found, registering anonymous user...")
        from retunnel.client.api_client import ReTunnelAPIClient
        from retunnel.client.config_manager import config_manager

        api_url = await config_manager.get_api_url()
        if "localhost" in self.server_addr or "127.0.0.1" in self.server_addr:
            api_url = (
                self.server_addr.replace("wss://", "https://")
                .replace("ws://", "http://")
                .split("/api/v1/")[0]
            )

        async with ReTunnelAPIClient(
            api_url, ssl_verify=self.ssl_verify
        ) as api:
            try:
                result = await api.register_user()
            except Exception as e:
                raise AuthenticationError(
                    f"Failed to register anonymous user: {e}"
                ) from e
            token = result.get("auth_token")
            if not token:
                raise AuthenticationError(
                    "No auth token in registration response"
                )
            self.auth_token = token
            await config_manager.set_auth_token(token)
            logger.info("Successfully registered and saved auth token.")

    async def start(self) -> list[Tunnel]:
        """Connect and create every registered tunnel; returns them once all
        are up. Raises TerminalError when the server refuses permanently."""
        if not self._configs:
            raise TunnelError("no tunnels configured")
        if self._supervisor is None:
            self._running = True
            self._supervisor = asyncio.ensure_future(self._run())
        while True:
            if self._failed is not None:
                raise self._failed
            if self._ready.is_set():
                return self.tunnels
            await self._wakeup.wait()
            self._wakeup.clear()

    async def request_tunnel(self, config: TunnelConfig) -> Tunnel:
        """Convenience for a single tunnel: add + start."""
        idx = self.add_tunnel(config)
        await self.start()
        return self._tunnels[idx]

    async def wait_closed(self) -> int:
        """Block until the supervisor ends; 0 on close(), else the terminal
        exit code."""
        if self._supervisor is not None:
            await asyncio.gather(self._supervisor, return_exceptions=True)
        return self._failed.exit_code if self._failed is not None else 0

    async def close(self) -> None:
        self._running = False
        if self._supervisor is not None and not self._supervisor.done():
            self._supervisor.cancel()
            await asyncio.gather(self._supervisor, return_exceptions=True)
        await self._teardown()
        for local in self._locals.values():
            await local.close()
        self._locals.clear()

    # ------------------------------------------------------------ supervisor
    async def _run(self) -> None:
        delay = 1.0
        attempts = 0
        try:
            while self._running:
                try:
                    await self._handshake()
                    delay, attempts = 1.0, 0
                    self._ready.set()
                    self._wakeup.set()
                    await self._message_loop()
                    logger.warning("Control connection closed by server")
                except TerminalError as e:
                    logger.error("Giving up: %s", e)
                    self._failed = e
                    self._running = False
                except TunnelError as e:
                    attempts += 1
                    logger.error(
                        "Connection error: %s (attempt %d)", e, attempts
                    )
                    if attempts > RETRY_BUDGET:
                        # Keep the server's own message; relabelling every
                        # exhausted-budget failure as SUBDOMAIN_TAKEN reported
                        # the wrong cause (issuedb #58).
                        self._failed = TerminalError(
                            "RETRY_BUDGET_EXHAUSTED", str(e)
                        )
                        self._running = False
                except Exception as e:
                    logger.error("Connection error: %s", e)
                finally:
                    self._ready.clear()
                    await self._teardown()
                    self._wakeup.set()
                if not self._running:
                    break
                wait = delay * (0.5 + random.random())  # jitter, 0.5x..1.5x
                logger.info("Reconnecting in %.1fs", wait)
                await asyncio.sleep(wait)
                delay = min(delay * 2, MAX_BACKOFF)
        finally:
            self._wakeup.set()

    def _ssl_kwargs(self) -> dict[str, Any]:
        if self.ssl_verify or not self.server_addr.startswith("wss://"):
            return {}
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return {"ssl": ctx}

    async def _recv(self, timeout: float) -> Message:
        raw = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        return deserialize(raw)

    @staticmethod
    def _refusal(err: Error) -> Exception:
        exit_code = TERMINAL_CODES.get(err.code)
        if exit_code is not None:
            return TerminalError(err.code, err.message, exit_code)
        return TunnelError(f"{err.message} [{err.code}]")

    async def _handshake(self) -> None:
        self.ws = await websockets.connect(
            self.server_addr,
            max_size=MAX_FRAME_SIZE,
            open_timeout=HANDSHAKE_TIMEOUT,
            **self._ssl_kwargs(),
        )
        await self.ws.send(
            serialize(Auth(token=self.auth_token, version=PROTOCOL_VERSION))
        )
        reply = await self._recv(HANDSHAKE_TIMEOUT)
        if isinstance(reply, Error):
            raise self._refusal(reply)
        if not isinstance(reply, HeartbeatAck):
            raise TunnelError(f"unexpected auth reply: {type(reply).__name__}")
        self.protocol_version = negotiate_version(reply.version)
        logger.info("Authenticated (protocol v%d)", self.protocol_version)

        for idx, cfg in enumerate(self._configs):
            prev = self._tunnels.get(idx)
            if cfg.hostname:
                create = TunnelCreate(
                    protocol=cfg.protocol,
                    hostname=cfg.hostname,
                    remote_port=cfg.remote_port,
                )
            elif cfg.spa or (prev is not None and prev.path):
                create = TunnelCreate(
                    protocol=cfg.protocol,
                    path=(
                        prev.path
                        if prev is not None and prev.path
                        else (cfg.path or "")
                    ),
                    remote_port=cfg.remote_port,
                )
            else:
                create = TunnelCreate(
                    protocol=cfg.protocol,
                    subdomain=(
                        prev.subdomain if prev is not None else cfg.subdomain
                    ),
                    remote_port=cfg.remote_port,
                )
            await self.ws.send(serialize(create))
            reply = await self._recv(HANDSHAKE_TIMEOUT)
            if isinstance(reply, Error):
                raise self._refusal(reply)
            if not isinstance(reply, TunnelCreated):
                raise TunnelError(f"unexpected reply: {type(reply).__name__}")
            if cfg.hostname:
                self._assert_hostname_honoured(cfg.hostname, reply.url)
            self._tunnels[idx] = Tunnel(
                id=reply.subdomain,
                url=reply.url,
                protocol=cfg.protocol,
                config=cfg,
                tunnel_id=reply.subdomain,
                subdomain=None if reply.path else reply.subdomain,
                path=reply.path,
            )
            logger.info(
                "Tunnel ready: %s -> localhost:%d", reply.url, cfg.local_port
            )

    @staticmethod
    def _assert_hostname_honoured(requested: str, url: str) -> None:
        """Refuse a tunnel the server did not actually serve on our hostname.

        `TunnelCreate.hostname` is an OPTIONAL field, and the deserializer
        drops fields it does not know (that is what keeps v1 peers working).
        So a server older than issuedb #60 does not reject the request -- it
        silently ignores the hostname and allocates a pool subdomain instead.
        The user would see "Tunnel ready: https://calm-fox-12.retunnel.net"
        after asking for https://app.example.com, and their DNS would point at
        a name nothing was listening on.

        An accepted-and-ignored flag is exactly the failure audit #47 called
        out, so the client checks the answer rather than trusting it.
        """
        host = urlsplit(url).hostname or ""
        if host.lower() != requested.lower():
            raise TerminalError(
                "HOSTNAME_IGNORED",
                f"asked for https://{requested} but the server returned "
                f"{url} -- this server does not support custom hostnames "
                f"(needs the issuedb #60 server release)",
                69,
            )

    async def _teardown(self) -> None:
        tasks = [s.task for s in self._streams.values() if s.task is not None]
        self._streams.clear()
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        ws, self.ws = self.ws, None
        if ws is not None:
            try:
                # Bounded: ws.close() waits for the peer's close handshake
                # (10s by default in websockets), which made Ctrl-C take
                # more than 8 seconds against an unresponsive server.
                await asyncio.wait_for(ws.close(), timeout=CLOSE_TIMEOUT)
            except (TimeoutError, asyncio.TimeoutError):
                logger.debug("control socket close timed out; abandoning it")
            except Exception:
                logger.debug("closing control socket failed", exc_info=True)

    # ---------------------------------------------------------- message loop
    async def _send_raw(self, data: bytes) -> None:
        if not self._ws_open():
            raise ConnectionError("control connection is down")
        await self.ws.send(data)

    async def _message_loop(self) -> None:
        async for raw in self.ws:
            try:
                msg = deserialize(
                    raw if isinstance(raw, bytes) else raw.encode()
                )
            except Exception as e:
                # One bad frame must never take down every stream.
                logger.warning("Ignoring undecodable frame: %s", e)
                continue
            if isinstance(msg, StreamOpen):
                self._on_open(msg)
            elif isinstance(msg, (StreamData, StreamClose, StreamReset)):
                self._on_frame(msg)
            elif isinstance(msg, Heartbeat):
                await self._send_raw(serialize(HeartbeatAck()))
            elif isinstance(msg, Error):
                logger.error("Server error %s: %s", msg.code, msg.message)

    def _config_for(self, tunnel_id: str) -> TunnelConfig:
        for t in self._tunnels.values():
            if tunnel_id in (t.tunnel_id, t.subdomain, t.path):
                return t.config
        return self._configs[0]

    def _local_for(self, port: int) -> LocalProxy:
        local = self._locals.get(port)
        if local is None:
            local = self._locals[port] = LocalProxy(port)
        return local

    def _on_open(self, msg: StreamOpen) -> None:
        logger.debug(
            "StreamOpen stream_id=%d mode=%s path=%s",
            msg.stream_id,
            msg.mode,
            msg.path,
        )
        state = StreamState(msg.stream_id)
        self._streams[msg.stream_id] = state
        sender = Sender(
            self._send_raw, msg.stream_id, self.protocol_version >= 2
        )
        cfg = self._config_for(msg.tunnel_id)
        if msg.mode == "ws":
            coro = handle_ws_stream(
                msg, state, sender, self._local_for(cfg.local_port), cfg.auth
            )
        elif msg.mode == "tcp":
            coro = handle_tcp_stream(msg, state, sender, cfg.local_port)
        else:
            coro = handle_http_stream(
                msg, state, sender, self._local_for(cfg.local_port), cfg.auth
            )
        state.task = asyncio.ensure_future(self._guard(coro, state, sender))

    async def _guard(
        self, coro: Any, state: StreamState, sender: Sender
    ) -> None:
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("stream %d handler failed: %s", state.stream_id, e)
            try:
                await sender.reset(f"{type(e).__name__}: {e}")
            except Exception:
                logger.debug(
                    "stream %d: reset not delivered",
                    state.stream_id,
                    exc_info=True,
                )
        finally:
            self._streams.pop(state.stream_id, None)

    def _on_frame(self, msg: Any) -> None:
        state = self._streams.get(msg.stream_id)
        if state is None:
            logger.debug("frame for unknown stream %d", msg.stream_id)
            return
        try:
            state.queue.put_nowait(msg)
        except asyncio.QueueFull:
            # Local consumer slower than the server: drop this stream only.
            logger.warning(
                "stream %d: local consumer too slow; resetting", msg.stream_id
            )
            self._streams.pop(msg.stream_id, None)
            if state.task is not None:
                state.task.cancel()
            task = asyncio.ensure_future(
                self._send_raw(
                    serialize(
                        StreamReset(msg.stream_id, reason="buffer overflow")
                    )
                )
            )
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)

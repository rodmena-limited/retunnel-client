from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, cast

import msgpack
import websockets
from websockets.protocol import State

from retunnel.core.exceptions import (
    AuthenticationError,
    TunnelError,
)
from retunnel.local_proxy import open_http
from retunnel.msg.messages import (
    Auth,
    Error,
    Heartbeat,
    HeartbeatAck,
    StreamClose,
    StreamData,
    StreamOpen,
    StreamReset,
    TunnelCreate,
    TunnelCreated,
    deserialize,
    serialize,
)

logger = logging.getLogger(__name__)


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
        self._running = False
        self._reconnect_task: asyncio.Task[Any] | None = None
        self.ws_streams: dict[int, asyncio.Queue[Any]] = {}

    def _ws_open(self) -> bool:
        return self.ws is not None and self.ws.state == State.OPEN

    async def _recv_bytes(self) -> bytes:
        """Receive a binary frame from the control WebSocket."""
        data = await self.ws.recv()
        if isinstance(data, str):
            return data.encode("utf-8")
        return cast(bytes, data)

    @property
    def is_connected(self) -> bool:
        return self._ws_open()

    def get_requests(self) -> list[Any]:
        return []

    async def connect(self) -> None:
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
                token = result.get("auth_token")
                if token:
                    self.auth_token = token
                    await config_manager.set_auth_token(token)
                    logger.info(
                        "Successfully registered and saved auth token."
                    )
                else:
                    raise AuthenticationError(
                        "No auth token in registration response"
                    )
            except Exception as e:
                raise AuthenticationError(
                    f"Failed to register anonymous user: {e}"
                )

    async def request_tunnel(self, config: TunnelConfig) -> Tunnel:
        self._running = True
        await self.connect()

        retry_delay = 1.0
        while self._running:
            try:
                self.ws = await websockets.connect(self.server_addr)
                await self.ws.send(serialize(Auth(token=self.auth_token)))
                auth_resp = deserialize(await self._recv_bytes())
                if isinstance(auth_resp, Error):
                    raise AuthenticationError(
                        f"Auth failed: {auth_resp.message}"
                    )

                await self.ws.send(
                    serialize(
                        TunnelCreate(
                            protocol=config.protocol,
                            subdomain=config.subdomain,
                            path=(config.path or "") if config.spa else None,
                            remote_port=config.remote_port,
                        )
                    )
                )
                tunnel_resp = deserialize(await self._recv_bytes())
                if isinstance(tunnel_resp, Error):
                    raise TunnelError(
                        f"Tunnel creation failed: {tunnel_resp.message}"
                    )
                if not isinstance(tunnel_resp, TunnelCreated):
                    raise TypeError(f"Unexpected response: {tunnel_resp}")

                tunnel = Tunnel(
                    id=tunnel_resp.subdomain,
                    url=tunnel_resp.url,
                    protocol=config.protocol,
                    config=config,
                    tunnel_id=tunnel_resp.subdomain,
                    subdomain=tunnel_resp.subdomain,
                    path=tunnel_resp.path,
                )

                self._reconnect_task = asyncio.create_task(
                    self._reconnect_loop(config, tunnel)
                )
                return tunnel
            except Exception as e:
                logger.error(f"Connection error: {e}")
                if not self._running:
                    raise
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 60.0)
        raise TunnelError("Tunnel request aborted")

    async def _reconnect_loop(
        self, config: TunnelConfig, tunnel: Tunnel
    ) -> None:
        retry_delay = 1.0
        while self._running:
            try:
                if not self.is_connected:
                    self.ws = await websockets.connect(self.server_addr)
                    await self.ws.send(serialize(Auth(token=self.auth_token)))
                    await self._recv_bytes()
                    await self.ws.send(
                        serialize(
                            TunnelCreate(
                                protocol=config.protocol,
                                subdomain=tunnel.subdomain,
                                path=tunnel.path,
                                remote_port=config.remote_port,
                            )
                        )
                    )
                    resp = deserialize(await self._recv_bytes())
                    if isinstance(resp, Error):
                        logger.error(
                            f"Reconnect tunnel creation failed: {resp.message}"
                        )
                        raise TunnelError(
                            f"Tunnel creation failed: {resp.message}"
                        )
                    if isinstance(resp, TunnelCreated):
                        tunnel.url = resp.url
                        if resp.path:
                            tunnel.path = resp.path
                            tunnel.subdomain = resp.subdomain

                retry_delay = 1.0
                await self._message_loop(config)
            except Exception as e:
                logger.error(f"Connection error: {e}")

            if not self._running:
                break

            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60.0)

    async def _message_loop(self, config: TunnelConfig) -> None:
        if not self.ws:
            return
        async for msg_raw in self.ws:
            msg = deserialize(msg_raw)
            if isinstance(msg, StreamOpen):
                logger.info(
                    f"StreamOpen received: stream_id={msg.stream_id} "
                    f"mode={msg.mode} path={msg.path}"
                )
                self.ws_streams[msg.stream_id] = asyncio.Queue()
                if msg.mode == "ws":
                    asyncio.create_task(
                        self._handle_ws_stream(msg, config.local_port)
                    )
                elif msg.mode == "tcp":
                    asyncio.create_task(
                        self._handle_tcp_stream(msg, config.local_port)
                    )
                else:
                    asyncio.create_task(
                        self._handle_stream(msg, config.local_port)
                    )
            elif isinstance(msg, (StreamData, StreamClose, StreamReset)):
                queue = self.ws_streams.get(msg.stream_id)
                if queue:
                    queue.put_nowait(msg)
            elif isinstance(msg, Heartbeat):
                if self._ws_open():
                    await self.ws.send(serialize(HeartbeatAck()))
            elif isinstance(msg, Error):
                logger.error(f"Server error: {msg.message}")

    async def _handle_ws_stream(
        self, msg: StreamOpen, local_port: int
    ) -> None:
        from retunnel.local_proxy import open_ws

        try:
            local_ws = await open_ws(local_port, msg.path, msg.headers)
            logger.info(
                f"local WS connected: port={local_port} path={msg.path}"
            )
        except Exception as e:
            logger.error(f"local WS connect failed: {e}")
            if self._ws_open():
                await self.ws.send(
                    serialize(
                        StreamReset(stream_id=msg.stream_id, reason=str(e))
                    )
                )
            self.ws_streams.pop(msg.stream_id, None)
            return

        async def read_from_local() -> None:
            try:
                while True:
                    data, ws_type = await local_ws.recv()
                    if not self._ws_open():
                        break
                    await self.ws.send(
                        serialize(
                            StreamData(
                                stream_id=msg.stream_id,
                                data=data,
                                ws_type=ws_type,
                            )
                        )
                    )
            except websockets.exceptions.ConnectionClosed as e:
                if self._ws_open():
                    await self.ws.send(
                        serialize(
                            StreamClose(
                                stream_id=msg.stream_id,
                                code=e.code,
                                reason=e.reason,
                            )
                        )
                    )
            except Exception as e:
                logger.error(f"Local WS read error: {e}")
                if self._ws_open():
                    await self.ws.send(
                        serialize(
                            StreamClose(
                                stream_id=msg.stream_id,
                                code=1011,
                                reason=str(e),
                            )
                        )
                    )

        async def read_from_server() -> None:
            queue = self.ws_streams.get(msg.stream_id)
            if not queue:
                return
            try:
                while True:
                    server_msg = await queue.get()
                    if isinstance(server_msg, StreamData):
                        ws_type = server_msg.ws_type or "binary"
                        await local_ws.send(server_msg.data, ws_type)
                    elif isinstance(server_msg, (StreamClose, StreamReset)):
                        code = getattr(server_msg, "code", 1000) or 1000
                        reason = getattr(server_msg, "reason", "") or ""
                        await local_ws.close(code=code, reason=reason)
                        break
            except Exception as e:
                logger.error(f"Server WS read error: {e}")

        t1 = asyncio.create_task(read_from_local())
        t2 = asyncio.create_task(read_from_server())

        await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)

        if not t1.done():
            t1.cancel()
        if not t2.done():
            t2.cancel()

        try:
            await local_ws.close()
        except Exception:
            logger.debug("Local WS already closed")

        self.ws_streams.pop(msg.stream_id, None)

    async def _handle_tcp_stream(
        self, msg: StreamOpen, local_port: int
    ) -> None:
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", local_port
            )
            logger.info(
                f"TCP stream {msg.stream_id} -> 127.0.0.1:{local_port}"
            )
        except Exception as e:
            logger.error(f"TCP connect failed: {e}")
            if self._ws_open():
                await self.ws.send(
                    serialize(
                        StreamReset(stream_id=msg.stream_id, reason=str(e))
                    )
                )
            self.ws_streams.pop(msg.stream_id, None)
            return

        async def read_from_local() -> None:
            try:
                while True:
                    data = await reader.read(65536)
                    if not data:
                        break
                    if not self._ws_open():
                        break
                    await self.ws.send(
                        serialize(
                            StreamData(stream_id=msg.stream_id, data=data)
                        )
                    )
            except Exception as e:
                logger.debug(f"TCP local read error: {e}")
            finally:
                if self._ws_open():
                    await self.ws.send(
                        serialize(StreamClose(stream_id=msg.stream_id))
                    )

        async def read_from_server() -> None:
            queue = self.ws_streams.get(msg.stream_id)
            if not queue:
                return
            try:
                while True:
                    server_msg = await queue.get()
                    if isinstance(server_msg, StreamData):
                        writer.write(server_msg.data)
                        await writer.drain()
                    elif isinstance(server_msg, (StreamClose, StreamReset)):
                        break
            except Exception as e:
                logger.debug(f"TCP server read error: {e}")

        t1 = asyncio.create_task(read_from_local())
        t2 = asyncio.create_task(read_from_server())
        await asyncio.wait([t1, t2], return_when=asyncio.FIRST_COMPLETED)

        if not t1.done():
            t1.cancel()
        if not t2.done():
            t2.cancel()

        writer.close()
        self.ws_streams.pop(msg.stream_id, None)

    async def _handle_stream(self, msg: StreamOpen, local_port: int) -> None:
        if msg.mode != "http":
            return

        method = msg.headers.pop(
            ":method",
            msg.headers.pop("method", msg.headers.pop("Method", "GET")),
        )
        try:
            proxy_resp = await open_http(
                port=local_port,
                method=method,
                path=msg.path,
                headers=msg.headers,
                body=msg.body,
            )
        except Exception as e:
            if self._ws_open():
                await self.ws.send(
                    serialize(
                        StreamReset(stream_id=msg.stream_id, reason=str(e))
                    )
                )
            self.ws_streams.pop(msg.stream_id, None)
            return

        closed = asyncio.Event()

        async def watch_server_close() -> None:
            queue = self.ws_streams.get(msg.stream_id)
            if not queue:
                return
            while True:
                server_msg = await queue.get()
                if isinstance(server_msg, (StreamClose, StreamReset)):
                    closed.set()
                    break

        watcher = asyncio.create_task(watch_server_close())

        try:
            if not self._ws_open():
                return

            meta = {
                "status": proxy_resp.status_code,
                "headers": proxy_resp.response_headers,
            }
            meta_bytes = msgpack.packb(meta, use_bin_type=True)
            await self.ws.send(
                serialize(StreamData(stream_id=msg.stream_id, data=meta_bytes))
            )

            async for chunk in proxy_resp.iter_chunks():
                if closed.is_set() or not self._ws_open():
                    break
                await self.ws.send(
                    serialize(StreamData(stream_id=msg.stream_id, data=chunk))
                )

            if self._ws_open() and not closed.is_set():
                await self.ws.send(
                    serialize(StreamClose(stream_id=msg.stream_id))
                )
        except Exception as e:
            logger.error(f"Stream handler error: {e}")
            if self._ws_open():
                await self.ws.send(
                    serialize(
                        StreamReset(stream_id=msg.stream_id, reason=str(e))
                    )
                )
        finally:
            watcher.cancel()
            self.ws_streams.pop(msg.stream_id, None)
            await proxy_resp.close()

    async def close(self) -> None:
        self._running = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
        if self.ws:
            await self.ws.close()

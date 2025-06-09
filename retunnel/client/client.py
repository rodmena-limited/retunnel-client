"""High-performance ReTunnel client implementation."""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import sys
from typing import Any, Dict, Optional, Set

from pydantic import BaseModel

from ..core.api import APIClient
from ..core.config import AuthConfig
from ..core.connection import WebSocketConnection
from ..core.exceptions import (
    AuthenticationError,
    ConnectionError,
    TunnelError,
)
from ..core.protocol import (
    Auth,
    AuthResp,
    NewTunnel,
    Ping,
    Pong,
    RegProxy,
    ReqProxy,
    ReqTunnel,
    StartProxy,
)
from ..utils.id import generate_id

logger = logging.getLogger(__name__)


class TunnelConfig(BaseModel):
    """Configuration for a tunnel."""

    protocol: str = "http"
    local_port: int
    subdomain: Optional[str] = None
    hostname: Optional[str] = None
    auth: Optional[str] = None
    inspect: bool = True


class Tunnel(BaseModel):
    """Active tunnel information."""

    id: str
    protocol: str
    url: str
    local_port: int
    config: TunnelConfig


class ReTunnelClient:
    """High-performance ReTunnel client."""

    VERSION = "2.0.0"

    def __init__(
        self,
        server_addr: Optional[str] = None,
        auth_token: Optional[str] = None,
        auto_register: bool = True,
    ):
        # Use server address from environment or default to localhost:6400
        if server_addr is None:
            server_addr = os.environ.get(
                "RETUNNEL_SERVER_ENDPOINT", "localhost:6400"
            )
        self.server_addr = self._normalize_server_addr(server_addr)
        self.auth_token = auth_token
        self.auto_register = auto_register

        self.client_id = generate_id("cli")
        self.api_client = APIClient(self._get_api_url())
        self.auth_config = AuthConfig()

        self._control_conn: Optional[WebSocketConnection] = None
        self._proxy_conns: Dict[str, WebSocketConnection] = {}
        self._tunnels: Dict[str, Tunnel] = {}
        self._running = False
        self._tasks: Set[asyncio.Task] = set()

        # Load auth token from config if not provided
        if not self.auth_token:
            self.auth_token = self.auth_config.auth_token

    def _normalize_server_addr(self, addr: str) -> str:
        """Normalize server address to WebSocket URL."""
        if not addr.startswith(("ws://", "wss://")):
            # Assume wss:// for production
            if "localhost" in addr or "127.0.0.1" in addr:
                addr = f"ws://{addr}"
            else:
                addr = f"wss://{addr}"

        # Ensure /api/v1/ws/tunnel path for WebSocket endpoint
        if not addr.endswith("/tunnel"):
            if "/api/v1/ws" not in addr:
                addr = addr.rstrip("/") + "/api/v1/ws/tunnel"
            else:
                addr = addr.rstrip("/") + "/tunnel"

        return addr

    def _get_api_url(self) -> str:
        """Get REST API URL from WebSocket URL."""
        api_url = self.server_addr.replace("/api/v1/ws/tunnel", "")
        api_url = api_url.replace("ws://", "http://")
        api_url = api_url.replace("wss://", "https://")
        return api_url

    async def connect(self) -> None:
        """Connect to ReTunnel server."""
        # Auto-register if needed
        if not self.auth_token and self.auto_register:
            await self._auto_register()

        # Create control connection
        self._control_conn = WebSocketConnection(
            self.server_addr, self.auth_token
        )
        await self._control_conn.connect()

        # Authenticate
        await self._authenticate()

        # Start background tasks
        self._running = True
        self._start_background_tasks()

        logger.info(f"Connected to {self.server_addr}")

    async def _auto_register(self) -> None:
        """Automatically register anonymous user."""
        logger.info("No auth token found, registering anonymous user...")

        try:
            user_info = await self.api_client.register_anonymous()
            self.auth_token = user_info.auth_token
            self.auth_config.auth_token = self.auth_token

            logger.info(f"Registered as {user_info.username}")
        except Exception as e:
            raise AuthenticationError(f"Auto-registration failed: {e}")

    async def _authenticate(self) -> None:
        """Authenticate with server."""
        if not self._control_conn:
            raise ConnectionError("Not connected")

        # Send auth message
        auth_msg = Auth(
            token=self.auth_token or "",
            client_id=self.client_id,
            version=self.VERSION,
            os=platform.system(),
            arch=platform.machine(),
        )

        await self._control_conn.send(auth_msg)

        # Wait for response
        resp = await self._control_conn.receive(timeout=10)
        if not isinstance(resp, AuthResp):
            raise AuthenticationError("Invalid auth response")

        if resp.error:
            raise AuthenticationError(resp.error)

        self.client_id = resp.client_id
        logger.info(f"Authenticated with client ID: {self.client_id}")

    def _start_background_tasks(self) -> None:
        """Start background tasks."""
        # Control message handler
        task = asyncio.create_task(self._handle_control_messages())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

        # Heartbeat task
        task = asyncio.create_task(self._heartbeat_loop())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_control_messages(self) -> None:
        """Handle incoming control messages."""
        while self._running and self._control_conn:
            try:
                msg = await self._control_conn.receive(timeout=1)
                if not msg:
                    continue

                if isinstance(msg, ReqProxy):
                    # Server requesting proxy connection
                    asyncio.create_task(
                        self._handle_proxy_request(msg.tunnel_id)
                    )
                elif isinstance(msg, Pong):
                    # Heartbeat response
                    logger.debug("Received pong")
                else:
                    logger.debug(f"Unhandled message: {msg}")

            except Exception as e:
                if self._running:
                    logger.error(f"Control message error: {e}")

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._running and self._control_conn:
            try:
                await self._control_conn.send(Ping())
                await asyncio.sleep(30)
            except Exception as e:
                if self._running:
                    logger.error(f"Heartbeat error: {e}")
                    break

    async def request_tunnel(self, config: TunnelConfig) -> Tunnel:
        """Request a new tunnel."""
        if not self._control_conn:
            raise ConnectionError("Not connected")

        # Send tunnel request
        req_id = generate_id("req", 8)
        req = ReqTunnel(
            req_id=req_id,
            protocol=config.protocol,
            subdomain=config.subdomain or "",
            hostname=config.hostname or "",
            auth=config.auth or "",
        )

        await self._control_conn.send(req)

        # Wait for response
        resp = await self._control_conn.receive(timeout=10)
        if not isinstance(resp, NewTunnel):
            raise TunnelError("Invalid tunnel response")

        if resp.error:
            raise TunnelError(resp.error)

        # Create tunnel object
        tunnel = Tunnel(
            id=resp.tunnel_id,
            protocol=resp.protocol,
            url=resp.url,
            local_port=config.local_port,
            config=config,
        )

        self._tunnels[tunnel.id] = tunnel
        logger.info(f"Tunnel created: {tunnel.url}")

        return tunnel

    async def _handle_proxy_request(self, tunnel_id: str) -> None:
        """Handle proxy connection request from server."""
        tunnel = self._tunnels.get(tunnel_id)
        if not tunnel:
            logger.error(f"Unknown tunnel ID: {tunnel_id}")
            return

        try:
            # Create proxy connection (use /api/v1/ws/proxy endpoint)
            proxy_url = self.server_addr.replace("/tunnel", "/proxy")
            proxy_conn = WebSocketConnection(proxy_url, self.auth_token)
            await proxy_conn.connect()

            # Register proxy
            await proxy_conn.send(
                RegProxy(
                    client_id=self.client_id,
                    tunnel_id=tunnel_id,
                )
            )

            # Wait for StartProxy
            msg = await proxy_conn.receive(timeout=5)
            if not isinstance(msg, StartProxy):
                await proxy_conn.close()
                return

            # Start proxying
            conn_id = msg.conn_id
            self._proxy_conns[conn_id] = proxy_conn

            task = asyncio.create_task(
                self._proxy_connection(tunnel, conn_id, proxy_conn)
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        except Exception as e:
            logger.error(f"Proxy setup error: {e}")

    async def _proxy_connection(
        self,
        tunnel: Tunnel,
        conn_id: str,
        proxy_conn: WebSocketConnection,
    ) -> None:
        """Proxy data between WebSocket and local server."""
        local_reader = None
        local_writer = None

        try:
            # Connect to local server
            local_reader, local_writer = await asyncio.open_connection(
                "localhost", tunnel.local_port
            )

            # Start bidirectional proxy
            await asyncio.gather(
                self._proxy_ws_to_local(proxy_conn, local_writer),
                self._proxy_local_to_ws(local_reader, proxy_conn),
            )

        except Exception as e:
            logger.error(f"Proxy error for {conn_id}: {e}")
        finally:
            # Cleanup
            if local_writer:
                local_writer.close()
                await local_writer.wait_closed()

            await proxy_conn.close()
            self._proxy_conns.pop(conn_id, None)

    async def _proxy_ws_to_local(
        self,
        ws: WebSocketConnection,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Proxy data from WebSocket to local server."""
        while ws.is_connected:
            try:
                # WebSocket sends raw bytes for proxy data
                if ws._ws:
                    data = await ws._ws.recv()
                    if isinstance(data, str):
                        data = data.encode()

                    writer.write(data)
                    await writer.drain()
            except Exception:
                break

    async def _proxy_local_to_ws(
        self,
        reader: asyncio.StreamReader,
        ws: WebSocketConnection,
    ) -> None:
        """Proxy data from local server to WebSocket."""
        while ws.is_connected:
            try:
                data = await reader.read(65536)
                if not data:
                    break

                if ws._ws:
                    await ws._ws.send(data)
            except Exception:
                break

    async def close(self) -> None:
        """Close all connections and cleanup."""
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close proxy connections
        for conn in self._proxy_conns.values():
            await conn.close()
        self._proxy_conns.clear()

        # Close control connection
        if self._control_conn:
            await self._control_conn.close()
            self._control_conn = None

        # Close API client
        await self.api_client.close()

        logger.info("Client closed")

    async def __aenter__(self) -> ReTunnelClient:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit."""
        await self.close()

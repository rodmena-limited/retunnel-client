"""
High-performance client model that works with the updated server protocol
"""

import asyncio
import logging
import platform
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set

import aiohttp
import msgpack

from ..utils.id import generate_client_id, generate_request_id
from .api_client import APIError, ReTunnelAPIClient
from .config_manager import config_manager

logger = logging.getLogger(__name__)


@dataclass
class TunnelConfig:
    """Configuration for a tunnel"""

    protocol: str  # http, tcp
    local_port: int
    name: Optional[str] = None
    auth: Optional[str] = None
    remote_port: Optional[int] = None
    subdomain: Optional[str] = None
    hostname: Optional[str] = None
    inspect: bool = True

    def __post_init__(self) -> None:
        if self.protocol not in ["http", "tcp"]:
            raise ValueError(f"Invalid protocol: {self.protocol}")


@dataclass
class Tunnel:
    """Active tunnel information"""

    id: str
    url: str
    protocol: str
    config: TunnelConfig
    tunnel_id: str = ""
    created_at: float = field(default_factory=time.time)

    @property
    def public_url(self) -> str:
        """Get the public URL for this tunnel"""
        return self.url


class HighPerformanceClient:
    """
    High-performance client that matches the server's protocol
    """

    def __init__(
        self,
        server_addr: Optional[str] = None,
        auth_token: Optional[str] = None,
    ) -> None:
        self.server_addr = server_addr
        self.auth_token = auth_token
        self.client_id = generate_client_id()

        # WebSocket connections
        self.control_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self.proxy_connections: Dict[str, aiohttp.ClientWebSocketResponse] = {}
        self.proxy_tasks: Set[asyncio.Task[Any]] = set()
        self.session: Optional[aiohttp.ClientSession] = None

        # State
        self.tunnels: Dict[str, Tunnel] = {}
        self.pending_requests: Dict[str, asyncio.Future[Any]] = {}

        # Configuration
        self.version = "2.3.40"
        self.mm_version = "2.3"

        # Tasks
        self._heartbeat_task: Optional[asyncio.Task[Any]] = None
        self._control_loop_task: Optional[asyncio.Task[Any]] = None
        self._proxy_pool_task: Optional[asyncio.Task[Any]] = None

        self.logger = logging.getLogger(f"client.{self.client_id}")

    async def _ensure_auth_token(self) -> None:
        """Ensure we have a valid auth token"""
        # If no auth token provided, check config file
        if not self.auth_token:
            self.auth_token = await config_manager.get_auth_token()

        # If still no token, register new user
        if not self.auth_token:
            self.logger.info("No auth token found, registering new user")
            api_url = await config_manager.get_api_url()

            # Handle local development
            if self.server_addr and "localhost" in self.server_addr:
                api_url = f"http://{self.server_addr}"

            async with ReTunnelAPIClient(api_url) as api:
                try:
                    result = await api.register_user()
                    self.auth_token = result.get("auth_token")
                    if self.auth_token:
                        await config_manager.set_auth_token(self.auth_token)
                        self.logger.info(
                            "Successfully registered and saved auth token"
                        )
                    else:
                        raise ValueError(
                            "No auth token in registration response"
                        )
                except Exception as e:
                    self.logger.error(f"Failed to register user: {e}")
                    raise

        # Verify token is still valid and refresh if needed
        if self.auth_token:
            api_url = await config_manager.get_api_url()

            # Handle local development
            if self.server_addr and "localhost" in self.server_addr:
                api_url = f"http://{self.server_addr}"

            async with ReTunnelAPIClient(api_url) as api:
                try:
                    # Check if token is valid
                    if not await api.verify_token(self.auth_token):
                        self.logger.info(
                            "Auth token is invalid, refreshing..."
                        )
                        try:
                            # Try to refresh the token
                            result = await api.refresh_token(self.auth_token)
                            new_token = result.get("auth_token")
                            if new_token:
                                self.auth_token = new_token
                                await config_manager.set_auth_token(new_token)
                                self.logger.info(
                                    "Successfully refreshed auth token"
                                )
                            else:
                                raise ValueError(
                                    "No auth token in refresh response"
                                )
                        except APIError as e:
                            if e.status == 401:
                                # Token is completely invalid, need to register new user
                                self.logger.info(
                                    "Token refresh failed, registering new user"
                                )
                                result = await api.register_user()
                                self.auth_token = result.get("auth_token")
                                if self.auth_token:
                                    await config_manager.set_auth_token(
                                        self.auth_token
                                    )
                                    self.logger.info(
                                        "Successfully registered new user"
                                    )
                                else:
                                    raise ValueError(
                                        "No auth token in registration response"
                                    )
                            else:
                                raise
                except Exception as e:
                    self.logger.warning(f"Token verification failed: {e}")
                    # Continue with existing token, will fail later if truly invalid

    async def connect(self) -> None:
        """Establish control connection to server"""
        # Ensure we have auth token
        await self._ensure_auth_token()

        # Use server from config if not provided
        if not self.server_addr:
            server_url = await config_manager.get_server_url()
            # Extract host:port from URL
            from urllib.parse import urlparse

            parsed = urlparse(server_url)
            self.server_addr = parsed.netloc or "retunnel.net"

        self.logger.info(f"Connecting to {self.server_addr}")

        # Create session
        self.session = aiohttp.ClientSession()

        # Build WebSocket URL
        if self.server_addr.startswith(("ws://", "wss://")):
            ws_url = f"{self.server_addr}/api/v1/ws/tunnel"
        else:
            # Convert host:port to WebSocket URL
            ws_url = f"ws://{self.server_addr}/api/v1/ws/tunnel"

        # Connect to control WebSocket
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        self.control_ws = await self.session.ws_connect(
            ws_url, headers=headers, heartbeat=30
        )

        # Send authentication using client's flat format with length prefix
        auth_msg = {
            "Type": "Auth",
            "ClientId": self.client_id,
            "OS": platform.system().lower(),
            "Arch": platform.machine().lower(),
            "Version": self.version,
            "MmVersion": self.mm_version,
            "User": self.auth_token or "",
            "Password": "",
        }

        await self._send_message(self.control_ws, auth_msg)

        # Wait for auth response
        resp = await self._receive_message(self.control_ws)

        if resp.get("Error"):
            raise Exception(f"Authentication failed: {resp['Error']}")

        # Update client ID if server assigned one
        if resp.get("ClientId"):
            self.client_id = resp["ClientId"]

        self.logger.info(f"Connected as client {self.client_id}")

        # Start background tasks
        self._start_background_tasks()

    async def request_tunnel(self, config: TunnelConfig) -> Tunnel:
        """Request a new tunnel from the server"""
        req_id = generate_request_id()

        # Create request in client format
        req = {
            "Type": "ReqTunnel",
            "ReqId": req_id,
            "Protocol": config.protocol,
            "Hostname": "",
            "Subdomain": "",
            "HttpAuth": config.auth or "",
            "RemotePort": config.remote_port or 0,
        }

        # Create future for response
        future: asyncio.Future[Dict[str, Any]] = asyncio.Future()
        self.pending_requests[req_id] = future

        # Send request
        if self.control_ws:
            await self._send_message(self.control_ws, req)

        try:
            # Wait for response (with timeout)
            resp = await asyncio.wait_for(future, timeout=10.0)

            if resp.get("Error"):
                raise Exception(f"Tunnel creation failed: {resp['Error']}")

            # Create tunnel object
            tunnel = Tunnel(
                id=req_id,
                url=resp.get("Url", ""),
                protocol=resp.get("Protocol", ""),
                config=config,
                tunnel_id=resp.get("TunnelId", ""),
            )

            self.tunnels[tunnel.id] = tunnel
            self.logger.info(f"Tunnel established: {tunnel.url}")

            return tunnel

        finally:
            self.pending_requests.pop(req_id, None)

    async def _send_message(
        self, ws: aiohttp.ClientWebSocketResponse, msg: Dict[str, Any]
    ) -> None:
        """Send a message with length prefix"""
        # Pack the message
        data = msgpack.packb(msg, use_bin_type=True)

        # Add length prefix
        length = struct.pack(">Q", len(data))

        # Send as binary
        await ws.send_bytes(length + data)

    async def _receive_message(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> Dict[str, Any]:
        """Receive a message with length prefix"""
        msg = await ws.receive()

        if msg.type == aiohttp.WSMsgType.BINARY:
            data = msg.data

            # Check if it has length prefix
            if len(data) >= 8:
                try:
                    # Try to read length prefix
                    length = struct.unpack(">Q", data[:8])[0]
                    if length == len(data) - 8:
                        # It's length-prefixed, extract actual data
                        data = data[8:]
                except:
                    # Not length-prefixed
                    pass

            # Unpack the message
            return msgpack.unpackb(data, raw=False)  # type: ignore[no-any-return]

        elif msg.type == aiohttp.WSMsgType.ERROR:
            raise Exception(f"WebSocket error: {ws.exception()}")

        elif msg.type == aiohttp.WSMsgType.CLOSE:
            raise Exception("WebSocket closed")

        else:
            raise Exception(f"Unexpected message type: {msg.type}")

    async def _handle_message(self, msg: Dict[str, Any]) -> None:
        """Handle incoming control messages"""
        msg_type = msg.get("Type")

        if msg_type == "NewTunnel":
            # Response to tunnel request
            req_id = msg.get("ReqId")
            future = self.pending_requests.get(req_id) if req_id else None
            if future and not future.done():
                future.set_result(msg)

        elif msg_type == "ReqProxy":
            # Server requesting a new proxy connection
            asyncio.create_task(self._handle_req_proxy())

        elif msg_type == "Ping":
            # Respond to ping
            if self.control_ws:
                await self._send_message(self.control_ws, {"Type": "Pong"})

        elif msg_type == "Pong":
            # Server's response to our ping - just log it
            self.logger.debug("Received pong from server")

        else:
            self.logger.warning(f"Unhandled message type: {msg_type}")

    async def _handle_req_proxy(self) -> None:
        """Handle server's request for a new proxy connection"""
        try:
            # Create new proxy WebSocket connection
            ws_url = f"ws://{self.server_addr}/api/v1/ws/proxy"
            if self.session:
                proxy_ws = await self.session.ws_connect(ws_url)
            else:
                raise RuntimeError("Session not initialized")

            # Register the proxy connection
            reg_msg = {"Type": "RegProxy", "ClientId": self.client_id}
            await self._send_message(proxy_ws, reg_msg)

            # Handle proxy messages
            task = asyncio.create_task(self._handle_proxy_connection(proxy_ws))
            self.proxy_tasks.add(task)
            task.add_done_callback(self.proxy_tasks.discard)

        except Exception as e:
            self.logger.error(f"Error creating proxy connection: {e}")

    async def _handle_proxy_connection(
        self, proxy_ws: aiohttp.ClientWebSocketResponse
    ) -> None:
        """Handle a proxy connection"""
        local_reader = None
        local_writer = None
        conn_id = generate_request_id()
        self.proxy_connections[conn_id] = proxy_ws

        try:
            while not proxy_ws.closed:
                msg = await self._receive_message(proxy_ws)
                msg_type = msg.get("Type")

                if msg_type == "StartProxy":
                    # Extract URL to determine which tunnel
                    url = msg.get("Url", "")

                    # Find matching tunnel
                    tunnel = None
                    for t in self.tunnels.values():
                        if t.tunnel_id and t.tunnel_id in url:
                            tunnel = t
                            break

                    if not tunnel:
                        self.logger.error(f"No tunnel found for URL: {url}")
                        break

                    # Connect to local service
                    local_reader, local_writer = await asyncio.open_connection(
                        "127.0.0.1", tunnel.config.local_port
                    )

                elif msg_type == "Proxy":
                    # Proxy data
                    data = msg.get("data", b"")
                    if data and local_writer:
                        # Unpack HTTP request
                        try:
                            http_req = msgpack.unpackb(data, raw=False)

                            # Build HTTP request
                            method = http_req.get("method", "GET")
                            path = http_req.get("path", "/")
                            query = http_req.get("query", "")
                            headers = http_req.get("headers", {})
                            body = http_req.get("body", b"")

                            # Build request line
                            if query:
                                request_line = (
                                    f"{method} {path}?{query} HTTP/1.1\r\n"
                                )
                            else:
                                request_line = f"{method} {path} HTTP/1.1\r\n"

                            # Build headers
                            header_lines = []
                            for key, value in headers.items():
                                header_lines.append(f"{key}: {value}")

                            # Combine request
                            full_request = (
                                request_line
                                + "\r\n".join(header_lines)
                                + "\r\n\r\n"
                            )

                            # Send to local service
                            local_writer.write(full_request.encode())
                            if body:
                                local_writer.write(body)
                            await local_writer.drain()

                            # Read response
                            response_data = b""
                            status_code = 500  # Default status code
                            response_headers = {}
                            response_body = b""

                            while True:
                                chunk = (
                                    await local_reader.read(8192)
                                    if local_reader
                                    else b""
                                )
                                if not chunk:
                                    break
                                response_data += chunk

                                # Check if we have full response
                                if b"\r\n\r\n" in response_data:
                                    # Parse headers
                                    header_end = response_data.index(
                                        b"\r\n\r\n"
                                    )
                                    headers_raw = response_data[
                                        :header_end
                                    ].decode("latin-1")
                                    body_start = header_end + 4

                                    # Parse status line
                                    lines = headers_raw.split("\r\n")
                                    status_line = lines[0]
                                    status_parts = status_line.split(" ", 2)
                                    status_code = int(status_parts[1])

                                    # Parse headers
                                    response_headers = {}
                                    for line in lines[1:]:
                                        if ": " in line:
                                            key, value = line.split(": ", 1)
                                            response_headers[key] = value

                                    # Get body
                                    response_body = response_data[body_start:]

                                    # Check content length
                                    content_length = response_headers.get(
                                        "Content-Length"
                                    )
                                    if content_length:
                                        expected_length = int(content_length)
                                        while (
                                            len(response_body)
                                            < expected_length
                                        ):
                                            chunk = (
                                                await local_reader.read(8192)
                                                if local_reader
                                                else b""
                                            )
                                            if not chunk:
                                                break
                                            response_body += chunk

                                    break

                            # Send response back
                            response_meta = {
                                "status": status_code,
                                "headers": response_headers,
                                "body": response_body,
                            }

                            response_msg = {
                                "Type": "Proxy",
                                "data": msgpack.packb(response_meta),
                            }

                            await self._send_message(proxy_ws, response_msg)

                        except Exception as e:
                            self.logger.error(
                                f"Error handling proxy data: {e}"
                            )

        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as e:
            if not proxy_ws.closed:
                self.logger.error(f"Proxy connection error: {e}")
        finally:
            # Clean up
            if local_writer:
                local_writer.close()
                try:
                    await local_writer.wait_closed()
                except Exception:
                    pass

            if not proxy_ws.closed:
                await proxy_ws.close()

            # Remove from tracked connections
            self.proxy_connections.pop(conn_id, None)

    def _start_background_tasks(self) -> None:
        """Start background tasks"""
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        self._control_loop_task = asyncio.create_task(self._control_loop())
        self._proxy_pool_task = asyncio.create_task(
            self._maintain_proxy_pool()
        )

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat pings"""
        try:
            while self.control_ws and not self.control_ws.closed:
                await asyncio.sleep(20)
                if self.control_ws and not self.control_ws.closed:
                    await self._send_message(self.control_ws, {"Type": "Ping"})
                    self.logger.debug("Sent heartbeat ping")
        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as e:
            self.logger.error(f"Heartbeat error: {e}")

    async def _control_loop(self) -> None:
        """Listen for control messages"""
        try:
            while self.control_ws and not self.control_ws.closed:
                msg = await self._receive_message(self.control_ws)
                await self._handle_message(msg)
        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as e:
            if self.control_ws and not self.control_ws.closed:
                self.logger.error(f"Control loop error: {e}")

    async def _maintain_proxy_pool(self) -> None:
        """Maintain a pool of proxy connections"""
        # For now, we create connections on demand
        # This could be optimized to pre-create connections
        pass

    async def close(self) -> None:
        """Close all connections and clean up"""
        self.logger.info("Closing client")

        # Cancel background tasks
        tasks_to_cancel = []
        for task in [
            self._heartbeat_task,
            self._control_loop_task,
            self._proxy_pool_task,
        ]:
            if task and not task.done():
                task.cancel()
                tasks_to_cancel.append(task)

        # Cancel proxy tasks
        for task in list(self.proxy_tasks):
            if not task.done():
                task.cancel()
                tasks_to_cancel.append(task)

        # Wait for all tasks to complete cancellation
        if tasks_to_cancel:
            await asyncio.gather(*tasks_to_cancel, return_exceptions=True)

        # Close WebSocket connections
        if self.control_ws and not self.control_ws.closed:
            await self.control_ws.close()

        for ws in list(self.proxy_connections.values()):
            if not ws.closed:
                await ws.close()

        # Close session
        if self.session and not self.session.closed:
            await self.session.close()
            # Small delay to ensure connections are properly closed
            await asyncio.sleep(0.25)

        # Clear tunnels
        self.tunnels.clear()
        self.proxy_connections.clear()
        self.proxy_tasks.clear()

        self.logger.info("Client closed")

    async def __aenter__(self) -> "HighPerformanceClient":
        """Async context manager entry"""
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit"""
        await self.close()

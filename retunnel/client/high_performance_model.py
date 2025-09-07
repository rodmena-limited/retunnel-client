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
from urllib.parse import urlparse, urlunparse

import aiohttp
import msgpack  # type: ignore[import-untyped]

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
    subdomain: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    bytes_in: int = 0
    bytes_out: int = 0

    @property
    def public_url(self) -> str:
        """Get the public URL for this tunnel"""
        return self.url

    def get_stats(self) -> Dict[str, Any]:
        """Get tunnel statistics"""
        return {
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "uptime": time.time() - self.created_at,
        }


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
        self.is_connected = False
        self.connection_status = "Disconnected"
        self._reconnect_delay = 1.0  # Start with 1 second
        self._max_reconnect_delay = 16.0
        self._reconnecting = False
        self._running = True

        # Configuration
        self.version = "2.3.40"
        self.mm_version = "2.3"

        # Tasks
        self._heartbeat_task: Optional[asyncio.Task[Any]] = None
        self._control_loop_task: Optional[asyncio.Task[Any]] = None
        self._proxy_pool_task: Optional[asyncio.Task[Any]] = None
        self._reconnect_task: Optional[asyncio.Task[Any]] = None

        self.logger = logging.getLogger(f"client.{self.client_id}")

    async def _ensure_auth_token(self) -> None:
        """Ensure we have a valid auth token"""
        # If no auth token provided, check config file
        if not self.auth_token:
            self.auth_token = await config_manager.get_auth_token()
            if self.auth_token:
                self.logger.info(
                    f"Loaded auth token from config: ****{self.auth_token[-4:]}"
                )

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

        # Skip token verification for now - just use the token from config
        # This was causing issues with multiple registrations
        if self.auth_token:
            self.logger.info(
                f"Using auth token from config: ****{self.auth_token[-4:]}"
            )
            return

        # OLD CODE - disabled for now
        # Verify token is still valid and refresh if needed
        if False and self.auth_token:
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
            self.server_addr = server_url

        self.logger.info(f"Connecting to {self.server_addr}")

        # Create session with proper timeout and SSL settings
        timeout = aiohttp.ClientTimeout(total=60)
        # Disable SSL verification for development/self-signed certificates
        ssl_context = False  # This disables SSL verification
        connector = aiohttp.TCPConnector(
            limit=100, limit_per_host=10, ssl=ssl_context
        )
        self.session = aiohttp.ClientSession(
            timeout=timeout, connector=connector
        )

        # Build WebSocket URL
        if self.server_addr.startswith(("ws://", "wss://")):
            # If already a WebSocket URL, ensure it has the right path
            if "/api/v1/ws/tunnel" not in self.server_addr:
                ws_url = f"{self.server_addr}/api/v1/ws/tunnel"
            else:
                ws_url = self.server_addr
        else:
            # Convert host:port to WebSocket URL
            # Default to wss:// for production domains
            if (
                "localhost" in self.server_addr
                or "127.0.0.1" in self.server_addr
            ):
                ws_url = f"ws://{self.server_addr}/api/v1/ws/tunnel"
            else:
                ws_url = f"wss://{self.server_addr}/api/v1/ws/tunnel"

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
            "User": self.auth_token if self.auth_token else "",
            "Password": "",
        }

        await self._send_message(self.control_ws, auth_msg)

        # Wait for auth response
        resp = await self._receive_message(self.control_ws)

        if resp.get("Error"):
            # Handle invalid auth token by reactivating it
            if "Invalid auth token" in resp.get("Error", ""):
                self.logger.info(
                    "Auth token invalid, attempting to reactivate..."
                )

                # Close the failed connection
                await self.control_ws.close()

                # Store the old token before clearing
                old_token = self.auth_token

                # Try to reactivate the token
                api_url = await config_manager.get_api_url()
                if self.server_addr and "localhost" in self.server_addr:
                    api_url = f"http://{self.server_addr}"

                async with ReTunnelAPIClient(api_url) as api:
                    try:
                        # First try to reactivate the existing token
                        if old_token:
                            result = await api.reactivate_token(old_token)
                        else:
                            result = await api.register_user()
                        self.auth_token = result.get("auth_token")
                        if self.auth_token:
                            await config_manager.set_auth_token(
                                self.auth_token
                            )
                            self.logger.info(
                                f"Successfully reactivated token for user {result.get('email')}"
                            )
                        else:
                            raise ValueError(
                                "No auth token in reactivation response"
                            )
                    except APIError as e:
                        # If reactivation fails (token not found), register new user
                        if e.status == 404:
                            self.logger.info(
                                "Token not found in system, registering new anonymous user..."
                            )
                            result = await api.register_user()
                            self.auth_token = result.get("auth_token")
                            if self.auth_token:
                                await config_manager.set_auth_token(
                                    self.auth_token
                                )
                                self.logger.info(
                                    "Successfully registered new user and saved auth token"
                                )
                            else:
                                raise ValueError(
                                    "No auth token in registration response"
                                )
                        else:
                            raise Exception(f"Token reactivation failed: {e}")
                    except Exception as e:
                        self.logger.error(f"Failed to reactivate token: {e}")
                        raise Exception(
                            f"Authentication failed and could not reactivate token: {e}"
                        )

                # Reconnect with new token
                headers = {"Authorization": f"Bearer {self.auth_token}"}
                self.control_ws = await self.session.ws_connect(
                    ws_url, headers=headers, heartbeat=30
                )

                # Retry authentication with new token
                auth_msg["User"] = self.auth_token
                await self._send_message(self.control_ws, auth_msg)
                resp = await self._receive_message(self.control_ws)

                if resp.get("Error"):
                    raise Exception(
                        f"Authentication failed after token reactivation: {resp['Error']}"
                    )
            else:
                raise Exception(f"Authentication failed: {resp['Error']}")

        # Update client ID if server assigned one
        if resp.get("ClientId"):
            self.client_id = resp["ClientId"]

        self.logger.info(
            f"Connected as client {self.client_id} with token ****{self.auth_token[-4:] if self.auth_token else 'None'}"
        )

        # Update connection state
        self.is_connected = True
        self.connection_status = "Connected"
        self._reconnect_delay = (
            1.0  # Reset reconnect delay on successful connection
        )

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
            "Hostname": config.hostname or "",
            "Subdomain": config.subdomain or "",
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

            # Check for error response
            if resp.get("Type") == "ErrorResp":
                # The error fields are at the root level, not in Payload
                error_code = resp.get("error_code", "UNKNOWN")
                message = resp.get("message", "Unknown error")

                # Debug log
                self.logger.debug(f"ErrorResp received: {resp}")

                if error_code == "OVER_CAPACITY":
                    raise Exception(
                        "No subdomains available. Please try again later."
                    )
                elif error_code == "FREE_TIER_LIMIT_REACHED":
                    raise Exception(
                        "Free tier limit reached. You can have a maximum of 2 active tunnels."
                    )
                else:
                    raise Exception(f"{error_code}: {message}")

            if resp.get("Error"):
                raise Exception(f"Tunnel creation failed: {resp['Error']}")

            # Create tunnel object
            url = resp.get("Url", "")
            subdomain = resp.get("Subdomain", "")
            tunnel_id = resp.get("TunnelId", "") or subdomain

            # For HTTP tunnels with subdomains, ensure URL uses subdomain
            if config.protocol == "http" and subdomain and url:
                # URL should already be in subdomain format from server
                # Just ensure it's using the right domain
                if "localhost" in url or "127.0.0.1" in url:
                    url = f"https://{subdomain}.retunnel.net"

            tunnel = Tunnel(
                id=tunnel_id,
                url=url,
                protocol=resp.get("Protocol", config.protocol),
                config=config,
                tunnel_id=tunnel_id,
                subdomain=subdomain,  # Store subdomain for reconnection
            )

            self.tunnels[tunnel.id] = tunnel
            self.logger.info(f"Tunnel established: {tunnel.url}")

            # Start subdomain heartbeat for HTTP tunnels
            if config.protocol == "http" and subdomain:
                asyncio.create_task(self._subdomain_heartbeat(subdomain))

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
                except Exception:
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
        # Normalize message - handle both uppercase and lowercase field names
        if "type" in msg and "Type" not in msg:
            msg["Type"] = msg["type"]
        if "payload" in msg and "Payload" not in msg:
            msg["Payload"] = msg["payload"]

        msg_type = msg.get("Type")

        if msg_type == "NewTunnel":
            # Response to tunnel request
            req_id = msg.get("ReqId")
            future = self.pending_requests.get(req_id) if req_id else None
            if future and not future.done():
                future.set_result(msg)

        elif msg_type == "ErrorResp":
            # Error response
            req_id = msg.get("ReqId") or msg.get("Payload", {}).get("req_id")
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
            # Build WebSocket URL from server address
            if self.server_addr and self.server_addr.startswith(
                ("ws://", "wss://")
            ):
                # Extract the base URL and construct proxy endpoint
                base_url = self.server_addr.replace("/api/v1/ws/tunnel", "")
                ws_url = f"{base_url}/api/v1/ws/proxy"
            else:
                ws_url = f"ws://{self.server_addr}/api/v1/ws/proxy"

            # Include auth headers
            headers = {}
            if self.auth_token:
                headers["Authorization"] = f"Bearer {self.auth_token}"

            self.logger.debug(f"Creating proxy connection to: {ws_url}")

            if self.session:
                proxy_ws = await self.session.ws_connect(
                    ws_url, headers=headers, heartbeat=30
                )
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
            self.logger.warning(
                f"Error creating proxy connection: {e} (URL: {ws_url if 'ws_url' in locals() else 'unknown'})"
            )

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
                        self.logger.error(
                            f"Available tunnels: {list(self.tunnels.keys())}"
                        )
                        for tid, t in self.tunnels.items():
                            self.logger.error(
                                f"  Tunnel {tid}: tunnel_id={t.tunnel_id}, url={t.url}"
                            )
                        break
                    else:
                        self.logger.info(
                            f"Found tunnel for URL {url}: tunnel_id={tunnel.tunnel_id}, tunnel.url={tunnel.url}"
                        )

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

                            self.logger.info(
                                f"Incoming request: {method} {path}{'?' + query if query else ''}"
                            )

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
                            request_bytes = full_request.encode()
                            local_writer.write(request_bytes)
                            if body:
                                local_writer.write(body)
                                request_bytes += body
                            await local_writer.drain()

                            # Count incoming bytes
                            if tunnel:
                                tunnel.bytes_in += len(request_bytes)

                            # Read response
                            response_data = b""
                            status_code = 500  # Default status code
                            response_headers: Dict[str, str] = {}
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

                            # Log response details for debugging
                            self.logger.debug(
                                f"Response status: {status_code}"
                            )
                            self.logger.debug(
                                f"Response headers: {response_headers}"
                            )

                            # Handle redirects (301, 302, 303, 307, 308)
                            if status_code in [301, 302, 303, 307, 308]:
                                self.logger.info(
                                    f"Processing redirect with status {status_code}"
                                )

                                # Check for Location header (case-insensitive)
                                location_key = None
                                location_value = None
                                for key, value in response_headers.items():
                                    if key.lower() == "location":
                                        location_key = key
                                        location_value = value
                                        break

                                if location_value and tunnel and location_key:
                                    self.logger.info(
                                        f"Original Location header: {location_value}"
                                    )

                                    # Parse the location URL
                                    if location_value.startswith("/"):
                                        # Relative URL - prepend tunnel URL
                                        # Remove trailing slash from tunnel URL if present
                                        base_url = tunnel.url.rstrip("/")
                                        new_location = (
                                            f"{base_url}{location_value}"
                                        )
                                        response_headers[location_key] = (
                                            new_location
                                        )
                                        self.logger.info(
                                            f"Rewritten relative redirect to: {new_location}"
                                        )
                                    elif (
                                        location_value.startswith(
                                            "http://localhost"
                                        )
                                        or location_value.startswith(
                                            "http://127.0.0.1"
                                        )
                                        or location_value.startswith(
                                            "https://localhost"
                                        )
                                        or location_value.startswith(
                                            "https://127.0.0.1"
                                        )
                                    ):
                                        # Absolute URL pointing to localhost (with or without port)
                                        # Extract the path and query
                                        try:
                                            parsed = urlparse(location_value)
                                            # Reconstruct with tunnel URL
                                            tunnel_parsed = urlparse(
                                                tunnel.url
                                            )
                                            new_location = urlunparse(
                                                (
                                                    tunnel_parsed.scheme,
                                                    tunnel_parsed.netloc,
                                                    parsed.path,
                                                    parsed.params,
                                                    parsed.query,
                                                    parsed.fragment,
                                                )
                                            )
                                            response_headers[location_key] = (
                                                new_location
                                            )
                                            self.logger.info(
                                                f"Rewritten absolute localhost redirect to: {new_location}"
                                            )
                                        except Exception as e:
                                            self.logger.error(
                                                f"Error parsing redirect URL: {e}"
                                            )
                                    else:
                                        self.logger.info(
                                            f"Not rewriting external redirect: {location_value}"
                                        )
                                else:
                                    self.logger.warning(
                                        f"Redirect response but no Location header found. Headers: {response_headers}"
                                    )

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

                            # Count outgoing bytes
                            if tunnel:
                                tunnel.bytes_out += len(response_body) + len(
                                    str(response_headers)
                                )

                        except Exception as e:
                            self.logger.debug(
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

    async def _subdomain_heartbeat(self, subdomain: str) -> None:
        """Send periodic heartbeats for subdomain keep-alive"""
        try:
            while self.control_ws and not self.control_ws.closed:
                await asyncio.sleep(30)  # Send heartbeat every 30 seconds
                if self.control_ws and not self.control_ws.closed:
                    heartbeat = {
                        "Type": "Heartbeat",
                        "Subdomain": subdomain,
                        "Timestamp": time.time(),
                    }
                    await self._send_message(self.control_ws, heartbeat)
                    self.logger.debug(
                        f"Sent subdomain heartbeat for {subdomain}"
                    )
        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as e:
            self.logger.error(f"Subdomain heartbeat error: {e}")

    async def _control_loop(self) -> None:
        """Listen for control messages"""
        try:
            while (
                self._running
                and self.control_ws
                and not self.control_ws.closed
            ):
                try:
                    msg = await self._receive_message(self.control_ws)
                    await self._handle_message(msg)
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    # Connection lost
                    self.logger.warning(f"Connection lost: {e}")
                    self.is_connected = False
                    self.connection_status = "Disconnected"
                    # Trigger reconnection
                    if self._running and not self._reconnecting:
                        self._reconnect_task = asyncio.create_task(
                            self._reconnect()
                        )
                    break
        except asyncio.CancelledError:
            # Normal shutdown
            pass
        except Exception as e:
            self.logger.error(f"Control loop error: {e}")
            self.is_connected = False
            self.connection_status = "Error"
            # Trigger reconnection
            if self._running and not self._reconnecting:
                self._reconnect_task = asyncio.create_task(self._reconnect())

    async def _maintain_proxy_pool(self) -> None:
        """Maintain a pool of proxy connections"""
        # For now, we create connections on demand
        # This could be optimized to pre-create connections
        pass

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff"""
        self._reconnecting = True

        while self._running:
            try:
                self.connection_status = (
                    f"Reconnecting in {self._reconnect_delay:.0f}s..."
                )
                self.logger.info(
                    f"Attempting reconnection in {self._reconnect_delay} seconds"
                )

                # Wait with exponential backoff
                await asyncio.sleep(self._reconnect_delay)

                # Update status
                self.connection_status = "Connecting..."

                # Close existing connection if any
                if self.control_ws and not self.control_ws.closed:
                    await self.control_ws.close()

                # Close and recreate session
                if self.session and not self.session.closed:
                    await self.session.close()
                    await asyncio.sleep(0.1)

                # Re-establish connection
                await self.connect()

                # Re-request tunnels with same configs
                for tunnel in list(self.tunnels.values()):
                    try:
                        # Request tunnel with same subdomain
                        config = tunnel.config
                        # For HTTP tunnels, try to get the same subdomain
                        if tunnel.protocol == "http" and hasattr(
                            tunnel, "subdomain"
                        ):
                            config.subdomain = tunnel.subdomain

                        new_tunnel = await self.request_tunnel(config)
                        self.logger.info(
                            f"Re-established tunnel: {new_tunnel.url}"
                        )
                    except Exception as e:
                        self.logger.error(
                            f"Failed to re-establish tunnel: {e}"
                        )

                # Success - exit reconnection loop
                self._reconnecting = False
                break

            except Exception as e:
                self.logger.error(f"Reconnection failed: {e}")
                self.connection_status = "Reconnection failed, retrying..."

                # Increase delay with exponential backoff
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

        self._reconnecting = False

    async def close(self) -> None:
        """Close all connections and clean up"""
        self.logger.info("Closing client")

        # Stop running
        self._running = False
        self.is_connected = False
        self.connection_status = "Disconnected"

        # Cancel background tasks
        tasks_to_cancel = []
        for task in [
            self._heartbeat_task,
            self._control_loop_task,
            self._proxy_pool_task,
            self._reconnect_task,
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

        # Close session properly
        if self.session and not self.session.closed:
            await self.session.close()
            # Wait for the underlying connections to close
            await asyncio.sleep(0.1)

        # Small delay to allow aiohttp to clean up
        await asyncio.sleep(0.1)

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

"""WebSocket connection management for ReTunnel client."""

from __future__ import annotations

import asyncio
import struct
from typing import Any, Optional

import websockets

from .exceptions import ConnectionError
from .protocol import Message, deserialize_message, serialize_message


class WebSocketConnection:
    """WebSocket connection wrapper with message framing."""

    def __init__(self, url: str, auth_token: Optional[str] = None):
        self.url = url
        self.auth_token = auth_token
        self._ws: Optional[Any] = None  # WebSocketClientProtocol
        self._read_task: Optional[asyncio.Task] = None
        self._message_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._closed = False

    async def connect(self) -> None:
        """Establish WebSocket connection."""
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            self._ws = await websockets.connect(
                self.url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
            )
            self._closed = False

            # Start message reader task
            self._read_task = asyncio.create_task(self._read_messages())

        except Exception as e:
            raise ConnectionError(f"Failed to connect: {str(e)}")

    async def _read_messages(self) -> None:
        """Read messages from WebSocket."""
        try:
            while not self._closed and self._ws:
                # Read length prefix (8 bytes)
                length_data = await self._ws.recv()
                if isinstance(length_data, str):
                    length_data = length_data.encode()

                if len(length_data) < 8:
                    continue

                msg_length = struct.unpack(">Q", length_data[:8])[0]
                msg_data = length_data[8:]

                # Read remaining message data if needed
                while len(msg_data) < msg_length:
                    chunk = await self._ws.recv()
                    if isinstance(chunk, str):
                        chunk = chunk.encode()
                    msg_data += chunk

                # Decode and queue message
                try:
                    message = deserialize_message(msg_data[:msg_length])
                    await self._message_queue.put(message)
                except Exception as e:
                    # Log but don't crash on decode errors
                    print(f"Failed to decode message: {e}")

        except websockets.ConnectionClosed:
            self._closed = True
        except Exception as e:
            self._closed = True
            print(f"Read error: {e}")

    async def send(self, message: Message) -> None:
        """Send a message."""
        if not self._ws or self._closed:
            raise ConnectionError("Not connected")

        try:
            # Serialize message
            msg_data = serialize_message(message)
            # Add length prefix
            length_prefix = struct.pack(">Q", len(msg_data))
            data = length_prefix + msg_data
            await self._ws.send(data)
        except Exception as e:
            raise ConnectionError(f"Send failed: {str(e)}")

    async def receive(
        self, timeout: Optional[float] = None
    ) -> Optional[Message]:
        """Receive a message."""
        try:
            if timeout:
                return await asyncio.wait_for(
                    self._message_queue.get(), timeout
                )
            else:
                return await self._message_queue.get()
        except asyncio.TimeoutError:
            return None

    async def close(self) -> None:
        """Close the connection."""
        self._closed = True

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            await self._ws.close()
            self._ws = None

    @property
    def is_connected(self) -> bool:
        """Check if connection is active."""
        return self._ws is not None and not self._closed

    async def __aenter__(self) -> WebSocketConnection:
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit."""
        await self.close()

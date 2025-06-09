#!/usr/bin/env python
"""Test WebSocket connection directly"""

import asyncio
import websockets

async def test_connection():
    url = "ws://127.0.0.1:6400/api/v1/ws/tunnel"
    headers = {
        "Authorization": "Bearer test_token"
    }
    
    try:
        async with websockets.connect(url, additional_headers=headers) as ws:
            print("Connected successfully!")
            # Try to receive the first message
            msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"Received: {msg}")
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
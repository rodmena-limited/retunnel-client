#!/usr/bin/env python
"""Debug WebSocket messages"""

import asyncio
import msgpack
import struct
import websockets

async def debug_connection():
    url = "ws://127.0.0.1:6400/api/v1/ws/tunnel"
    headers = {
        "Authorization": "Bearer EVzfwc2D2GHgrv_ZDT5brw5ftRiOUuOrXYH3SMvToc4"
    }
    
    async with websockets.connect(url, additional_headers=headers) as ws:
        print("Connected!")
        
        # Send Auth message
        auth_msg = {
            "type": "Auth",
            "token": "EVzfwc2D2GHgrv_ZDT5brw5ftRiOUuOrXYH3SMvToc4",
            "client_id": "cli_test",
            "version": "2.0.0",
            "user": "",
            "password": "",
            "os": "Linux",
            "arch": "x86_64",
        }
        
        data = msgpack.packb(auth_msg)
        length = struct.pack(">Q", len(data))
        await ws.send(length + data)
        
        print("Sent Auth message")
        
        # Receive messages
        for i in range(5):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                if isinstance(msg, str):
                    print(f"Received text: {msg}")
                else:
                    print(f"Received {len(msg)} bytes")
                    # Try to decode
                    if len(msg) >= 8:
                        length = struct.unpack(">Q", msg[:8])[0]
                        print(f"  Length prefix: {length}")
                        msg_data = msg[8:]
                        if len(msg_data) >= length:
                            # Decode with various options
                            try:
                                decoded = msgpack.unpackb(msg_data[:length], raw=False)
                                print(f"  Decoded (raw=False): {decoded}")
                            except Exception as e:
                                print(f"  Error with raw=False: {e}")
                                
                            try:
                                decoded = msgpack.unpackb(msg_data[:length], raw=True)
                                print(f"  Decoded (raw=True): {decoded}")
                            except Exception as e:
                                print(f"  Error with raw=True: {e}")
            except asyncio.TimeoutError:
                print("Timeout waiting for message")
                break

if __name__ == "__main__":
    asyncio.run(debug_connection())
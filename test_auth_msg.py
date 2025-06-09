#!/usr/bin/env python
"""Test Auth message serialization"""

from retunnel.core.protocol import Auth
import msgpack

# Create auth message
auth = Auth(
    token="test_token",
    client_id="cli_test",
    version="2.0.0",
    os="Linux",
    arch="x86_64",
)

# Check what gets serialized
data = auth.model_dump(by_alias=True)
print("Serialized data:", data)

# Check msgpack
packed = msgpack.packb(data)
unpacked = msgpack.unpackb(packed)
print("After msgpack round-trip:", unpacked)
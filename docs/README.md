# ReTunnel Python Client Documentation

## Overview

ReTunnel is a platform for securely exposing local servers to the internet. This Python package is currently a placeholder for the upcoming official ReTunnel client.

## Installation

```bash
pip install retunnel
```

## Quick Start

```python
from retunnel import ReTunnelClient, hello

# Print hello message
print(hello())

# Create a tunnel (placeholder)
with ReTunnelClient() as client:
    tunnel_url = client.create_tunnel(port=8080)
    print(f"Tunnel URL: {tunnel_url}")
```

## API Reference

### ReTunnelClient

The main client class for interacting with ReTunnel services.

#### Methods

- `__init__(api_key=None)`: Initialize the client with an optional API key
- `connect()`: Connect to the ReTunnel service
- `create_tunnel(port=8080)`: Create a tunnel for the specified port
- `close()`: Close the connection

#### Context Manager

The client supports Python's context manager protocol:

```python
with ReTunnelClient() as client:
    # Use client here
    pass
```

### hello()

Returns a welcome message from ReTunnel.

## More Information

Visit [https://retunnel.com](https://retunnel.com) for more information about ReTunnel.
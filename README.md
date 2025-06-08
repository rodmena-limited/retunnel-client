# ReTunnel Python Client

[![PyPI Version](https://badge.fury.io/py/retunnel.svg)](https://pypi.org/project/retunnel/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Placeholder package for ReTunnel - Securely expose local servers to the internet**

ReTunnel is a free platform that allows developers to securely expose local servers to the internet through powerful tunneling capabilities. This Python package serves as a placeholder for the upcoming official ReTunnel client.

## Features (Placeholder)

This is currently a placeholder package. The full ReTunnel client will include:

* Secure tunnel creation and management
* Multiple protocol support (HTTP, HTTPS, TCP)
* Custom domain configuration
* Authentication and API key management
* Automatic reconnection and failover
* Webhook forwarding
* Request inspection and replay

For now, this package provides a simple hello-world implementation to reserve the package name on PyPI.


## Installation

You can install `retunnel` from PyPI using pip:

```bash
pip install retunnel
```

## Usage

Here's a simple example demonstrating the placeholder functionality:

```python
from retunnel import ReTunnelClient, hello

# Simple hello message
print(hello())

# Create a client instance
client = ReTunnelClient()

# Connect to the service (placeholder)
if client.connect():
    print("Connected to ReTunnel service")
    
    # Create a tunnel (placeholder)
    tunnel_url = client.create_tunnel(port=8080)
    print(f"Tunnel created: {tunnel_url}")
    
    # Close the connection
    client.close()

# Or use context manager
with ReTunnelClient(api_key="your-api-key") as client:
    tunnel_url = client.create_tunnel(port=3000)
    print(f"Tunnel URL: {tunnel_url}")
```

## Running Tests

To run the unit tests, install pytest and run:

```bash
pip install pytest
```

To run the tests:

```bash
pytest tests/
```

## Documentation

Full documentation for ReTunnel is available at [https://retunnel.com](https://retunnel.com)

## Contributing

This is a placeholder package. The actual ReTunnel client development is happening at the main ReTunnel repository.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Links

* Website: [https://retunnel.com](https://retunnel.com)
* PyPI: [https://pypi.org/project/retunnel/](https://pypi.org/project/retunnel/)

---

**Note:** This is a placeholder package. The full-featured ReTunnel client is under development.

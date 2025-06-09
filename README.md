# ReTunnel Client

[![PyPI Version](https://badge.fury.io/py/retunnel.svg)](https://pypi.org/project/retunnel/)
[![Python Versions](https://img.shields.io/pypi/pyversions/retunnel.svg)](https://pypi.org/project/retunnel/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

ReTunnel is a secure tunnel service that allows you to expose local servers to the internet. This is the official Python client library and CLI.

## Features

- 🚀 **Easy to use** - Single command to expose your local server
- 🔒 **Secure** - All connections are encrypted
- 🌐 **HTTP/HTTPS and TCP** - Support for web and TCP services
- 🔑 **Automatic registration** - No sign-up required for basic usage
- ⚡ **High performance** - Built with asyncio for efficiency
- 🎛️ **Professional CLI** - Rich terminal interface with Typer

## Installation

```bash
pip install retunnel
```

Requires Python 3.9 or higher.

## Quick Start

### HTTP Tunnel

Expose a local web server on port 8080:

```bash
retunnel http 8080
```

### TCP Tunnel

Expose a local TCP service on port 22:

```bash
retunnel tcp 22
```

### With Custom Subdomain

Request a specific subdomain (subject to availability):

```bash
retunnel http 8080 --subdomain myapp
```

### With Authentication

Protect your tunnel with HTTP Basic Auth:

```bash
retunnel http 8080 --auth user:password
```

## Configuration

### Server Endpoint

By default, ReTunnel connects to `localhost:6400`. You can configure this using:

- Environment variable: `RETUNNEL_SERVER_ENDPOINT=your.server.com:port`
- Command-line option: `--server your.server.com:port`
- Configuration file: `server_addr: your.server.com:port`

### Save Authentication Token

Save your auth token for persistent access:

```bash
retunnel authtoken YOUR_AUTH_TOKEN
```

### Configuration File

Create a `retunnel.yml` file to define multiple tunnels:

```yaml
server_addr: ${RETUNNEL_SERVER_ENDPOINT:localhost:6400}
auth_token: ${RETUNNEL_AUTH_TOKEN}
log_level: INFO

tunnels:
  - name: web
    protocol: http
    local_port: 8080
    subdomain: myapp
    
  - name: api
    protocol: http
    local_port: 3000
    auth: user:pass
    
  - name: ssh
    protocol: tcp
    local_port: 22
```

Then start all tunnels:

```bash
retunnel start retunnel.yml
```

## Environment Variables

- `RETUNNEL_SERVER_ENDPOINT` - Server endpoint (default: `localhost:6400`)
- `RETUNNEL_AUTH_TOKEN` - Authentication token
- `RETUNNEL_LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)

## Python API

```python
import asyncio
from retunnel import ReTunnelClient, TunnelConfig

async def main():
    # Create client
    client = ReTunnelClient()
    
    # Connect to server
    await client.connect()
    
    # Create HTTP tunnel
    config = TunnelConfig(protocol="http", local_port=8080)
    tunnel = await client.request_tunnel(config)
    
    print(f"Tunnel URL: {tunnel.url}")
    
    # Keep running
    await asyncio.Event().wait()

asyncio.run(main())
```

## Advanced Usage

### Custom Server

Connect to a self-hosted ReTunnel server:

```bash
retunnel http 8080 --server your-server.com:8000
```

### Multiple Tunnels

Use the configuration file to manage multiple tunnels simultaneously.

### Logging

Set log level for debugging:

```bash
retunnel http 8080 --log-level DEBUG
```

## CLI Commands

- `retunnel http PORT` - Create HTTP tunnel
- `retunnel tcp PORT` - Create TCP tunnel
- `retunnel start CONFIG` - Start tunnels from config file
- `retunnel authtoken TOKEN` - Save authentication token
- `retunnel config` - Manage configuration
- `retunnel version` - Show version
- `retunnel credits` - Show open source credits

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/retunnel/retunnel-client
cd retunnel-client

# Install with development dependencies
make install-dev
```

### Testing

```bash
# Run tests
make test

# Run linting
make lint

# Run type checking
make typecheck

# Format code
make format
```

### Building

```bash
make build
```

## License

MIT License - see LICENSE file for details.

## Credits

ReTunnel uses these excellent open source libraries:

- aiohttp - Async HTTP client/server
- websockets - WebSocket client/server
- msgpack - Efficient serialization
- typer - CLI framework
- rich - Terminal formatting
- pydantic - Data validation

## Support

- Documentation: https://docs.retunnel.com
- Issues: https://github.com/retunnel/retunnel-client/issues
- Email: support@retunnel.com

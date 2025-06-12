# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build and Development Commands

### Development Setup
```bash
# Install package with dev dependencies
make install-dev
```

### Testing Commands
```bash
# Run all tests with coverage
make test

# Run tests without coverage (faster)
make test-quick

# Run tests with verbose output
make test-verbose

# Run specific test file
uv run pytest tests/test_cli.py -v

# Run unit tests only (faster, no server required)
uv run pytest tests/test_*unit*.py tests/test_cli.py tests/test_protocol.py tests/test_config.py tests/test_utils.py tests/test_exceptions.py --cov

# Run integration tests against real server at 127.0.0.1:6400
uv run pytest tests/test_client.py tests/test_api.py tests/test_connection.py
```

### Code Quality Commands
```bash
# Format code with isort and black
make format

# Check if code is properly formatted
make format-check

# Run flake8 linting
make lint

# Run mypy type checking
make typecheck

# Run all checks (format, lint, typecheck, test)
make check
```

### Build and Release
```bash
# Build distribution packages
make build

# Upload to PyPI
make upload
```

## Architecture Overview

### Package Structure
- **`retunnel/core/`** - Core functionality shared between client and server
  - `protocol.py` - Message definitions using dataclasses and MessagePack serialization
  - `connection.py` - WebSocket connection wrapper with async message handling
  - `config.py` - Pydantic-based configuration management
  - `exceptions.py` - Comprehensive exception hierarchy
  - `api.py` - REST API types and responses

- **`retunnel/client/`** - Client implementation
  - `high_performance_model.py` - Main async client managing tunnels and proxy connections
  - `cli.py` - Typer-based CLI with Rich terminal UI
  - `api_client.py` - REST API client for authentication
  - `config_manager.py` - Manages ~/.retunnel.conf persistence

- **`retunnel/utils/`** - Utility functions
  - `id.py` - ID generation utilities

### Key Design Patterns
1. **Async/Await Throughout** - All network operations use asyncio for performance
2. **Message-Based Protocol** - Clean client-server separation via typed messages
3. **Binary Protocol** - MessagePack for efficient serialization
4. **Configuration Management** - Environment variables (RETUNNEL_*) and config files
5. **Rich CLI** - Terminal UI with progress bars, colors, and real-time stats

### Testing Approach
- Integration tests connect to real server at 127.0.0.1:6400 (no mocks)
- Unit tests use mocks for isolated testing
- Current coverage: 84.3% (target: 90%)
- Tests are rate-limited to avoid server throttling

### Environment Variables
- `RETUNNEL_SERVER_ENDPOINT` - Server endpoint (default: localhost:6400)
- `RETUNNEL_AUTH_TOKEN` - Authentication token
- `RETUNNEL_LOG_LEVEL` - Logging level (DEBUG, INFO, WARNING, ERROR)

### Performance Notes
- Server authentication is currently slow (10-16 seconds) due to full table scan
- Client implements automatic reconnection with exponential backoff
- Binary protocol minimizes overhead for proxy data

### Known Issues
- Server closes WebSocket after Auth message (see SERVER_INTEGRATION_NOTES.md)
- Some aiohttp ClientResponse cleanup warnings on shutdown
- Features pending: byte counting, msgpack optimization
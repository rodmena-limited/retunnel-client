# Server Integration Notes

## Current Status

The ReTunnel client has been successfully rewritten with:
- ✅ Production-ready code structure
- ✅ Professional CLI using Typer
- ✅ Python 3.9+ support
- ✅ Configurable server endpoint via RETUNNEL_SERVER_ENDPOINT
- ✅ Code quality tools (isort, black, flake8)
- ✅ 64% test coverage (target: 90%)

## Integration Issue

The server at localhost:6400 is closing WebSocket connections immediately after receiving the Auth message. This prevents full integration testing.

### WebSocket Connection Flow

1. Client connects to `ws://localhost:6400/api/v1/ws/tunnel` ✅
2. Server accepts WebSocket upgrade (101 Switching Protocols) ✅
3. Client sends Auth message with token ✅
4. Server closes connection with code 1000 (OK) ❌
5. Expected: Server should send AuthResp message

### Possible Causes

1. **Invalid Auth Token**: The test token might not be recognized by the server
2. **Protocol Mismatch**: Server might expect different message format or flow
3. **Missing User Registration**: Server might require user to exist before auth

### Recommendations for Server Implementation

1. Implement proper WebSocket message handling for Auth messages
2. Send AuthResp message after successful authentication
3. Keep connection open for subsequent tunnel requests
4. Implement auto-registration endpoint at `/api/v1/auth/register`

## Test Configuration

To run tests against a real server:

```bash
# Set server endpoint
export RETUNNEL_SERVER_ENDPOINT=localhost:6400

# Run tests
uv run pytest

# For specific integration tests
uv run pytest tests/test_client.py -k "test_client_connect"
```

## Coverage Note

Current coverage is limited by server integration issues. Unit tests and CLI tests provide good coverage of client-side logic. Full integration tests will achieve 90%+ coverage once server implements the expected protocol.
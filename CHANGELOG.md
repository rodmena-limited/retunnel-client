# Changelog

## Unreleased

- `retunnel.core.exceptions.handle_api_error` is removed. Nothing in the
  package used it.
- A local app that restarts on the other loopback family (127.0.0.1 <-> ::1)
  is followed without restarting `retunnel`. Before, the first family that
  answered was the only one tried for the rest of the process, so every
  request failed after such a restart.
- A REST reply whose body is JSON but not an object (for example a list) now
  raises `APIError` instead of being returned to callers that expect a dict.

## 3.3.0 (2026-09-27)

Behaviour changes that matter to anyone running `retunnel` under a supervisor
(systemd, supervice, a shell loop).

- **The client no longer gives up on a server that says "try again later".**
  `SERVICE_UNAVAILABLE` (database blip), `POOL_EXHAUSTED`,
  `TUNNEL_CREATE_FAILED` and `HOSTNAME_NO_CERTIFICATE` (certificate still
  being issued) are now retried forever, once a minute at most. Before, six
  such refusals in a row made the client exit.
- **Retry-budget exhaustion now exits 75 (EX_TEMPFAIL), not 69.** 69 still
  means a real refusal (bad token, name not yours, invalid request) that
  restarting cannot fix. 75 means "restart me later". Configure supervisors to
  restart on 75 and not on 69.
- **Reconnect backoff never exceeds 60 s** (jitter used to stretch it to 90 s).
- **A slow or hung local app can no longer freeze the tunnel.** HTTP and
  WebSocket traffic use separate connection pools (256 each, the server's own
  stream limit). Waiting for a pool slot or a local connection times out after
  30 s. A request the server has abandoned is cancelled locally.
- **Request bodies buffered at once are capped at 64 MiB per process.** Past
  that, new requests are refused instead of exhausting memory on a small
  machine.
- Dependency floors raised to releases with no known advisories, and ceilings
  added at the next major version. `aiofiles` removed (unused).
- Removed `APIClient.verify_token` and `APIClient.reactivate_token`: both
  called server endpoints that no longer exist.

## 3.2.4

- `--spa` tunnels are served on their own origin, `https://<id>.retunnel.net`.
  The shared-origin warning is gone.

## 3.2.3

- Group options work after nested subcommands, e.g. `retunnel hostname list --json`.

## 3.2.2

- The client never overwrites or deletes an unreadable `~/.retunnel.conf`
  (exit 78). Basic auth compared per RFC 7617. Registration throttling is
  reported clearly.

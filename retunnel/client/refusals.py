"""How the client treats each server refusal (issuedb #93, audit R3).

Three kinds:
- terminal: retrying cannot help; the process exits with the mapped code.
- transient: the server says it will pass (database blip, pool briefly
  empty, allocator contention, certificate still being issued). Retried
  forever at a capped rate: an unattended client must never give up on
  a server that told it to wait.
- anything else: retried RETRY_BUDGET times, then the client exits with
  EXIT_TEMPFAIL (75), which supervisors restart, unlike 69.
"""

from __future__ import annotations

from retunnel.core.exceptions import TerminalError, TunnelError
from retunnel.msg.messages import Error

EXIT_TEMPFAIL = 75
MAX_BACKOFF = 60.0
RETRY_BUDGET = 6

TERMINAL_CODES: dict[str, int] = {
    "UNAUTHORIZED": 69,
    "AUTH_REQUIRED": 69,
    "SUBDOMAIN_UNAVAILABLE": 69,
    "PATH_TAKEN": 69,
    "PATH_LIMIT": 69,
    "TCP_DISABLED": 69,
    "HOSTNAME_NOT_REGISTERED": 69,
    "HOSTNAME_NOT_VERIFIED": 69,
    "HOSTNAME_TAKEN": 69,
    "INVALID_PATH": 2,
    "INVALID_HOSTNAME": 2,
    "UNSUPPORTED_PROTOCOL": 2,
}

TRANSIENT_CODES = frozenset(
    {
        "SERVICE_UNAVAILABLE",
        "POOL_EXHAUSTED",
        "TUNNEL_CREATE_FAILED",
        "HOSTNAME_NO_CERTIFICATE",
    }
)


class TransientRefusal(TunnelError):
    """The server refused for now and said so; never counts toward a budget."""


def refusal(err: Error) -> Exception:
    exit_code = TERMINAL_CODES.get(err.code)
    if exit_code is not None:
        return TerminalError(err.code, err.message, exit_code)
    if err.code in TRANSIENT_CODES:
        return TransientRefusal(f"{err.message} [{err.code}]")
    return TunnelError(f"{err.message} [{err.code}]")


def next_delay(delay: float) -> float:
    return min(delay * 2, MAX_BACKOFF)


def jittered(delay: float, unit_random: float) -> float:
    return min(MAX_BACKOFF, delay * (0.5 + unit_random))


__all__ = [
    "EXIT_TEMPFAIL",
    "MAX_BACKOFF",
    "RETRY_BUDGET",
    "TERMINAL_CODES",
    "TRANSIENT_CODES",
    "TransientRefusal",
    "jittered",
    "next_delay",
    "refusal",
]

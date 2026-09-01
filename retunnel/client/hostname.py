"""Client-side validation of a custom hostname (issuedb #60).

Deliberately a MIRROR of the server's rules, not a replacement for them: the
server revalidates everything it receives. This exists so an obvious typo
costs no round trip, and so the value put on the wire is already canonical
(lowercased, no trailing dot, no port) and therefore compares equal to what
the server stored.
"""

from __future__ import annotations

import re

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789-.")

MAX_HOSTNAME_LENGTH = 253


class InvalidHostname(ValueError):
    """The supplied value is not a usable custom hostname."""


def normalize_hostname(raw: str) -> str:
    """Return the canonical form of `raw`, or raise InvalidHostname."""
    host = raw.strip().lower().rstrip(".")

    if not host:
        raise InvalidHostname("hostname is empty")
    if len(host) > MAX_HOSTNAME_LENGTH:
        raise InvalidHostname(f"longer than {MAX_HOSTNAME_LENGTH} characters")
    if ":" in host:
        raise InvalidHostname("a port must not be included")
    if any(c not in _ALLOWED for c in host):
        raise InvalidHostname(
            "may contain only a-z, 0-9, '-' and '.'; encode an "
            "internationalised name as punycode (xn--...) first"
        )
    if _IPV4.match(host):
        raise InvalidHostname("an IP address is not a hostname")

    labels = host.split(".")
    if len(labels) < 2:
        raise InvalidHostname("must be fully qualified, e.g. app.example.com")
    for label in labels:
        if not label:
            raise InvalidHostname("has an empty label")
        if not _LABEL.match(label):
            raise InvalidHostname(f"label {label!r} is not a valid DNS label")
    if labels[-1].isdigit():
        raise InvalidHostname("the last label must not be all digits")

    return host


__all__ = ["MAX_HOSTNAME_LENGTH", "InvalidHostname", "normalize_hostname"]

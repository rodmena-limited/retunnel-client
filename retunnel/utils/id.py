"""ID generation utilities."""

import random
import string
import time
from typing import Optional


def generate_id(prefix: Optional[str] = None, length: int = 16) -> str:
    """Generate a unique identifier.

    Args:
        prefix: Optional prefix for the ID
        length: Length of random part (default 16)

    Returns:
        Generated ID string
    """
    chars = string.ascii_lowercase + string.digits
    random_part = "".join(random.choices(chars, k=length))

    if prefix:
        return f"{prefix}_{random_part}"
    return random_part


def generate_session_id() -> str:
    """Generate a session ID with timestamp."""
    timestamp = int(time.time() * 1000)
    random_part = generate_id(length=8)
    return f"{timestamp}_{random_part}"


def generate_request_id() -> str:
    """Generate a request ID."""
    return generate_id("req", 12)


def generate_tunnel_id() -> str:
    """Generate a tunnel ID."""
    return generate_id("tun", 12)


def generate_client_id() -> str:
    """Generate a client ID."""
    return generate_id("cli", 16)

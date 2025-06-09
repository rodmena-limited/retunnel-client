"""
ID generation utilities
"""

import random
import string
import time
from typing import Optional


def generate_id(prefix: Optional[str] = None, length: int = 8) -> str:
    """
    Generate a unique ID.

    Args:
        prefix: Optional prefix for the ID
        length: Length of random part (default 8)

    Returns:
        Generated ID string
    """
    # Use alphanumeric characters (no confusing ones like 0/O, 1/l)
    chars = string.ascii_lowercase + string.digits
    chars = chars.replace("0", "").replace("1", "").replace("l", "")

    # Generate random part
    random_part = "".join(random.choices(chars, k=length))

    if prefix:
        return f"{prefix}-{random_part}"
    return random_part


def generate_client_id() -> str:
    """Generate a client ID"""
    return generate_id(prefix="client", length=12)


def generate_tunnel_id() -> str:
    """Generate a tunnel ID"""
    return generate_id(prefix="tun", length=8)


def generate_request_id() -> str:
    """Generate a request ID"""
    return generate_id(prefix="req", length=8)


def generate_session_id() -> str:
    """Generate a session ID with timestamp"""
    timestamp = int(time.time())
    random_part = generate_id(length=6)
    return f"sess-{timestamp}-{random_part}"

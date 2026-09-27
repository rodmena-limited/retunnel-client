"""
API client for ReTunnel server interactions
"""

from __future__ import annotations

import types
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
from aiohttp import ClientSession
from typing_extensions import Self

from ..core.exceptions import TerminalError


class APIError(Exception):
    """API request error"""

    def __init__(
        self, status: int, message: str, retry_after: int | None = None
    ):
        self.status = status
        self.message = message
        self.retry_after = retry_after
        super().__init__(f"API Error {status}: {message}")


EXIT_TEMPFAIL = 75


def registration_refusal(exc: BaseException) -> TerminalError | None:
    """A temporary server refusal of new-account registration, or None."""
    if not isinstance(exc, APIError) or exc.status not in (429, 503):
        return None
    wait = f"; retry in {exc.retry_after}s" if exc.retry_after else ""
    return TerminalError(
        "REGISTRATION_REFUSED",
        f"new-account registration refused ({exc.status}): {exc.message}{wait}",
        exit_code=EXIT_TEMPFAIL,
    )


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_loopback_url(url: str) -> bool:
    """True only when the URL's host IS a loopback name, never a substring."""
    try:
        host = urlparse(url).hostname
    except ValueError:
        return False
    return host is not None and host.lower() in _LOOPBACK_HOSTS


class ReTunnelAPIClient:
    """Client for ReTunnel API interactions"""

    def __init__(
        self,
        api_url: str = "https://api.retunnel.net",
        ssl_verify: bool = True,
    ):
        """Initialize API client

        Args:
            api_url: Base URL for API endpoints
            ssl_verify: Whether to verify SSL certificates (default: True)
        """
        self.api_url = api_url.rstrip("/")
        self.ssl_verify = ssl_verify
        self._session: ClientSession | None = None

    async def __aenter__(self) -> Self:
        """Async context manager entry"""
        # Add timeout for all requests (2 seconds)
        timeout = aiohttp.ClientTimeout(total=2)
        # Use SSL verification setting (#27)
        # For localhost, always disable SSL verification
        ssl_context = (
            False if is_loopback_url(self.api_url) else self.ssl_verify
        )
        connector = aiohttp.TCPConnector(ssl=ssl_context)
        self._session = ClientSession(timeout=timeout, connector=connector)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Async context manager exit"""
        if self._session:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make API request

        Args:
            method: HTTP method
            path: API path
            json_data: JSON data to send
            headers: Additional headers

        Returns:
            Response data

        Raises:
            APIError: If request fails
        """
        if not self._session:
            raise RuntimeError(
                "API client not initialized. Use async context manager."
            )

        url = urljoin(self.api_url, path)

        async with self._session.request(
            method=method, url=url, json=json_data, headers=headers
        ) as response:
            try:
                data = await response.json()
            except (aiohttp.ContentTypeError, ValueError):
                data = {"error": await response.text()}

            if response.status >= 400:
                error_msg = data.get(
                    "detail", data.get("error", "Unknown error")
                )
                header = response.headers.get("Retry-After", "")
                raise APIError(
                    response.status,
                    error_msg,
                    int(header) if header.isdigit() else None,
                )

            if not isinstance(data, dict):
                raise APIError(
                    response.status, "response body is not a JSON object"
                )
            return data

    async def register_user(self, email: str | None = None) -> dict[str, Any]:
        """Register a new user

        Args:
            email: User email (optional, will generate anonymous user if not provided)

        Returns:
            User data including auth token
        """
        # Generate anonymous email if not provided
        if not email:
            import uuid

            email = f"anon-{uuid.uuid4().hex[:8]}@retunnel.com"

        data = {"email": email}
        return await self._request(
            "POST", "/api/v1/auth/register", json_data=data
        )

    async def refresh_token(self, auth_token: str) -> dict[str, Any]:
        """Refresh authentication token

        Args:
            auth_token: Current auth token

        Returns:
            New auth token data
        """
        headers = {"Authorization": f"Bearer {auth_token}"}
        return await self._request(
            "POST", "/api/v1/auth/refresh", headers=headers
        )

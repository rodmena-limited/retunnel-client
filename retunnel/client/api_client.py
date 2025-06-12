"""
API client for ReTunnel server interactions
"""

from typing import Any, Optional
from urllib.parse import urljoin

import aiohttp
from aiohttp import ClientSession


class APIError(Exception):
    """API request error"""

    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"API Error {status}: {message}")


class ReTunnelAPIClient:
    """Client for ReTunnel API interactions"""

    def __init__(self, api_url: str = "https://api.retunnel.net"):
        """Initialize API client

        Args:
            api_url: Base URL for API endpoints
        """
        self.api_url = api_url.rstrip("/")
        self._session: Optional[ClientSession] = None

    async def __aenter__(self) -> "ReTunnelAPIClient":
        """Async context manager entry"""
        # Add timeout for all requests (2 seconds)
        timeout = aiohttp.ClientTimeout(total=2)
        # Disable SSL verification for development/self-signed certificates
        connector = aiohttp.TCPConnector(ssl=False)
        self._session = ClientSession(timeout=timeout, connector=connector)
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit"""
        if self._session:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
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
            except Exception:
                data = {"error": await response.text()}

            if response.status >= 400:
                error_msg = data.get(
                    "detail", data.get("error", "Unknown error")
                )
                raise APIError(response.status, error_msg)

            return data  # type: ignore[no-any-return]

    async def register_user(
        self, email: Optional[str] = None
    ) -> dict[str, Any]:
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

    async def verify_token(self, auth_token: str) -> bool:
        """Verify if auth token is valid

        Args:
            auth_token: Auth token to verify

        Returns:
            True if valid, False otherwise
        """
        try:
            headers = {"Authorization": f"Bearer {auth_token}"}
            await self._request("GET", "/api/v1/users/me", headers=headers)
            return True
        except APIError:
            return False

    async def reactivate_token(self, old_token: str) -> dict[str, Any]:
        """Reactivate an expired or invalid token

        Args:
            old_token: The old/invalid auth token

        Returns:
            New auth token data with same user account
        """
        data = {"old_token": old_token}
        return await self._request(
            "POST", "/api/v1/auth/reactivate-token", json_data=data
        )

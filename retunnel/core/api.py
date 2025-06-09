"""API client for ReTunnel server interactions."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import aiohttp
from pydantic import BaseModel

from .exceptions import APIError, AuthenticationError


class UserInfo(BaseModel):
    """User information from API."""

    user_id: str
    username: str
    email: Optional[str] = None
    auth_token: str


class APIClient:
    """Client for ReTunnel REST API."""

    def __init__(self, base_url: Optional[str] = None):
        if base_url is None:
            # Use server endpoint from environment or default to localhost:6400
            server_endpoint = os.environ.get(
                "RETUNNEL_SERVER_ENDPOINT", "localhost:6400"
            )
            # Convert to HTTP URL
            if (
                "localhost" in server_endpoint
                or "127.0.0.1" in server_endpoint
            ):
                base_url = f"http://{server_endpoint}"
            else:
                base_url = f"https://{server_endpoint}"
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> APIClient:
        """Async context manager entry."""
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(
        self, exc_type: Any, exc_val: Any, exc_tb: Any
    ) -> None:
        """Async context manager exit."""
        if self._session:
            await self._session.close()

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if not self._session:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Make HTTP request to API."""
        session = await self._get_session()
        url = f"{self.base_url}{path}"

        try:
            async with session.request(
                method, url, json=json, headers=headers
            ) as resp:
                data = await resp.json()

                if resp.status >= 400:
                    error_msg = data.get("detail", "API request failed")
                    raise APIError(error_msg, resp.status)

                return data  # type: ignore[no-any-return]
        except aiohttp.ClientError as e:
            raise APIError(f"Network error: {str(e)}")

    async def register_anonymous(self) -> UserInfo:
        """Register a new anonymous user."""
        import random
        import string

        # Generate random anonymous email
        random_id = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        )
        anon_email = f"anon_{random_id}@retunnel.io"

        data = await self._request(
            "POST",
            "/api/v1/auth/register",
            json={"email": anon_email},
        )

        return UserInfo(
            user_id=data["id"],
            username=data.get("email", anon_email).split("@")[
                0
            ],  # Use email prefix as username
            email=data.get("email"),
            auth_token=data["auth_token"],
        )

    async def verify_token(self, token: str) -> bool:
        """Verify if authentication token is valid."""
        try:
            await self._request(
                "GET",
                "/api/v1/auth/verify",
                headers={"Authorization": f"Bearer {token}"},
            )
            return True
        except APIError:
            return False

    async def refresh_token(self, token: str) -> str:
        """Refresh authentication token."""
        try:
            data = await self._request(
                "POST",
                "/api/v1/auth/refresh",
                headers={"Authorization": f"Bearer {token}"},
            )
            return data["token"]  # type: ignore[no-any-return]
        except APIError as e:
            if e.status_code == 401:
                raise AuthenticationError("Invalid or expired token")
            raise

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

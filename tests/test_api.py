"""Fast API tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from retunnel.core.api import APIClient
from retunnel.core.exceptions import APIError


class TestAPIClient:
    """Fast API client tests."""

    def test_init(self):
        """Test initialization."""
        client = APIClient("http://localhost:6400")
        assert client.base_url == "http://localhost:6400"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test closing client."""
        client = APIClient("http://localhost:6400")
        with patch.object(client, "_session") as mock_session:
            mock_session.close = AsyncMock()
            await client.close()
            mock_session.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_success(self):
        """Test successful request."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={"success": True})
        
        client = APIClient("http://localhost:6400")
        with patch.object(client, "_session") as mock_session:
            mock_session.request = AsyncMock(return_value=mock_response)
            
            result = await client._request("GET", "/test")
            assert result == {"success": True}

    @pytest.mark.asyncio
    async def test_request_error(self):
        """Test request error."""
        mock_response = MagicMock()
        mock_response.status = 500
        mock_response.text = AsyncMock(return_value="Server Error")
        
        client = APIClient("http://localhost:6400")
        with patch.object(client, "_session") as mock_session:
            mock_session.request = AsyncMock(return_value=mock_response)
            
            with pytest.raises(APIError):
                await client._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_register_anonymous(self):
        """Test anonymous registration."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "token": "test_token",
            "user_id": "123",
            "email": "test@example.com"
        })
        
        client = APIClient("http://localhost:6400")
        with patch.object(client, "_session") as mock_session:
            mock_session.request = AsyncMock(return_value=mock_response)
            
            user_info = await client.register_anonymous()
            assert user_info.token == "test_token"
            assert user_info.user_id == "123"

    @pytest.mark.asyncio
    async def test_create_tunnel(self):
        """Test creating tunnel."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "tunnel_id": "tunnel123",
            "url": "http://test.ngrok.io",
            "protocol": "http"
        })
        
        client = APIClient("http://localhost:6400")
        with patch.object(client, "_session") as mock_session:
            mock_session.request = AsyncMock(return_value=mock_response)
            
            tunnel_info = await client.create_tunnel(
                token="test_token",
                protocol="http",
                local_port=8080
            )
            assert tunnel_info.tunnel_id == "tunnel123"
            assert tunnel_info.url == "http://test.ngrok.io"
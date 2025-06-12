"""Comprehensive tests for exceptions module to achieve 95%+ coverage."""

import pytest

from retunnel.core.exceptions import (
    APIError,
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ProtocolError,
    ProxyError,
    ReTunnelError,
    TunnelError,
    ValidationError,
    handle_api_error,
)


class TestExceptionHierarchy:
    """Test exception class hierarchy."""

    def test_base_exception(self):
        """Test ReTunnelError base exception."""
        err = ReTunnelError("Base error message")
        assert str(err) == "Base error message"
        assert isinstance(err, Exception)

        # Test with no message
        err2 = ReTunnelError()
        assert str(err2) == ""

    def test_connection_error(self):
        """Test ConnectionError."""
        err = ConnectionError("Connection failed")
        assert isinstance(err, ReTunnelError)
        assert isinstance(err, Exception)
        assert str(err) == "Connection failed"

        # Test inheritance
        with pytest.raises(ReTunnelError):
            raise ConnectionError("test")

    def test_authentication_error(self):
        """Test AuthenticationError."""
        err = AuthenticationError("Invalid credentials")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Invalid credentials"

        # Test catching as base exception
        try:
            raise AuthenticationError("auth failed")
        except ReTunnelError as e:
            assert str(e) == "auth failed"

    def test_tunnel_error(self):
        """Test TunnelError."""
        err = TunnelError("Tunnel creation failed")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Tunnel creation failed"

    def test_configuration_error(self):
        """Test ConfigurationError."""
        err = ConfigurationError("Invalid configuration")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Invalid configuration"

    def test_protocol_error(self):
        """Test ProtocolError."""
        err = ProtocolError("Invalid protocol message")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Invalid protocol message"

    def test_proxy_error(self):
        """Test ProxyError."""
        err = ProxyError("Proxy connection failed")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Proxy connection failed"

    def test_validation_error(self):
        """Test ValidationError."""
        err = ValidationError("Invalid input data")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Invalid input data"


class TestAPIError:
    """Test APIError class with status code."""

    def test_api_error_without_status_code(self):
        """Test APIError without status code."""
        err = APIError("API request failed")
        assert isinstance(err, ReTunnelError)
        assert str(err) == "API request failed"
        assert err.status_code is None

    def test_api_error_with_status_code(self):
        """Test APIError with status code."""
        err = APIError("Not found", status_code=404)
        assert isinstance(err, ReTunnelError)
        assert str(err) == "Not found"
        assert err.status_code == 404

    def test_api_error_various_status_codes(self):
        """Test APIError with various status codes."""
        test_cases = [
            (400, "Bad request"),
            (401, "Unauthorized"),
            (403, "Forbidden"),
            (500, "Internal server error"),
            (503, "Service unavailable"),
        ]

        for code, message in test_cases:
            err = APIError(message, status_code=code)
            assert err.status_code == code
            assert str(err) == message

    def test_api_error_inheritance(self):
        """Test APIError can be caught as ReTunnelError."""
        with pytest.raises(ReTunnelError) as exc_info:
            raise APIError("API failed", status_code=500)

        assert exc_info.value.status_code == 500
        assert str(exc_info.value) == "API failed"


class TestHandleAPIErrorDecorator:
    """Test handle_api_error decorator."""

    def test_decorator_success(self):
        """Test decorator with successful function."""

        @handle_api_error
        def successful_function(x: int, y: int) -> int:
            return x + y

        result = successful_function(2, 3)
        assert result == 5

        # Test with kwargs
        result = successful_function(x=10, y=20)
        assert result == 30

    def test_decorator_with_exception(self):
        """Test decorator catches and wraps exceptions."""

        @handle_api_error
        def failing_function():
            raise ValueError("Something went wrong")

        with pytest.raises(APIError) as exc_info:
            failing_function()

        assert "API operation failed: Something went wrong" in str(
            exc_info.value
        )
        assert exc_info.value.status_code is None

    def test_decorator_preserves_function_attributes(self):
        """Test decorator preserves function metadata."""

        @handle_api_error
        def documented_function(param: str) -> str:
            """This is a documented function."""
            return f"Result: {param}"

        # Check function metadata is preserved
        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is a documented function."

        # Function still works
        assert documented_function("test") == "Result: test"

    def test_decorator_with_various_exceptions(self):
        """Test decorator with different exception types."""

        @handle_api_error
        def multi_error_function(error_type: str):
            if error_type == "type":
                raise TypeError("Type error")
            elif error_type == "value":
                raise ValueError("Value error")
            elif error_type == "key":
                raise KeyError("key")
            return "success"

        # Test different exceptions
        with pytest.raises(APIError) as exc_info:
            multi_error_function("type")
        assert "Type error" in str(exc_info.value)

        with pytest.raises(APIError) as exc_info:
            multi_error_function("value")
        assert "Value error" in str(exc_info.value)

        with pytest.raises(APIError) as exc_info:
            multi_error_function("key")
        assert "key" in str(exc_info.value)

        # Success case
        assert multi_error_function("none") == "success"

    def test_decorator_with_class_method(self):
        """Test decorator on class methods."""

        class TestClass:
            @handle_api_error
            def method(self, value: int) -> int:
                if value < 0:
                    raise ValueError("Negative value not allowed")
                return value * 2

            @staticmethod
            @handle_api_error
            def static_method(value: int) -> int:
                if value == 0:
                    raise ZeroDivisionError("Cannot divide by zero")
                return 100 // value

        obj = TestClass()

        # Test instance method success
        assert obj.method(5) == 10

        # Test instance method failure
        with pytest.raises(APIError) as exc_info:
            obj.method(-1)
        assert "Negative value not allowed" in str(exc_info.value)

        # Test static method success
        assert TestClass.static_method(10) == 10

        # Test static method failure
        with pytest.raises(APIError) as exc_info:
            TestClass.static_method(0)
        assert "Cannot divide by zero" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_decorator_with_async_function(self):
        """Test decorator behavior with async functions."""

        # Note: The current decorator doesn't support async functions properly
        # This test documents the current behavior
        @handle_api_error
        async def async_function():
            return "async result"

        # The decorator returns the coroutine, not the result
        coro = async_function()
        assert hasattr(coro, "__await__")

        # Await the coroutine to avoid warning
        result = await coro
        assert result == "async result"


class TestExceptionUsagePatterns:
    """Test common usage patterns for exceptions."""

    def test_exception_chaining(self):
        """Test exception chaining patterns."""
        try:
            try:
                raise ValueError("Original error")
            except ValueError as e:
                raise ConnectionError("Connection failed") from e
        except ConnectionError as e:
            assert str(e) == "Connection failed"
            assert isinstance(e.__cause__, ValueError)

    def test_multiple_exception_handling(self):
        """Test handling multiple exception types."""

        def risky_operation(operation_type: str):
            if operation_type == "auth":
                raise AuthenticationError("Auth failed")
            elif operation_type == "conn":
                raise ConnectionError("Conn failed")
            elif operation_type == "tunnel":
                raise TunnelError("Tunnel failed")
            return "success"

        # Test catching specific exceptions
        with pytest.raises(AuthenticationError):
            risky_operation("auth")

        with pytest.raises(ConnectionError):
            risky_operation("conn")

        # Test catching base exception
        with pytest.raises(ReTunnelError):
            risky_operation("tunnel")

    def test_exception_with_additional_attributes(self):
        """Test adding custom attributes to exceptions."""
        err = ConnectionError("Failed to connect")
        err.retry_count = 3
        err.last_attempt = "2024-01-01"

        assert hasattr(err, "retry_count")
        assert err.retry_count == 3
        assert err.last_attempt == "2024-01-01"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

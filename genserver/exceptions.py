"""
Custom exceptions for the GenServer library.
"""

class GenServerError(Exception):
    """Base class for GenServer related exceptions."""
    pass

class GenServerTimeoutError(GenServerError, TimeoutError): # Inherit from TimeoutError for broader compatibility
    """Exception raised when a GenServer call times out."""
    pass

"""
Type hints and aliases for the GenServer library.
"""

from typing import Any, Dict, TypeVar

# Define Message as a type alias for dictionaries representing messages
Message = Dict[str, Any]

# StateType will be a generic type variable
StateType = TypeVar('StateType')

__all__ = ['Message', 'StateType'] # Ensure StateType is exported

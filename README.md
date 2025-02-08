# genserver

**Python GenServer Implementation**

[![PyPI Version](https://badge.fury.io/py/genserver.svg)](https://pypi.org/project/genserver/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Build Status](https://github.com/yourusername/genserver/actions/workflows/test.yml/badge.svg)](https://github.com/yourusername/genserver/actions/workflows/test.yml)
[![Code Coverage](https://codecov.io/gh/yourusername/genserver/branch/main/graph/badge.svg?token=YOUR_CODECOV_TOKEN)](https://codecov.io/gh/yourusername/genserver) `genserver` is a Python library that provides a robust and easy-to-use implementation of the GenServer pattern, inspired by Erlang/OTP. GenServers are a fundamental building block for building concurrent and fault-tolerant applications. They encapsulate state, handle asynchronous messages, and simplify concurrent programming.

This library aims to bring the power and elegance of the GenServer model to Python developers, enabling them to build more resilient and scalable applications.

## Features

*   **Core GenServer Pattern:** Implements the essential GenServer behaviors: state management, message handling (cast and call), and lifecycle callbacks (init, terminate).
*   **Asynchronous Messaging (Cast):** Send non-blocking messages to the GenServer for asynchronous operations and state updates.
*   **Synchronous Messaging (Call):** Send blocking messages and receive responses, enabling request-response style interactions with the GenServer.
*   **State Management:** GenServers manage their own internal state, simplifying concurrent access and data consistency.
*   **Error Handling:** Includes robust error handling within the GenServer loop and user-defined handlers, with logging and custom exception types.
*   **Timeouts:** Supports timeouts for `stop` and `call` operations, preventing indefinite blocking.
*   **Type Hinting:**  Written with type hints for improved code clarity, maintainability, and static analysis.
*   **Well-Tested:** Comes with a comprehensive suite of unit tests to ensure reliability and correctness.
*   **Production-Ready:** Designed for building robust and scalable applications.


## Installation

You can install `genserver` from PyPI using pip:

```bash
pip install genserver
````

**Note:** The PyPI package name is `genserver` to avoid namespace conflicts. When importing in Python, you will use `import genserver`.

## Usage
`python test_application.py` or
Here's a simple example demonstrating how to use `genserver` to create a counter server:

```python
import time
import logging
from genserver import GenServer, GenServerError, GenServerTimeoutError

# Configure logging (optional)
logging.basicConfig(level=logging.INFO)

class CounterServer(GenServer[int]): # State is an integer
    def init(self) -> int:
        return 0  # Initial count is 0

    def handle_cast(self, message: dict, state: int) -> int:
        action = message.get("action")
        if action == "increment":
            return state + 1
        elif action == "decrement":
            return state - 1
        else:
            return super().handle_cast(message, state) # Default unhandled cast

    def handle_call(self, message: dict, state: int) -> tuple[int, int]:
        action = message.get("action")
        if action == "get_count":
            return state, state  # Return current count
        elif action == "increment_and_get":
            new_state = state + 1
            return new_state, new_state # Increment and return new count
        else:
            raise NotImplementedError(f"Call action '{action}' not implemented: {action}")

if __name__ == "__main__":
    counter = CounterServer()
    counter.start()

    counter.cast({"action": "increment"})
    counter.cast({"action": "increment"})

    count = counter.call({"action": "get_count"})
    print(f"Current Count: {count}") # Output: Current Count: 2

    new_count = counter.call({"action": "increment_and_get"})
    print(f"Incremented Count: {new_count}") # Output: Incremented Count: 3

    counter.stop()
    print("Counter Server Stopped.")
```

To run this example, save it as a Python file (e.g., `counter_example.py`) and execute it from your terminal:

```bash
python counter_example.py
```

**Key GenServer Methods:**

  * **`start(*args, **kwargs)`:** Starts the GenServer process. Calls `init(*args, **kwargs)` in a new thread.
  * **`stop(timeout=None)`:**  Stops the GenServer gracefully, waiting for the thread to join (with optional timeout).
  * **`cast(message)`:** Sends an asynchronous message to the GenServer's mailbox (no response expected). `message` must be a dictionary.
  * **`call(message, timeout=None)`:** Sends a synchronous message and waits for a response (with optional timeout). `message` must be a dictionary.

**User-Defined Callbacks (Override in Subclasses):**

  * **`init(*args, **kwargs) -> State`:**  Initialization callback. Return the initial state.
  * **`handle_cast(message: dict, state: State) -> State`:** Handles asynchronous cast messages. Return the new state.
  * **`handle_call(message: dict, state: State) -> tuple[Any, State]`:** Handles synchronous call messages. Return a tuple containing the response and the new state.
  * **`terminate(state: State)`:** Termination callback, called when the GenServer is stopping.

## Running Tests

To run the unit tests for `genserver`, you will need to install `pytest`. If you haven't already, install it using:

```bash
pip install pytest
```

Then, navigate to the root directory of the `genserver` library (where `setup.py` is located) and run `pytest` from your terminal:

```bash
pytest
```

This will discover and run all tests located in the `tests/` directory. You should see output indicating the test results.

## Contributing

Contributions are welcome\! Please feel free to submit issues or pull requests

-----

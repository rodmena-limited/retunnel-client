"""
Core GenServer implementation.
"""

import logging
import queue
import threading
import time
import uuid
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    Generic,
    Optional,
    Tuple,
    TypeVar,
)

from genserver.exceptions import GenServerError, GenServerTimeoutError
from genserver.typing import Message, StateType

# Configure default logger for the library
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler()) # To avoid 'No handler found' warnings if not configured by user


_StateType = TypeVar('_StateType')


class GenServer(Generic[_StateType]):
    """
    Generic Server (GenServer) base class for Python.

    Implements the core GenServer behavior inspired by Erlang/OTP.
    Subclass this to create your own GenServers.

    Handles message queuing, state management, and basic lifecycle.
    """

    def __init__(self) -> None:
        """
        Initializes the GenServer with a message queue and internal state.
        """
        self._mailbox: queue.Queue[Message] = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._current_state: Optional[_StateType] = None
        self._reply_queues: Dict[uuid.UUID, queue.Queue[Any]] = {} # For handle_call replies

    def start(self, *args: Any, **kwargs: Any) -> None:
        """
        Starts the GenServer process.

        This method initializes the GenServer's state by calling `init(*args, **kwargs)`
        in a new thread and begins processing messages from the mailbox.

        Args:
            *args: Positional arguments to be passed to the `init` method.
            **kwargs: Keyword arguments to be passed to the `init` method.

        Raises:
            GenServerError: If the GenServer is already running.
        """
        if self._running:
            raise GenServerError("GenServer is already running.")
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=args, kwargs=kwargs)
        self._thread.daemon = False  # Non-daemon so threads aren't killed when main returns
        self._thread.start()

    def stop(self, timeout: Optional[float] = None) -> None:
        """
        Stops the GenServer process gracefully.

        Sends a stop command to the GenServer's mailbox and waits for the thread to join.

        Args:
            timeout: Optional timeout in seconds to wait for the GenServer to stop.
                     If None, blocks indefinitely until stopped.

        Raises:
            GenServerError: If the GenServer is not running.
            TimeoutError: If the GenServer fails to stop within the timeout.
        """
        if not self._running:
            raise GenServerError("GenServer is not running.")
        self._running = False
        self._mailbox.put(('_command', 'stop'))
        self._thread.join(timeout=timeout)
        if self._thread.is_alive(): # Check if thread is still alive after timeout
            raise TimeoutError("GenServer failed to stop within the timeout.")

    def cast(self, message: Message) -> None:
        """
        Sends an asynchronous message (cast) to the GenServer's mailbox.

        The GenServer will process this message in its message processing loop.
        No response is expected for cast messages.

        Args:
            message: The message to be sent. Must be a dictionary.

        Raises:
            GenServerError: If the GenServer is not running or message is not a dictionary.
        """
        if not self._running:
            raise GenServerError("Cannot cast message to a stopped GenServer.")
        if not isinstance(message, dict): # Enforce message as dictionary for structure
            raise GenServerError("Message must be a dictionary.")
        self._mailbox.put(message)

    def call(self, message: Message, timeout: Optional[float] = None) -> Any:
        """
        Sends a synchronous message (call) to the GenServer and waits for a response.

        This method blocks until the GenServer replies or a timeout occurs.

        Args:
            message: The message to be sent. Must be a dictionary.
            timeout: Optional timeout in seconds to wait for a response.
                     If None, blocks indefinitely.

        Returns:
            Any: The response from the GenServer.

        Raises:
            GenServerError: If the GenServer is not running or message is not a dictionary.
            GenServerTimeoutError: If no response is received within the timeout.
        """
        if not self._running:
            raise GenServerError("Cannot call a stopped GenServer.")
        if not isinstance(message, dict): # Enforce message as dictionary for structure
            raise GenServerError("Message must be a dictionary.")

        correlation_id = uuid.uuid4()
        reply_queue: queue.Queue[Any] = queue.Queue()
        self._reply_queues[correlation_id] = reply_queue
        call_message = ('_call', message, correlation_id) # Wrap message for _loop to handle
        self._mailbox.put(call_message)

        try:
            response = reply_queue.get(timeout=timeout) # Wait for response with timeout
            return response
        except queue.Empty:
            del self._reply_queues[correlation_id] # Clean up
            raise GenServerTimeoutError(f"No response received for call within timeout: {timeout} seconds.")
        finally:
            if correlation_id in self._reply_queues: # Ensure cleanup even if timeout didn't happen via queue.Empty
                del self._reply_queues[correlation_id]

    def _reply(self, correlation_id: uuid.UUID, response: Any) -> None:
        """
        Internal method to send a reply to a 'call' message.

        Used by handle_call to send the response back to the caller.

        Args:
            correlation_id: The UUID of the call message to respond to.
            response: The response data.
        """
        reply_queue = self._reply_queues.get(correlation_id)
        if reply_queue:
            reply_queue.put(response)
        else:
            logger.warning(f"Reply queue not found for correlation ID: {correlation_id}. "
                           f"This might indicate a programming error or timeout.")

    def _loop(self, *args: Any, **kwargs: Any) -> None:
        """
        The main message processing loop of the GenServer.

        - Initializes state by calling `init`.
        - Continuously retrieves messages from the mailbox.
        - Handles different message types ('_command', '_call', cast messages).
        - Calls user-defined handler methods (`handle_cast`, `handle_call`).
        - Handles exceptions within handlers and logs them.
        - Calls `terminate` before exiting the loop.
        """
        try:
            self._current_state = self.init(*args, **kwargs)
        except Exception as e:
            logger.exception(f"GenServer init failed: {e}")
            self._running = False # Stop if init fails, prevent further processing
            return # Exit loop immediately

        while self._running:
            try:
                msg = self._mailbox.get(timeout=0.1) # Block with timeout for responsiveness
                if not msg: # Spurious wakeup?
                    continue

                if isinstance(msg, tuple): # Internal commands or calls
                    command = msg[0]
                    if command == '_command':
                        internal_command = msg[1]
                        if internal_command == 'stop':
                            self._running = False # Graceful stop
                            break # Exit loop
                    elif command == '_call':
                        _, call_message, correlation_id = msg # Unpack call message
                        try:
                            response, next_state = self.handle_call(call_message, self._current_state)
                            self._current_state = next_state
                            self._reply(correlation_id, response) # Send response back to caller
                        except Exception as e:
                            logger.exception(f"GenServer handle_call error for message: {call_message}")
                            self._reply(correlation_id, GenServerError(f"handle_call failed: {e}")) # Reply with error
                    else:
                        logger.warning(f"Unknown internal message type: {command}")

                elif isinstance(msg, dict): # Cast messages (user-defined)
                    try:
                        next_state = self.handle_cast(msg, self._current_state)
                        self._current_state = next_state
                    except Exception as e:
                        logger.exception(f"GenServer handle_cast error for message: {msg}")

                else:
                    logger.warning(f"Unknown message type received: {msg}")


            except queue.Empty: # Timeout, just continue loop to check self._running
                pass # No message in queue, non-blocking timeout used

            except Exception as main_loop_err: # Catch any unexpected errors in the loop
                logger.exception(f"GenServer main loop error: {main_loop_err}")
                self._running = False # Stop on unhandled loop errors to prevent indefinite issues
                break # Ensure loop exit

        try:
            self.terminate(self._current_state) # Call terminate before thread exits
        except Exception as e_term:
            logger.exception(f"GenServer terminate error: {e_term}")


    # --- User-defined callback methods to be overridden in subclasses ---

    def init(self, *args: Any, **kwargs: Any) -> _StateType:
        """
        Initialization callback.

        Called when the GenServer starts. Should return the initial state.
        Override in subclass to define initial state and setup.

        Args:
            *args: Arguments passed from `start`.
            **kwargs: Keyword arguments passed from `start`.

        Returns:
            State: The initial state of the GenServer.
        """
        raise NotImplementedError("init method must be implemented in subclass.")

    def handle_cast(self, message: Message, state: _StateType) -> _StateType:
        """
        Handles asynchronous cast messages.

        Override in subclass to define how to handle cast messages.

        Args:
            message: The cast message (dictionary).
            state: The current state of the GenServer.

        Returns:
            State: The new state of the GenServer after handling the message.
                   Return the same state if no state change is needed.
        """
        logger.warning(f"Unhandled cast message: {message}. Override handle_cast in subclass to handle it.")
        return state # Default: return same state

    def handle_call(self, message: Message, state: _StateType) -> Tuple[Any, _StateType]:
        """
        Handles synchronous call messages.

        Override in subclass to define how to handle call messages.

        Args:
            message: The call message (dictionary).
            state: The current state of the GenServer.

        Returns:
            Tuple[Any, State]: A tuple containing:
                - The response to the call message.
                - The new state of the GenServer after handling the message.
                  Return the same state if no state change is needed.

        Raises:
            NotImplementedError: If not overridden in subclass.
        """
        raise NotImplementedError("handle_call method must be implemented in subclass to handle calls.")

    def terminate(self, state: _StateType) -> None:
        """
        Termination callback.

        Called when the GenServer is about to stop.
        Override in subclass to perform cleanup or final actions before shutdown.

        Args:
            state: The current state of the GenServer.
        """
        logger.info("GenServer is terminating.")
        pass # Default: do nothing on terminate

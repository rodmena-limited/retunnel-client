import logging
import time
import unittest

from genserver import GenServer, GenServerError, GenServerTimeoutError

# Configure logging for tests (optional, but helpful for debugging)
logging.basicConfig(level=logging.INFO)


class CounterServer(GenServer[int]): # Example with state as int
    def init(self) -> int:
        return 0 # Initial state is 0

    def handle_cast(self, message: dict, state: int) -> int:
        action = message.get("action")
        if action == "increment":
            return state + 1
        elif action == "decrement":
            return state - 1
        else:
            return super().handle_cast(message, state) # Default unhandled cast behavior

    def handle_call(self, message: dict, state: int) -> tuple[int, int]:
        action = message.get("action")
        if action == "get_count":
            return state, state # Response is current count, state remains same
        elif action == "increment_and_get":
            new_state = state + 1
            return new_state, new_state # Response is new count, state is updated
        else:
            raise NotImplementedError(f"Call action '{action}' not implemented.")


class TestGenServer(unittest.TestCase):

    def test_start_stop(self):
        server = CounterServer()
        server.start()
        self.assertTrue(server._running)
        server.stop()
        self.assertFalse(server._running)

    def test_double_start_stop(self):
        server = CounterServer()
        server.start()
        with self.assertRaises(GenServerError):
            server.start() # Should raise error if already running
        server.stop()
        with self.assertRaises(GenServerError):
            server.stop() # Should raise error if already stopped

    def test_cast_increment(self):
        server = CounterServer()
        server.start()
        server.cast({"action": "increment"})
        time.sleep(0.1) # Allow time for message processing
        count = server.call({"action": "get_count"})
        self.assertEqual(count, 1)
        server.stop()

    def test_cast_decrement(self):
        server = CounterServer()
        server.start()
        server.cast({"action": "decrement"})
        time.sleep(0.1)
        count = server.call({"action": "get_count"})
        self.assertEqual(count, -1)
        server.stop()

    def test_call_get_count(self):
        server = CounterServer()
        server.start()
        count = server.call({"action": "get_count"})
        self.assertEqual(count, 0)
        server.stop()

    def test_call_increment_and_get(self):
        server = CounterServer()
        server.start()
        new_count = server.call({"action": "increment_and_get"})
        self.assertEqual(new_count, 1)
        count = server.call({"action": "get_count"}) # Verify state is updated
        self.assertEqual(count, 1)
        server.stop()

    def test_call_timeout(self):
        class TimeoutServer(GenServer[None]):
            def init(self):
                return None
            def handle_call(self, message, state):
                time.sleep(1) # Simulate long processing
                return "response", state

        server = TimeoutServer()
        server.start()
        start_time = time.time()
        with self.assertRaises(GenServerTimeoutError):
            server.call({"action": "test"}, timeout=0.1) # Short timeout
        elapsed_time = time.time() - start_time
        self.assertLess(elapsed_time, 0.5) # Should be much less than 1 sec sleep in handler
        server.stop()

    def test_terminate_callback(self):
        class TerminateTestServer(GenServer[list]):
            def init(self):
                return []
            def terminate(self, state):
                state.append("terminated") # Modify state on terminate

        server = TerminateTestServer()
        server.start()
        server.stop()
        self.assertEqual(server._current_state, ["terminated"]) # Check state after stop

    def test_init_exception_handling(self):
        class InitErrorServer(GenServer[None]):
            def init(self):
                raise ValueError("Init failed") # Simulate init failure
            def handle_cast(self, message, state):
                return state
            def handle_call(self, message, state):
                return "response", state

        server = InitErrorServer()
        server.start() # Start should not raise, but GenServer should stop internally
        time.sleep(0.1) # Give time for thread to run and stop
        self.assertFalse(server._running) # Should not be running after init failure
        with self.assertRaises(GenServerError): # Check cast and call fail
            server.cast({"action": "test"})
        with self.assertRaises(GenServerError):
            server.call({"action": "test"})

    def test_handler_exception_handling(self):
            class HandlerErrorServer(GenServer[None]):
                def init(self):
                    return None
                def handle_cast(self, message, state):
                    if message.get("action") == "error_cast":
                        raise TypeError("Cast handler error")
                    return state
                def handle_call(self, message, state):
                    if message.get("action") == "error_call":
                        raise ValueError("Call handler error")
                    return "response", state

            server = HandlerErrorServer()
            server.start()

            # Cast error should be logged, but GenServer should continue running
            server.cast({"action": "error_cast"})
            time.sleep(0.1) # Allow time for error to be logged and handled
            self.assertTrue(server._running) # Still running after cast error

            # Call error should also be handled, and exception returned to caller via call
            response = server.call({"action": "error_call"}) # Capture the returned response
            self.assertIsInstance(response, GenServerError) # Assert response is GenServerError
            with self.assertRaises(GenServerError): # Now assert that *raising* this response raises GenServerError
                raise response

            server.stop()

if __name__ == '__main__':
    unittest.main()

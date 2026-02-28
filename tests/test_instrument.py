"""test_instrument.py - Unit and integration tests for the @trace decorator.

Covers:
    - @trace writes >> entry line to buffer
    - @trace writes << return line to buffer on normal exit
    - @trace writes !! exception line and re-raises on failure
    - Arguments are captured correctly (positional + keyword)
    - Return value is captured in << line
    - Nested @trace calls produce correct indentation hierarchy
    - Exception type and message appear in !! line
    - Buffer is shared with TraceLogHandler (same get_buffer() instance)
    - Integration scenario B: addHandler + @trace produces full DSL tree
"""

import io
import logging

import pytest

from tracelog.buffer import RingBuffer
from tracelog.context import ContextManager
from tracelog.handler import TraceLogHandler, get_buffer, _buffer_var
from tracelog.instrument import trace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_context():
    """Clear the buffer and reset depth for test isolation."""
    get_buffer().clear()
    ContextManager._depth.set(0)


# ---------------------------------------------------------------------------
# @trace — entry line
# ---------------------------------------------------------------------------


class TestTraceEntryLine:
    def setup_method(self):
        _reset_context()

    def test_trace_writes_entry_line_to_buffer(self):
        """@trace pushes a '>> funcname(...)' line to the buffer on entry."""

        @trace
        def my_func(x):
            return x

        my_func(42)
        entries = get_buffer().snapshot()
        assert any(">>" in e.dsl_line and "my_func" in e.dsl_line for e in entries)

    def test_trace_entry_includes_argument_name_and_value(self):
        """Entry line captures keyword argument names and their values."""

        @trace
        def add(a, b):
            return a + b

        add(3, 5)
        entry_lines = [e.dsl_line for e in get_buffer().snapshot()]
        entry = next(l for l in entry_lines if ">>" in l)
        assert "a=3" in entry
        assert "b=5" in entry

    def test_trace_entry_qualname_is_used(self):
        """Entry line uses __qualname__ (e.g. 'Class.method') not just __name__."""

        class Calc:
            @trace
            def multiply(self, x, y):
                return x * y

        Calc().multiply(2, 3)
        entry_lines = [e.dsl_line for e in get_buffer().snapshot()]
        assert any("Calc.multiply" in l for l in entry_lines)


# ---------------------------------------------------------------------------
# @trace — return line
# ---------------------------------------------------------------------------


class TestTraceReturnLine:
    def setup_method(self):
        _reset_context()

    def test_trace_writes_return_line_on_success(self):
        """@trace pushes a '<< value' line after normal function return."""

        @trace
        def square(n):
            return n * n

        square(4)
        lines = [e.dsl_line for e in get_buffer().snapshot()]
        assert any("<<" in l and "16" in l for l in lines)

    def test_trace_return_value_is_repr(self):
        """Return value in << line is the repr() of the actual return value."""

        @trace
        def greet(name):
            return f"hello {name}"

        greet("world")
        lines = [e.dsl_line for e in get_buffer().snapshot()]
        ret_line = next(l for l in lines if "<<" in l)
        assert "'hello world'" in ret_line


# ---------------------------------------------------------------------------
# @trace — exception line
# ---------------------------------------------------------------------------


class TestTraceExceptionLine:
    def setup_method(self):
        _reset_context()

    def test_trace_writes_exception_line_on_failure(self):
        """@trace pushes a '!! ExcType: message' line when the function raises."""

        @trace
        def fail():
            raise RuntimeError("something broke")

        with pytest.raises(RuntimeError):
            fail()

        lines = [e.dsl_line for e in get_buffer().snapshot()]
        assert any("!!" in l and "RuntimeError" in l for l in lines)

    def test_trace_reraises_exception_unchanged(self):
        """@trace never swallows exceptions — the original exception propagates."""

        @trace
        def explode():
            raise ValueError("original message")

        with pytest.raises(ValueError, match="original message"):
            explode()

    def test_trace_reraises_exact_exception_type(self):
        """The re-raised exception is the same type as the original."""

        @trace
        def raise_type_error():
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            raise_type_error()

    def test_trace_exception_message_in_dsl_line(self):
        """The exception message appears in the !! DSL line."""

        @trace
        def blow_up():
            raise KeyError("missing_key")

        with pytest.raises(KeyError):
            blow_up()

        lines = [e.dsl_line for e in get_buffer().snapshot()]
        exc_line = next(l for l in lines if "!!" in l)
        assert "missing_key" in exc_line


# ---------------------------------------------------------------------------
# @trace — indentation (nested calls)
# ---------------------------------------------------------------------------


class TestTraceIndentation:
    def setup_method(self):
        _reset_context()

    def test_trace_nested_calls_produce_increasing_indentation(self):
        """Nested @trace calls indent inner calls relative to outer calls."""

        @trace
        def inner():
            return "inner result"

        @trace
        def outer():
            return inner()

        outer()
        lines = [e.dsl_line for e in get_buffer().snapshot()]

        outer_entry = next(l for l in lines if "outer" in l and ">>" in l)
        inner_entry = next(l for l in lines if "inner" in l and ">>" in l)

        outer_indent = len(outer_entry) - len(outer_entry.lstrip())
        inner_indent = len(inner_entry) - len(inner_entry.lstrip())
        assert inner_indent > outer_indent

    def test_trace_depth_restored_to_zero_after_call(self):
        """After a top-level @trace call completes, depth returns to 0."""

        @trace
        def top():
            return 1

        top()
        assert ContextManager._depth.get() == 0

    def test_trace_depth_restored_to_zero_after_exception(self):
        """Depth is restored to 0 even when an exception is raised inside @trace."""

        @trace
        def raises():
            raise NotImplementedError

        with pytest.raises(NotImplementedError):
            raises()

        assert ContextManager._depth.get() == 0


# ---------------------------------------------------------------------------
# Shared buffer with TraceLogHandler
# ---------------------------------------------------------------------------


class TestTraceSharedBuffer:
    def setup_method(self):
        _reset_context()

    def test_trace_and_handler_share_same_buffer(self):
        """@trace and TraceLogHandler write to the same context-local buffer."""
        stream = io.StringIO()
        handler = TraceLogHandler(capacity=50, dump_stream=stream)
        logger = logging.getLogger("shared_buffer_test")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.addHandler(handler)

        @trace
        def do_work():
            logger.info("working")
            return "done"

        try:
            _reset_context()
            do_work()
            # Both >> / << from @trace and .. [INFO] from logger are in buffer
            entries = get_buffer().snapshot()
            dsl_lines = [e.dsl_line for e in entries]
            assert any(">>" in l for l in dsl_lines)
            assert any("INFO" in l for l in dsl_lines)
        finally:
            logger.removeHandler(handler)


# ---------------------------------------------------------------------------
# Integration — Scenario B: addHandler + @trace
# ---------------------------------------------------------------------------


class TestIntegrationHandlerAndTrace:
    def test_integration_scenario_b_full_dsl_tree_on_error(self):
        """Scenario B: addHandler + @trace produces nested DSL tree in error dump."""
        stream = io.StringIO()
        logger = logging.getLogger("scenario_b_test")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        handler = TraceLogHandler(capacity=50, dump_stream=stream)
        logger.addHandler(handler)

        @trace
        def get_balance(user_id):
            logger.debug(f"querying balance for user {user_id}")
            return 3000

        @trace
        def pay(user_id, amount):
            logger.info(f"payment attempt: user={user_id}, amount={amount}")
            balance = get_balance(user_id)
            if balance < amount:
                logger.error("insufficient funds")
                raise ValueError("InsufficientFunds")

        try:
            _reset_context()
            pay(1, 5000)
        except ValueError:
            pass
        finally:
            logger.removeHandler(handler)

        output = stream.getvalue()
        assert "DUMP START" in output
        assert ">>" in output  # @trace entry lines present
        assert "<<" in output  # @trace return lines present
        assert "!!" in output  # exception / error lines present
        assert "payment attempt" in output
        assert "querying balance" in output

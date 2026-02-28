"""test_handler.py - Unit and integration tests for TraceLogHandler.

Covers:
    - get_buffer() returns same instance within a context
    - get_buffer() creates independent buffers per thread
    - emit() pushes DSL line to buffer for sub-ERROR records
    - emit() triggers _dump() on ERROR and above
    - _to_dsl() produces correct prefix for each log level
    - _to_dsl() includes exception class name when exc_info is present
    - _to_dsl() applies correct indentation based on call depth
    - _dump() writes header, entries, and footer to stream
    - _dump() clears buffer via flash() after writing
    - Integration scenario A: handler-only (no @trace) dumps on ERROR
"""

import io
import logging
import threading

import pytest

from tracelog.handler import TraceLogHandler, get_buffer, _buffer_var
from tracelog.context import ContextManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_record(
    msg: str,
    level: int = logging.INFO,
    exc_info=None,
    name: str = "test",
) -> logging.LogRecord:
    """Create a minimal LogRecord for testing."""
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    return record


def _fresh_handler(stream=None) -> TraceLogHandler:
    """Return a TraceLogHandler with an in-memory stream and cleared buffer."""
    if stream is None:
        stream = io.StringIO()
    # Ensure each test starts with a clean buffer (token bound to current thread)
    try:
        get_buffer().clear()
    except Exception:
        pass
    return TraceLogHandler(capacity=50, dump_stream=stream)


# ---------------------------------------------------------------------------
# get_buffer()
# ---------------------------------------------------------------------------


class TestGetBuffer:
    def setup_method(self):
        # Reset the ContextVar for isolation in sequential tests
        _buffer_var.set(get_buffer())
        get_buffer().clear()

    def test_get_buffer_returns_ring_buffer(self):
        """get_buffer() returns a RingBuffer instance."""
        from tracelog.buffer import RingBuffer

        assert isinstance(get_buffer(), RingBuffer)

    def test_get_buffer_same_instance_within_context(self):
        """Calling get_buffer() twice in the same context returns the same object."""
        buf1 = get_buffer()
        buf2 = get_buffer()
        assert buf1 is buf2

    def test_get_buffer_isolated_per_thread(self):
        """Each thread gets its own independent RingBuffer."""
        buffers = {}

        def worker(name: str):
            buf = get_buffer()
            buf.push(f"entry from {name}")
            buffers[name] = buf

        t1 = threading.Thread(target=worker, args=("t1",))
        t2 = threading.Thread(target=worker, args=("t2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert buffers["t1"] is not buffers["t2"]
        # t1's buffer has only its own entry
        assert all("t1" in e.dsl_line for e in buffers["t1"].snapshot())
        assert all("t2" in e.dsl_line for e in buffers["t2"].snapshot())


# ---------------------------------------------------------------------------
# _to_dsl()
# ---------------------------------------------------------------------------


class TestToDsl:
    def setup_method(self):
        self.stream = io.StringIO()
        self.handler = _fresh_handler(self.stream)
        ContextManager._depth.set(0)

    def test_to_dsl_info_uses_dot_dot_info_prefix(self):
        """INFO records produce '.. [INFO] message' prefix."""
        record = _make_record("hello", logging.INFO)
        dsl = self.handler._to_dsl(record)
        assert dsl == ".. [INFO] hello"

    def test_to_dsl_debug_uses_dot_dot_debug_prefix(self):
        """DEBUG records produce '.. [DEBUG] message' prefix."""
        record = _make_record("debug msg", logging.DEBUG)
        dsl = self.handler._to_dsl(record)
        assert dsl == ".. [DEBUG] debug msg"

    def test_to_dsl_warning_uses_dot_dot_prefix(self):
        """WARNING records produce '.. message' (no level label)."""
        record = _make_record("watch out", logging.WARNING)
        dsl = self.handler._to_dsl(record)
        assert dsl == ".. watch out"

    def test_to_dsl_error_uses_bang_bang_prefix(self):
        """ERROR records produce '!! message' prefix."""
        record = _make_record("bad news", logging.ERROR)
        dsl = self.handler._to_dsl(record)
        assert dsl == "!! bad news"

    def test_to_dsl_critical_uses_bang_bang_prefix(self):
        """CRITICAL records also produce '!! message' prefix."""
        record = _make_record("critical fail", logging.CRITICAL)
        dsl = self.handler._to_dsl(record)
        assert dsl == "!! critical fail"

    def test_to_dsl_applies_indentation_based_on_depth(self):
        """DSL line is indented by 2 spaces per depth level."""
        ContextManager._depth.set(2)
        record = _make_record("deep msg", logging.INFO)
        dsl = self.handler._to_dsl(record)
        assert dsl.startswith("    ")  # 4 spaces = depth 2

    def test_to_dsl_includes_exception_class_name_when_exc_info_present(self):
        """When exc_info is set, the exception class name is prepended."""
        try:
            raise ValueError("bad value")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = _make_record("caught it", logging.ERROR, exc_info=exc_info)
        dsl = self.handler._to_dsl(record)
        assert "ValueError" in dsl


# ---------------------------------------------------------------------------
# emit()
# ---------------------------------------------------------------------------


class TestEmit:
    def setup_method(self):
        self.stream = io.StringIO()
        self.handler = _fresh_handler(self.stream)
        ContextManager._depth.set(0)
        get_buffer().clear()

    def test_emit_info_pushes_to_buffer_without_dumping(self):
        """emit() with INFO level buffers the entry but produces no dump output."""
        record = _make_record("just info", logging.INFO)
        self.handler.emit(record)

        assert len(get_buffer()) == 1
        output = self.stream.getvalue()
        assert output == ""

    def test_emit_error_triggers_dump_to_stream(self):
        """emit() with ERROR level writes DUMP START/END markers to the stream."""
        record = _make_record("something broke", logging.ERROR)
        self.handler.emit(record)

        output = self.stream.getvalue()
        assert "DUMP START" in output
        assert "DUMP END" in output

    def test_emit_error_clears_buffer_after_dump(self):
        """After an ERROR emit, the buffer is empty (flash was called)."""
        self.handler.emit(_make_record("step 1", logging.INFO))
        self.handler.emit(_make_record("step 2", logging.INFO))
        self.handler.emit(_make_record("boom", logging.ERROR))

        assert len(get_buffer()) == 0

    def test_emit_includes_prior_info_entries_in_dump(self):
        """ERROR dump contains all buffered INFO lines recorded before the error."""
        self.handler.emit(_make_record("step A", logging.INFO))
        self.handler.emit(_make_record("step B", logging.DEBUG))
        self.handler.emit(_make_record("kaboom", logging.ERROR))

        output = self.stream.getvalue()
        assert "step A" in output
        assert "step B" in output
        assert "kaboom" in output


# ---------------------------------------------------------------------------
# Integration — Scenario A: handler-only, no @trace
# ---------------------------------------------------------------------------


class TestIntegrationHandlerOnly:
    def test_integration_handler_only_dumps_on_error(self):
        """Scenario A: addHandler alone captures INFO/DEBUG and dumps on ERROR."""
        stream = io.StringIO()
        logger = logging.getLogger("scenario_a_test")
        logger.setLevel(logging.DEBUG)
        # Remove any pre-existing handlers to avoid interference
        logger.handlers.clear()
        handler = TraceLogHandler(capacity=50, dump_stream=stream)
        logger.addHandler(handler)

        try:
            get_buffer().clear()
            logger.info("Payment attempt: user_id=1")
            logger.debug("Querying DB")
            logger.error("Insufficient funds")
        finally:
            logger.removeHandler(handler)

        output = stream.getvalue()
        assert "DUMP START" in output
        assert "Payment attempt" in output
        assert "Querying DB" in output
        assert "Insufficient funds" in output

    def test_integration_buffer_is_empty_after_dump(self):
        """After an error dump, the buffer is cleared and ready for the next run."""
        stream = io.StringIO()
        logger = logging.getLogger("scenario_a_empty_test")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        handler = TraceLogHandler(capacity=50, dump_stream=stream)
        logger.addHandler(handler)

        try:
            get_buffer().clear()
            logger.info("pre-error info")
            logger.error("error occurs")
            # After error, buffer should be empty
            post_error_length = len(get_buffer())
        finally:
            logger.removeHandler(handler)

        assert post_error_length == 0

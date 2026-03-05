import pytest
import logging
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from tracelog import TraceLogHandler, trace
from tracelog.handler import get_buffer
from tracelog.context import ContextManager


@pytest.fixture
def stream():
    return StringIO()


@pytest.fixture
def handler(stream):
    h = TraceLogHandler()
    # Replace default exporter with a StreamExporter to capture dumps
    from tracelog.exporter import StreamExporter

    h._exporter = StreamExporter(stream=stream, show_timestamp=False)

    logger = logging.getLogger("test_span_propagation")
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.propagate = False
    logger.addHandler(h)

    return logger, stream


def test_decorator_generates_span_id_and_restores_parent():
    """Test that @trace creates a new span_id, sets parent, and correctly restores after exit."""

    ctx = ContextManager()

    # Clear any residual context from previous tests
    ctx._trace_id.set("")
    ctx._parent_span_id.set("")

    # 1. Start with no span
    initial_span = ctx._trace_id.get()
    assert initial_span == ""

    @trace
    def inner_function():
        return ctx.get_span_id(), ctx.get_parent_span_id()

    @trace
    def outer_function():
        outer_span = ctx.get_span_id()
        outer_parent = ctx.get_parent_span_id()

        # Inner should get its own span_id and set outer's span_id as its parent
        inner_span, inner_parent = inner_function()

        return outer_span, outer_parent, inner_span, inner_parent

    outer_span, outer_parent, inner_span, inner_parent = outer_function()

    # 2. Assert relationships
    assert outer_span != ""
    assert outer_parent is None  # Top level trace has no parent

    assert inner_span != ""
    assert inner_span != outer_span  # Inner gets a fresh span
    assert inner_parent == outer_span  # Inner's parent is outer

    # 3. Assert restoration after exit
    assert ctx._trace_id.get() == initial_span
    assert ctx._parent_span_id.get() == ""


def test_span_id_in_dump_header(handler):
    """Test that DUMP START header includes the correct span_id and parent_span_id."""
    logger, stream = handler
    ctx = ContextManager()

    # Manually set a root span id so @trace will pick it up as parent.
    root_id = "root1234"
    ctx._trace_id.set(root_id)

    @trace
    def crashing_func():
        logger.error("simulated crash")
        return ctx.get_span_id()

    span_id = crashing_func()

    dump_output = stream.getvalue()

    # Check if header matches format: === [TraceLog] DUMP START (span_id: {span_id}, parent_span_id: root1234) ===
    expected_header = (
        f"=== [TraceLog] DUMP START (span_id: {span_id}, parent_span_id: {root_id}) ==="
    )
    assert expected_header in dump_output


def test_threadpool_worker_leak_prevention(handler):
    """
    CRITICAL TEST: Ensure recycled ThreadPoolExecutor workers do not leak
    buffer contents or span contexts across entirely separate tasks.

    In Phase 1, workers reusing contextvars leaked buffer contents.
    Let's see if the fix/design works.
    """
    logger, stream = handler
    ctx = ContextManager()

    # We use max_workers=1 to force thread reuse.
    with ThreadPoolExecutor(max_workers=1) as executor:

        @trace
        def task_one():
            # Add a distinct log message that should NOT bleed into task two
            logger.info("Message from Task One")
            # We don't error, so it shouldn't dump. But it's in the buffer.
            return ctx.get_span_id(), get_buffer().snapshot()

        @trace
        def task_two():
            # This task errors out and dumps its buffer
            logger.error("Crash in Task Two")
            return ctx.get_span_id(), get_buffer().snapshot()

        # Execute sequentially on the single worker
        future1 = executor.submit(task_one)
        span_one, buffer_one_items = future1.result()

        future2 = executor.submit(task_two)
        span_two, buffer_two_items = future2.result()

    # 1. Spans must be different
    assert span_one != span_two

    # 2. Check the raw buffer objects inside the worker
    # At the end of task_two (right before error flush), the buffer shouldn't contain "Task One" log.
    # Note: wait, but TraceLogHandler calls buffer.clear() inside flash(),
    # so error() actually clears the buffer.
    # Let's inspect the actual dumped output.
    dump_output = stream.getvalue()

    # If buffer was contaminated, "Message from Task One" would appear in the DUMP.
    # Because @trace wraps the function, if the worker leaked context, the buffer
    # would still hold it.
    assert "Message from Task One" not in dump_output
    assert "Crash in Task Two" in dump_output

import pytest
import logging
import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

from tracelog import TraceLogHandler, trace
from tracelog.handler import get_buffer
from tracelog.context import ContextManager


def _parse_dump(output: str) -> dict:
    lines = [line for line in output.splitlines() if line.strip()]
    assert len(lines) == 1
    return json.loads(lines[0])


@pytest.fixture
def stream():
    return StringIO()


@pytest.fixture
def handler(stream):
    ctx = ContextManager()
    ctx._trace_id.set("")
    ctx._span_id.set("")
    ctx._parent_span_id.set("")
    ctx._depth.set(0)
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
    ctx._span_id.set("")
    ctx._parent_span_id.set("")

    # 1. Start with no span
    initial_span = ctx._span_id.get()
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
    assert ctx._span_id.get() == initial_span
    assert ctx._parent_span_id.get() == ""


def test_span_id_in_json_dump(handler):
    """Test that the JSON dump includes the correct span_id and parent_span_id."""
    logger, stream = handler
    ctx = ContextManager()

    # Manually set a root span id so @trace will pick it up as parent.
    root_id = "root1234"
    ctx._trace_id.set(root_id)
    ctx._span_id.set("")

    @trace
    def crashing_func():
        logger.error("simulated crash")
        return ctx.get_span_id()

    span_id = crashing_func()

    payload = _parse_dump(stream.getvalue())
    assert payload["span_id"] == span_id
    assert payload["trace_id"] == root_id
    assert payload["parent_span_id"] is None


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
    payload = _parse_dump(dump_output)

    # If buffer was contaminated, "Message from Task One" would appear in the DUMP.
    # Because @trace wraps the function, if the worker leaked context, the buffer
    # would still hold it.
    assert not any("Message from Task One" in line for line in payload["dsl_lines"])
    assert any("Crash in Task Two" in line for line in payload["dsl_lines"])


def test_propagated_parent_span_id_is_preserved_in_worker_dump(handler):
    """A worker started with a propagated parent span should export that linkage."""
    logger, stream = handler
    ctx = ContextManager()

    root_trace_id = "trace1234"
    parent_span_id = "parent567"

    def worker():
        child_ctx = ContextManager()
        child_ctx.set_trace_id(root_trace_id)
        child_ctx.set_span_id("")
        child_ctx.set_parent_span_id(parent_span_id)
        child_ctx._depth.set(0)

        @trace
        def send_email():
            logger.error("worker failed")

        send_email()

    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(worker).result()

    payload = _parse_dump(stream.getvalue())
    assert payload["trace_id"] == root_trace_id
    assert payload["parent_span_id"] == parent_span_id

"""handler.py - Core integration layer for TraceLog.

This module provides TraceLogHandler, a logging.Handler subclass that acts as
the primary integration point between the Python standard logging infrastructure
and TraceLog's Trace-DSL buffering and dump mechanism.

Design contract:
    - Developers add ONE line to their existing logging setup: addHandler().
    - All log records flow through emit(), which appends Trace-DSL entries to
      a per-context circular buffer.
    - On ERROR or above, the entire buffer is serialized to Trace-DSL and dumped
      to a stream (default: stderr), then the buffer is cleared for the next run.

Typical usage:
    import logging
    from tracelog import TraceLogHandler

    logging.getLogger().addHandler(TraceLogHandler())
    logger = logging.getLogger(__name__)

    logger.info("Starting job")    # buffered silently
    logger.error("Job failed")     # triggers full Trace-DSL dump
"""

import logging
import sys
from contextvars import ContextVar

from .buffer import RingBuffer
from .context import ContextManager

# ---------------------------------------------------------------------------
# Module-level context variable for per-thread / per-coroutine buffer isolation.
#
# Using contextvars.ContextVar instead of threading.local ensures correctness
# in both multi-threaded *and* async (asyncio / trio) execution models.
# Each thread or asyncio Task gets its own independent RingBuffer instance.
# ---------------------------------------------------------------------------
_buffer_var: ContextVar[RingBuffer] = ContextVar("tracelog_buffer")


def get_buffer(capacity: int = 200) -> RingBuffer:
    """Return the RingBuffer bound to the current execution context.

    On first access within a thread or asyncio Task, a new RingBuffer is
    created and bound via the ContextVar so that subsequent calls in the same
    context always return the same instance.

    This function is the **single source of truth** for buffer access. Both
    TraceLogHandler and the @trace decorator call this to ensure they write
    into the same buffer within one execution context.

    Args:
        capacity: Maximum number of log entries the buffer can hold before
            the oldest entries are automatically evicted. Defaults to 200.

    Returns:
        The RingBuffer associated with the current execution context.

    Example:
        >>> buf = get_buffer()
        >>> buf.push(">> my_func(x=1)", level=logging.DEBUG)
        >>> len(buf)
        1
    """
    try:
        return _buffer_var.get()
    except LookupError:
        buf = RingBuffer(capacity=capacity)
        _buffer_var.set(buf)
        return buf


class TraceLogHandler(logging.Handler):
    """A logging.Handler that buffers records as Trace-DSL and dumps on error.

    TraceLogHandler integrates TraceLog into the standard Python logging pipeline
    without requiring any changes to existing application code. Developers simply
    attach this handler to their root (or any) logger.

    Buffering strategy:
        Every log record received by emit() is converted to a Trace-DSL line and
        appended to the context-local RingBuffer. Records below ERROR level are
        held in the buffer silently. When an ERROR (or CRITICAL) record arrives,
        the complete buffer — representing the full execution narrative up to that
        point — is serialized and written to ``dump_stream``, then cleared.

    Thread-safety:
        The parent class ``logging.Handler`` wraps emit() with acquire()/release()
        around a threading.RLock, so concurrent calls are serialized automatically.
        Buffer isolation across threads is handled by the ContextVar in get_buffer().

    Attributes:
        _capacity (int): Buffer capacity passed to RingBuffer on creation.
        _dump_stream: File-like object where DSL dumps are written.
        _ctx (ContextManager): Provides the current call-stack depth for DSL indent.

    Example:
        >>> import logging
        >>> from tracelog import TraceLogHandler
        >>> logging.getLogger().addHandler(TraceLogHandler())
        >>> logger = logging.getLogger("myapp")
        >>> logger.info("step one")   # buffered
        >>> logger.error("oh no")     # dumps full Trace-DSL to stderr
    """

    def __init__(self, capacity: int = 200, dump_stream=None) -> None:
        """Initialise the handler with buffer capacity and output stream.

        Args:
            capacity: Maximum number of log entries retained in the circular
                buffer per execution context. When the buffer is full, the
                oldest entry is evicted to make room. Defaults to 200.
            dump_stream: A writable file-like object for DSL dump output.
                Defaults to sys.stderr so dumps don't interfere with stdout.
        """
        super().__init__()
        self._capacity = capacity
        self._dump_stream = dump_stream or sys.stderr
        self._ctx = ContextManager()

    # ---------------------------------------------------------------------- #
    # Public interface
    # ---------------------------------------------------------------------- #

    def emit(self, record: logging.LogRecord) -> None:
        """Process a single log record.

        Called automatically by the logging framework (after locking) for every
        record that passes this handler's level filter.

        Behaviour:
            1. Convert ``record`` to a Trace-DSL line via ``_to_dsl()``.
            2. Append the DSL line to the context-local RingBuffer.
            3. If the record's level is ERROR or above, invoke ``_dump()`` to
               flush the entire buffer as a Trace-DSL narrative.

        Args:
            record: The LogRecord produced by the logging framework.
        """
        try:
            buf = get_buffer(self._capacity)
            dsl_line = self._to_dsl(record)
            buf.push(dsl_line, level=record.levelno)

            if record.levelno >= logging.ERROR:
                self._dump(buf)
        except Exception:
            # Delegate error handling to the standard logging machinery so that
            # a bug inside TraceLog never silences the application's own logs.
            self.handleError(record)

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    def _to_dsl(self, record: logging.LogRecord) -> str:
        """Convert a LogRecord to a single Trace-DSL line.

        DSL prefix convention:
            ``!! <message>``  — ERROR / CRITICAL (includes exception type if present)
            ``.. <message>``  — WARNING
            ``.. [LEVEL] <message>`` — DEBUG / INFO and others

        Indentation reflects the current call-stack depth tracked by ContextManager,
        so nested function calls appear visually as a tree.

        Args:
            record: The LogRecord to convert.

        Returns:
            A formatted Trace-DSL string, indented by the current call depth.

        Example:
            >>> # At depth 1 with an INFO record for message "loading config"
            >>> # returns: "  .. [INFO] loading config"
        """
        depth = self._ctx.get_depth()
        indent = "  " * depth

        if record.levelno >= logging.ERROR:
            prefix = "!!"
        elif record.levelno >= logging.WARNING:
            prefix = ".."
        else:
            prefix = f".. [{record.levelname}]"

        msg = record.getMessage()

        # If the record carries exception info, prepend the exception class name
        # to make it obvious at a glance what kind of failure occurred.
        if record.exc_info and record.exc_info[1]:
            exc = record.exc_info[1]
            return f"{indent}{prefix} {type(exc).__name__}: {msg}"

        return f"{indent}{prefix} {msg}"

    def _dump(self, buf: RingBuffer) -> None:
        """Flush the buffer as a Trace-DSL narrative and reset it.

        Retrieves all entries from the buffer via ``flash()`` (which also clears
        it), then writes each DSL line to ``_dump_stream`` wrapped in a header
        and footer for easy identification in log output.

        Args:
            buf: The RingBuffer instance for the current execution context.
        """
        entries = buf.flash()  # atomic snapshot + clear
        stream = self._dump_stream

        print("\n=== [TraceLog] DUMP START ===", file=stream)
        for entry in entries:
            print(entry.dsl_line, file=stream)
        print("=== [TraceLog] DUMP END ===\n", file=stream)

"""handler.py - Core integration layer for TraceLog.

Design contract:
    - Developers add ONE line to their existing logging setup: addHandler().
    - All log records flow through emit(), which appends Trace-DSL entries to
      a per-context circular buffer.
    - On ERROR or above, ALL registered buffers across ALL threads are drained,
      merged by timestamp, and exported as one combined Trace-DSL dump.

Typical usage:
    import logging
    from tracelog import TraceLogHandler

    # Default: dumps to stderr
    logging.getLogger().addHandler(TraceLogHandler())

    # Custom: dump to file instead
    from tracelog.exporter import FileExporter
    logging.getLogger().addHandler(TraceLogHandler(exporter=FileExporter("/var/log/trace.log")))

    logger = logging.getLogger(__name__)
    logger.info("Starting job")    # buffered silently
    logger.error("Job failed")     # triggers full Trace-DSL dump across all threads
"""

import logging
import os
import threading
import weakref
from contextvars import ContextVar
from typing import Optional

from .buffer import ChunkBuffer, LogEntry
from .context import ContextManager
from .exporter import TraceExporter, StreamExporter

# ---------------------------------------------------------------------------
# Per-thread / per-coroutine buffer isolation via ContextVar.
# ---------------------------------------------------------------------------
_buffer_var: ContextVar[ChunkBuffer] = ContextVar("tracelog_buffer")

# ---------------------------------------------------------------------------
# Global buffer registry.
#
# Every ChunkBuffer created by get_buffer() registers itself here as a weakref.
# TraceLogHandler._dump() iterates this registry on every ERROR to collect
# all thread buffers — including worker threads that never call logger.error()
# themselves (e.g. ThreadPoolExecutor workers).
#
# Weakrefs prevent the registry from keeping buffers alive past their natural
# lifetime. Dead refs are pruned lazily on each new buffer registration.
# ---------------------------------------------------------------------------
_registry_lock: threading.Lock = threading.Lock()
_buffer_registry: set[weakref.ref] = set()


def _register_buffer(buf: ChunkBuffer) -> None:
    """Register a new buffer in the global registry, pruning dead refs first."""
    with _registry_lock:
        dead = {ref for ref in _buffer_registry if ref() is None}
        _buffer_registry.difference_update(dead)
        _buffer_registry.add(weakref.ref(buf))


# Default chunk directory, overridable via TRACELOG_CHUNK_DIR environment variable.
_DEFAULT_CHUNK_DIR = os.environ.get("TRACELOG_CHUNK_DIR", ".tracelog/chunks")


def get_buffer(
    capacity: int = 200, max_chunks: int = 50, chunk_dir: Optional[str] = None
) -> ChunkBuffer:
    """Return the ChunkBuffer bound to the current execution context.

    On first access within a thread or asyncio Task, a new ChunkBuffer is
    created, bound via the ContextVar, and registered in the global buffer
    registry so that TraceLogHandler._dump() can collect it at error time.

    Args:
        capacity: Maximum memory capacity of the buffer before flushing chunks.
        max_chunks: Maximum number of chunk files to keep on disk.
        chunk_dir: Path to directory for storing flush chunks. Defaults to
            the ``TRACELOG_CHUNK_DIR`` environment variable, or ``.tracelog/chunks``
            if the variable is not set.

    Returns:
        The ChunkBuffer associated with the current execution context.
    """
    try:
        return _buffer_var.get()
    except LookupError:
        resolved_dir = chunk_dir if chunk_dir is not None else _DEFAULT_CHUNK_DIR
        buf = ChunkBuffer(
            capacity=capacity, max_chunks=max_chunks, chunk_dir=resolved_dir
        )
        _buffer_var.set(buf)
        _register_buffer(buf)
        return buf


class TraceLogHandler(logging.Handler):
    """A logging.Handler that buffers records as Trace-DSL and dumps on error.

    TraceLogHandler integrates TraceLog into the standard Python logging pipeline
    without requiring any changes to existing application code. Developers simply
    attach this handler to their root (or any) logger.

    Buffering strategy:
        Every log record received by emit() is converted to a Trace-DSL line and
        appended to the context-local ChunkBuffer. Records below ERROR level are
        held in the buffer silently. When an ERROR (or CRITICAL) record arrives,
        ALL registered thread buffers are drained, merged chronologically, and
        exported as one combined Trace-DSL dump.

    Thread-safety:
        The parent class ``logging.Handler`` wraps emit() with acquire()/release()
        around a threading.RLock, so concurrent emit() calls are serialized.
        Buffer isolation across threads is handled by the ContextVar in get_buffer().
        The global registry is protected by _registry_lock.

    Example:
        >>> import logging
        >>> from tracelog import TraceLogHandler
        >>> logging.getLogger().addHandler(TraceLogHandler())
        >>> logger = logging.getLogger("myapp")
        >>> logger.info("step one")   # buffered
        >>> logger.error("oh no")     # dumps full Trace-DSL across all threads
    """

    def __init__(
        self,
        capacity: int = 200,
        max_chunks: int = 50,
        chunk_dir: str = ".tracelog/chunks",
        dump_stream=None,
        exporter: Optional[TraceExporter] = None,
    ) -> None:
        """Initialise the handler with buffer limits and a dump exporter.

        Args:
            capacity: Maximum number of entries in memory before flushing to disk chunk.
            max_chunks: Maximum number of disk chunk files.
            chunk_dir: Path for writing temporary buffer chunks.
            dump_stream: Deprecated. A writable file-like object passed directly
                to StreamExporter. Ignored when ``exporter`` is supplied.
                Kept for backward compatibility.
            exporter: A TraceExporter instance that receives the flushed entries
                on each ERROR dump. Defaults to StreamExporter(sys.stderr).
        """
        super().__init__()
        self._capacity = capacity
        self._max_chunks = max_chunks
        self._chunk_dir = chunk_dir
        if exporter is not None:
            self._exporter: TraceExporter = exporter
        else:
            import sys
            self._exporter = StreamExporter(stream=dump_stream or sys.stderr)
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
            2. Append the DSL line to the current thread's ChunkBuffer.
            3. If the record's level is ERROR or above, invoke ``_dump()`` to
               drain ALL registered buffers and export as one combined dump.

        Args:
            record: The LogRecord produced by the logging framework.
        """
        try:
            buf = get_buffer(self._capacity, self._max_chunks, self._chunk_dir)
            dsl_line = self._to_dsl(record)
            buf.push(dsl_line, level=record.levelno)

            if record.levelno >= logging.ERROR:
                self._dump()
        except Exception:
            import traceback
            traceback.print_exc()
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

        Indentation reflects the current call-stack depth tracked by ContextManager.

        Args:
            record: The LogRecord to convert.

        Returns:
            A formatted Trace-DSL string, indented by the current call depth.
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

        if record.exc_info and record.exc_info[1]:
            exc = record.exc_info[1]
            return f"{indent}{prefix} {type(exc).__name__}: {msg}"

        return f"{indent}{prefix} {msg}"

    def _dump(self) -> None:
        """Drain ALL registered thread buffers, merge by timestamp, export once.

        Takes a snapshot of the global buffer registry under lock, then flashes
        every live buffer. Entries are sorted by monotonic timestamp to produce
        the true chronological execution narrative across all threads.
        """
        with _registry_lock:
            refs = list(_buffer_registry)

        all_entries: list[LogEntry] = []
        for ref in refs:
            b = ref()
            if b is not None:
                all_entries.extend(b.flash())

        all_entries.sort(key=lambda e: e.timestamp)
        self._exporter.export(all_entries)

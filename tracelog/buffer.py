"""buffer.py - Context-local circular buffer for Trace-DSL log entries.

RingBuffer is the in-memory store that holds Trace-DSL lines between log calls.
Under normal execution (no errors), the buffer accumulates entries silently and
is never persisted — keeping overhead minimal. On error, TraceLogHandler calls
``flash()`` to atomically snapshot and clear the buffer, producing the full
execution narrative for that context.

Design decisions:
    - ``collections.deque(maxlen=N)`` provides O(1) append with automatic eviction
      of the oldest entry when capacity is exceeded.
    - ``deque.append`` is atomic under CPython's GIL, so no explicit lock is
      required for single-producer scenarios (one thread writing its own buffer).
    - ``flash()`` combines snapshot and clear in a single call to minimise the
      window in which a concurrent read could observe a partially-cleared state.
"""

from collections import deque
from typing import List
import time


class LogEntry:
    """An immutable record stored inside a RingBuffer.

    Each entry captures the DSL-formatted log line, the log level, and a
    monotonic timestamp so that entries can be ordered and timed when needed.

    Attributes:
        timestamp (float): Monotonic clock value at the time of creation,
            as returned by ``time.monotonic()``. Not wall-clock time.
        dsl_line (str): The formatted Trace-DSL string, e.g. ``"  .. [INFO] msg"``.
        level (int): The ``logging`` level constant (e.g. ``logging.DEBUG = 10``).
            Stored for potential downstream filtering without re-parsing the line.
    """

    __slots__ = ("timestamp", "dsl_line", "level")

    def __init__(self, timestamp: float, dsl_line: str, level: int = 0) -> None:
        """Create a new LogEntry.

        Args:
            timestamp: Monotonic timestamp at the moment the entry was created.
            dsl_line: Pre-formatted Trace-DSL string to store.
            level: Logging level integer corresponding to the original record.
                Defaults to 0 (NOTSET).
        """
        self.timestamp = timestamp
        self.dsl_line = dsl_line
        self.level = level

    def __repr__(self) -> str:  # pragma: no cover
        return f"LogEntry({self.timestamp:.3f}, {self.dsl_line!r})"


class RingBuffer:
    """Fixed-capacity circular buffer for Trace-DSL LogEntry objects.

    The buffer enforces a maximum capacity via ``deque(maxlen=capacity)``.
    When the buffer is full, the oldest entry is silently dropped on the next
    ``push()`` call. This prevents unbounded memory growth in long-running
    processes while preserving the *most recent* context — which is exactly
    the window of interest when an error occurs.

    Thread-safety note:
        ``deque.append`` and ``list(deque)`` are both atomic in CPython.
        This is sufficient because each thread owns its own RingBuffer (via
        ``contextvars.ContextVar``), so concurrent writes to the *same* buffer
        do not occur in the normal execution model. If a buffer is deliberately
        shared across threads, callers must add their own locking.

    Example:
        >>> buf = RingBuffer(capacity=3)
        >>> buf.push(">> foo()", level=10)
        >>> buf.push(".. [INFO] step", level=20)
        >>> len(buf)
        2
        >>> entries = buf.flash()
        >>> len(entries)
        2
        >>> len(buf)   # cleared after flash
        0
    """

    def __init__(self, capacity: int = 200) -> None:
        """Initialise the buffer with the given maximum capacity.

        Args:
            capacity: Maximum number of LogEntry objects retained. When full,
                the oldest entry is evicted on the next push. Defaults to 200.
        """
        self._buffer: deque[LogEntry] = deque(maxlen=capacity)

    def push(self, dsl_line: str, level: int = 0) -> None:
        """Append a new Trace-DSL entry to the buffer.

        If the buffer has reached its capacity, the oldest entry is automatically
        removed to make room for the new one (FIFO eviction).

        Args:
            dsl_line: The formatted Trace-DSL string to store (e.g. ``">> pay(x=1)"``).
            level: The logging level integer for the entry. Defaults to 0 (NOTSET).
        """
        self._buffer.append(LogEntry(time.monotonic(), dsl_line, level))

    def flash(self) -> List[LogEntry]:
        """Return all entries as a list and clear the buffer atomically.

        This is the primary read operation used by TraceLogHandler during an
        error dump. The snapshot-then-clear pattern guarantees that the buffer
        is empty after the call, giving subsequent execution a clean slate.

        Returns:
            A list of all LogEntry objects in insertion order (oldest first).
            The returned list is a shallow copy; the buffer is cleared.

        Example:
            >>> buf = RingBuffer()
            >>> buf.push(">> foo()", level=10)
            >>> entries = buf.flash()
            >>> len(entries), len(buf)
            (1, 0)
        """
        entries = list(self._buffer)
        self._buffer.clear()
        return entries

    def snapshot(self) -> List[LogEntry]:
        """Return all entries without clearing the buffer.

        Intended for testing and debugging only. In production, prefer ``flash()``
        to avoid accumulating stale entries after an error dump.

        Returns:
            A shallow-copy list of current LogEntry objects in insertion order.
        """
        return list(self._buffer)

    def clear(self) -> None:
        """Remove all entries from the buffer without returning them."""
        self._buffer.clear()

    def __len__(self) -> int:
        """Return the current number of entries in the buffer."""
        return len(self._buffer)

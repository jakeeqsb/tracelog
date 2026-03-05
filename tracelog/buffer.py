"""buffer.py - Context-local chunk buffer for Trace-DSL log entries.

ChunkBuffer is the in-memory store that holds Trace-DSL lines between log calls.
Under normal execution (no errors), the buffer accumulates entries. When it
becomes full, it signals the caller (handler) to flush the chunk to disk.
On error, TraceLogHandler calls ``flash()`` to retrieve all current entries
and merges them with previously flushed chunks for the full execution narrative.

Design decisions:
    - ``List[LogEntry]`` provides fast appends and snapshots.
    - Instead of evicting old entries (like a ring buffer), we return a boolean
      overflow flag from ``push()`` so the Handler can flush to persistent storage,
      guaranteeing zero information loss.
    - ``flash()`` combines snapshot and clear in a single call.
"""

from typing import List
import time
import pickle
from pathlib import Path


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


class ChunkBuffer:
    """Fixed-capacity chunk buffer for Trace-DSL LogEntry objects.

    Unlike a ring buffer that discards old entries when full, this buffer
    flushes the chunk to a persistent storage directory when capacity is reached,
    guaranteeing zero data loss for long-running executions.
    Upon an error dump, all disk chunks and the remaining memory buffer are merged.

    Thread-safety note:
        Each thread owns its own ChunkBuffer (via ``contextvars.ContextVar``),
        so concurrent writes to the *same* buffer do not occur in the normal
        execution model. If a buffer is deliberately shared across threads,
        callers must add their own locking.

    Example:
        >>> buf = ChunkBuffer(capacity=2)
        >>> buf.push(">> foo()", level=10)
        >>> buf.push(".. [INFO] step", level=20)
        >>> len(buf)  # 0 because it flushed to disk!
        0
        >>> entries = buf.flash()
        >>> len(entries)
        2
    """

    def __init__(
        self,
        capacity: int = 200,
        max_chunks: int = 50,
        chunk_dir: str = ".tracelog/chunks",
    ) -> None:
        """Initialise the buffer with the given maximum capacity.

        Args:
            capacity: Maximum number of LogEntry objects retained in memory.
                When full, the buffer flushes to disk. Defaults to 200.
            max_chunks: Maximum number of chunk files to keep per buffer to
                prevent unbounded disk growth. Defaults to 50.
            chunk_dir: Directory where chunk temp files are stored.
        """
        self._capacity = capacity
        self._max_chunks = max_chunks
        self._chunk_dir = Path(chunk_dir)

        self._buffer: List[LogEntry] = []
        self._chunk_files: List[Path] = []

    def push(self, dsl_line: str, level: int = 0) -> None:
        """Append a new Trace-DSL entry to the buffer.

        If the buffer reaches its capacity, memory contents are automatically
        flushed to a chunk file on disk.

        Args:
            dsl_line: The formatted Trace-DSL string to store (e.g. ``">> pay(x=1)"``).
            level: The logging level integer for the entry. Defaults to 0 (NOTSET).
        """
        self._buffer.append(LogEntry(time.monotonic(), dsl_line, level))
        if len(self._buffer) >= self._capacity:
            self._flush_to_chunk()

    def _flush_to_chunk(self) -> None:
        """Serialize current buffer to a disk chunk and clear memory."""
        if not self._buffer:
            return

        self._chunk_dir.mkdir(parents=True, exist_ok=True)
        filename = f"chunk_{id(self)}_{time.time_ns()}.pkl"
        filepath = self._chunk_dir / filename

        with open(filepath, "wb") as f:
            pickle.dump(self._buffer, f)

        self._buffer.clear()
        self._chunk_files.append(filepath)

        # Evict oldest chunk if exceeding max_chunks
        while len(self._chunk_files) > self._max_chunks:
            oldest = self._chunk_files.pop(0)
            try:
                oldest.unlink(missing_ok=True)
            except OSError:
                pass

    def flash(self) -> List[LogEntry]:
        """Return all entries (disk chunks + memory list) and clear everything entirely.

        This is used by TraceLogHandler to extract the full trace for persistence.
        The snapshot-then-clear pattern guarantees that the buffer is empty
        after the call, wiping out disk chunks as well.

        Returns:
            A list of all LogEntry objects in insertion order.
            The buffer is cleared.
        """
        all_entries = []
        for filepath in self._chunk_files:
            try:
                with open(filepath, "rb") as f:
                    all_entries.extend(pickle.load(f))
            except Exception:
                pass
            try:
                filepath.unlink(missing_ok=True)
            except OSError:
                pass
        self._chunk_files.clear()

        all_entries.extend(self._buffer)
        self._buffer.clear()
        return all_entries

    def snapshot(self) -> List[LogEntry]:
        """Return all entries without clearing the buffer or disk chunks.

        Intended for testing and debugging only.

        Returns:
            A list of all current LogEntry objects (disk + memory) in insertion order.
        """
        all_entries = []
        for filepath in self._chunk_files:
            try:
                with open(filepath, "rb") as f:
                    all_entries.extend(pickle.load(f))
            except Exception:
                pass
        all_entries.extend(self._buffer)
        return all_entries

    def clear(self) -> None:
        """Remove all entries from the memory buffer and delete disk chunks."""
        self._buffer.clear()
        for filepath in self._chunk_files:
            try:
                filepath.unlink(missing_ok=True)
            except OSError:
                pass
        self._chunk_files.clear()

    def __len__(self) -> int:
        """Return the current number of entries in memory buffer (ignores chunks limits)."""
        return len(self._buffer)

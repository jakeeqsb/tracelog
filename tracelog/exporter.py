"""exporter.py - Pluggable dump target for Trace-DSL output.

This module defines the TraceExporter protocol and provides two concrete
implementations for Phase 1:

    StreamExporter  — writes the DSL dump to any writable stream (default: stderr).
    FileExporter    — appends each DSL dump to a file on disk, with optional rotation.

By accepting a TraceExporter via TraceLogHandler(exporter=...), callers can swap
the dump destination without touching any other SDK code.

Typical usage::

    import logging
    from tracelog import TraceLogHandler
    from tracelog.exporter import FileExporter

    handler = TraceLogHandler(exporter=FileExporter("/var/log/trace.log"))
    logging.getLogger().addHandler(handler)
"""

import sys
import os
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

from .buffer import LogEntry


class TraceExporter(ABC):
    """Abstract base class for all Trace-DSL dump destinations.

    Any custom exporter must subclass this and implement ``export()``.
    The exporter receives an immutable list of ``LogEntry`` objects —
    the result of a ``RingBuffer.flash()`` call — and is responsible
    for serialising and persisting them in whatever format it chooses.

    Example:
        >>> class MyExporter(TraceExporter):
        ...     def export(self, entries: List[LogEntry]) -> None:
        ...         for entry in entries:
        ...             send_to_remote(entry.dsl_line)
    """

    @abstractmethod
    def export(self, entries: List[LogEntry]) -> None:
        """Persist a list of Trace-DSL entries to the configured destination.

        Called by TraceLogHandler after every ERROR-level log record. The entries
        are already in insertion order (oldest first) and have been removed from
        the RingBuffer via flash().

        Args:
            entries: Ordered list of LogEntry objects to export. May be empty
                if the buffer was cleared before the error was recorded.
        """


class StreamExporter(TraceExporter):
    """Export Trace-DSL dumps to a writable stream (default: sys.stderr).

    This is the default exporter used by TraceLogHandler when no exporter is
    specified. It prints a clearly delimited block to the stream so that
    TraceLog output is easy to grep in application logs.

    Output format::

        === [TraceLog] DUMP START ===
        >> pay(user_id=1, amount=5000)
          .. [INFO] Querying balance
        !! ValueError: InsufficientFunds
        === [TraceLog] DUMP END ===

    Attributes:
        _stream: The writable file-like object to write to.
        _show_timestamp: If True, a UTC timestamp header is prepended to each dump.

    Example:
        >>> import sys
        >>> from tracelog.exporter import StreamExporter
        >>> exporter = StreamExporter(stream=sys.stdout)
    """

    def __init__(self, stream=None, show_timestamp: bool = False) -> None:
        """Initialise the stream exporter.

        Args:
            stream: A writable file-like object. Defaults to ``sys.stderr``
                so that dump output does not pollute the application's stdout.
            show_timestamp: If True, prepend an ISO-8601 UTC timestamp to each
                dump header. Useful for correlating dumps with external logs.
        """
        self._stream = stream or sys.stderr
        self._show_timestamp = show_timestamp

    def export(self, entries: List[LogEntry]) -> None:
        """Write the Trace-DSL dump block to the configured stream.

        Args:
            entries: Ordered list of LogEntry objects from the flushed buffer.
        """
        stream = self._stream
        timestamp = ""
        if self._show_timestamp:
            timestamp = (
                f" [{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}]"
            )

        print(f"\n=== [TraceLog] DUMP START{timestamp} ===", file=stream)
        for entry in entries:
            print(entry.dsl_line, file=stream)
        print("=== [TraceLog] DUMP END ===\n", file=stream)


class FileExporter(TraceExporter):
    """Export Trace-DSL dumps by appending to a log file on disk.

    Each dump is appended to the specified file as a self-contained block
    with an ISO-8601 UTC timestamp, making it easy to parse dumps from a
    long-running process log.

    The file and any missing parent directories are created automatically
    on first export.

    Output format (appended to file)::

        === [TraceLog] DUMP 2024-01-15T12:34:56Z ===
        >> pay(user_id=1, amount=5000)
          .. [INFO] Querying balance
        !! ValueError: InsufficientFunds
        === END ===

    Attributes:
        _path (str): Absolute or relative path to the dump file.
        _max_bytes (int): Soft size limit before the file is rotated.
            0 means no rotation.
        _encoding (str): File encoding. Defaults to ``"utf-8"``.

    Example:
        >>> from tracelog.exporter import FileExporter
        >>> exporter = FileExporter("/var/log/tracelog/app.log")
        >>> exporter = FileExporter("./trace.log", max_bytes=5 * 1024 * 1024)
    """

    def __init__(
        self,
        path: str,
        max_bytes: int = 0,
        encoding: str = "utf-8",
    ) -> None:
        """Initialise the file exporter.

        Args:
            path: Path to the output file. Parent directories are created
                automatically if they do not exist.
            max_bytes: Soft maximum file size in bytes before rotation. When
                the file exceeds this size, it is renamed to ``<path>.bak``
                (overwriting any previous backup) and a new file is started.
                Set to 0 (default) to disable rotation.
            encoding: Character encoding for the output file. Defaults to
                ``"utf-8"``.

        Raises:
            ValueError: If ``max_bytes`` is negative.
        """
        if max_bytes < 0:
            raise ValueError(f"max_bytes must be >= 0, got {max_bytes}")
        self._path = path
        self._max_bytes = max_bytes
        self._encoding = encoding

    def export(self, entries: List[LogEntry]) -> None:
        """Append the Trace-DSL dump block to the configured file.

        Creates the file (and any missing parent directories) if it does not
        yet exist. Rotates the file beforehand if ``max_bytes`` is set and
        the current file exceeds the limit.

        Args:
            entries: Ordered list of LogEntry objects from the flushed buffer.
        """
        self._ensure_dir()
        if self._max_bytes > 0:
            self._rotate_if_needed()

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines = [
            f"\n=== [TraceLog] DUMP {timestamp} ===",
            *(entry.dsl_line for entry in entries),
            "=== END ===\n",
        ]

        with open(self._path, "a", encoding=self._encoding) as f:
            f.write("\n".join(lines) + "\n")

    # ---------------------------------------------------------------------- #
    # Private helpers
    # ---------------------------------------------------------------------- #

    def _ensure_dir(self) -> None:
        """Create parent directories for the log file if they do not exist."""
        parent = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(parent, exist_ok=True)

    def _rotate_if_needed(self) -> None:
        """Rotate the log file if it exceeds ``_max_bytes``.

        The current file is moved to ``<path>.bak``, replacing any previous
        backup. A new (empty) file will be created by the next ``export()``
        call.
        """
        try:
            if os.path.getsize(self._path) >= self._max_bytes:
                backup = self._path + ".bak"
                os.replace(self._path, backup)
        except FileNotFoundError:
            pass  # File does not yet exist — nothing to rotate.

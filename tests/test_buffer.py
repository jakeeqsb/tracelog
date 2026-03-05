"""test_buffer.py - Unit tests for ChunkBuffer and LogEntry.

Covers:
    - LogEntry field storage
    - ChunkBuffer push, len, flash, snapshot, clear
    - Overflow: oldest entry evicted when capacity exceeded
    - flash() atomicity: returns entries AND clears buffer in one call
    - 100% branch coverage target for buffer.py
"""

import logging
import time

import pytest

from tracelog.buffer import LogEntry, ChunkBuffer


# ---------------------------------------------------------------------------
# LogEntry
# ---------------------------------------------------------------------------


class TestLogEntry:
    def test_log_entry_stores_fields(self):
        """LogEntry correctly stores timestamp, dsl_line, and level."""
        ts = time.monotonic()
        entry = LogEntry(ts, ">> foo()", logging.DEBUG)

        assert entry.timestamp == ts
        assert entry.dsl_line == ">> foo()"
        assert entry.level == logging.DEBUG

    def test_log_entry_default_level_is_zero(self):
        """LogEntry.level defaults to 0 (NOTSET) when not supplied."""
        entry = LogEntry(0.0, ".. [INFO] hello")
        assert entry.level == 0

    def test_log_entry_is_immutable_via_slots(self):
        """LogEntry uses __slots__, so arbitrary attributes cannot be added."""
        entry = LogEntry(0.0, "test", 10)
        with pytest.raises(AttributeError):
            entry.unexpected = "should fail"  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# ChunkBuffer — basic operations
# ---------------------------------------------------------------------------


class TestChunkBufferBasic:
    def test_ring_buffer_initial_length_is_zero(self):
        """A newly created ChunkBuffer has no entries."""
        buf = ChunkBuffer(capacity=10)
        assert len(buf) == 0

    def test_ring_buffer_push_increments_length(self):
        """push() adds one entry and len() reflects it."""
        buf = ChunkBuffer(capacity=10)
        buf.push(">> foo()", level=logging.DEBUG)
        assert len(buf) == 1

    def test_ring_buffer_push_stores_dsl_line(self):
        """Pushed entries have the correct dsl_line value."""
        buf = ChunkBuffer(capacity=10)
        buf.push(".. [INFO] starting", level=logging.INFO)
        entries = buf.snapshot()
        assert entries[0].dsl_line == ".. [INFO] starting"

    def test_ring_buffer_push_stores_level(self):
        """Pushed entries carry the provided log level."""
        buf = ChunkBuffer(capacity=10)
        buf.push("!! oops", level=logging.ERROR)
        assert buf.snapshot()[0].level == logging.ERROR

    def test_ring_buffer_push_records_monotonic_timestamp(self):
        """Each entry has a non-negative monotonic timestamp."""
        buf = ChunkBuffer()
        before = time.monotonic()
        buf.push(">> bar()")
        after = time.monotonic()
        ts = buf.snapshot()[0].timestamp
        assert before <= ts <= after


# ---------------------------------------------------------------------------
# ChunkBuffer — flash()
# ---------------------------------------------------------------------------


class TestChunkBufferFlash:
    def test_ring_buffer_flash_returns_all_entries(self):
        """flash() returns every entry that was pushed."""
        buf = ChunkBuffer(capacity=10)
        buf.push("A")
        buf.push("B")
        buf.push("C")
        entries = buf.flash()
        assert [e.dsl_line for e in entries] == ["A", "B", "C"]

    def test_ring_buffer_flash_clears_buffer_after_snapshot(self):
        """After flash(), the buffer is empty."""
        buf = ChunkBuffer(capacity=10)
        buf.push("A")
        buf.flash()
        assert len(buf) == 0

    def test_ring_buffer_flash_atomic_snapshot_and_clear(self):
        """flash() empties the buffer and returns the snapshot in one call."""
        buf = ChunkBuffer(capacity=10)
        for i in range(5):
            buf.push(f"line {i}")
        entries = buf.flash()
        # Snapshot captured all 5
        assert len(entries) == 5
        # Buffer is now empty
        assert len(buf) == 0

    def test_ring_buffer_flash_on_empty_buffer_returns_empty_list(self):
        """flash() on an empty buffer returns [] without error."""
        buf = ChunkBuffer()
        assert buf.flash() == []

    def test_ring_buffer_flash_preserves_insertion_order(self):
        """flash() returns entries oldest-first."""
        buf = ChunkBuffer(capacity=5)
        for i in range(5):
            buf.push(str(i))
        entries = buf.flash()
        assert [e.dsl_line for e in entries] == ["0", "1", "2", "3", "4"]


# ---------------------------------------------------------------------------
# ChunkBuffer — overflow / eviction
# ---------------------------------------------------------------------------


class TestChunkBufferOverflow:
    def test_chunk_buffer_flushes_to_disk_on_capacity(self, tmp_path):
        """When capacity is reached, entries are written to a chunk file."""
        buf = ChunkBuffer(capacity=3, chunk_dir=str(tmp_path))
        buf.push("first")
        buf.push("second")
        buf.push("third")  # Reaches capacity (3), triggers flush

        # Memory buffer should be empty
        assert len(buf._buffer) == 0
        # One chunk file should be created
        assert len(buf._chunk_files) == 1
        assert buf._chunk_files[0].exists()

        buf.push("fourth")
        # Memory buffer has 1, disk has 3
        assert len(buf._buffer) == 1

        dsl_lines = [e.dsl_line for e in buf.snapshot()]
        assert dsl_lines == ["first", "second", "third", "fourth"]

    def test_chunk_buffer_flash_merges_chunks_and_memory(self, tmp_path):
        """flash() merges chunks from disk and entries in memory."""
        buf = ChunkBuffer(capacity=2, chunk_dir=str(tmp_path))
        for i in range(5):
            buf.push(f"entry {i}")

        # 5 items, capacity 2 => 2 flushes (4 items), 1 item in memory
        assert len(buf._chunk_files) == 2
        assert len(buf._buffer) == 1

        entries = buf.flash()
        assert len(entries) == 5
        assert [e.dsl_line for e in entries] == [f"entry {i}" for i in range(5)]

        # Everything should be cleared
        assert len(buf._buffer) == 0
        assert len(buf._chunk_files) == 0
        assert not any(tmp_path.iterdir())  # directory should be empty

    def test_chunk_buffer_evicts_oldest_chunks_when_exceeding_max_chunks(
        self, tmp_path
    ):
        """When the number of chunks exceeds max_chunks, the oldest chunk is deleted."""
        buf = ChunkBuffer(capacity=2, max_chunks=2, chunk_dir=str(tmp_path))
        for i in range(7):
            buf.push(f"entry {i}")

        # 7 items, capacity 2 => 3 flushes. Max chunks is 2, so the first chunk (entry 0, 1) is dropped
        assert len(buf._chunk_files) == 2

        entries = buf.snapshot()
        # Should only have chunks 2 and 3 (items 2,3,4,5) and memory (item 6)
        dsl_lines = [e.dsl_line for e in entries]
        assert dsl_lines == ["entry 2", "entry 3", "entry 4", "entry 5", "entry 6"]


# ---------------------------------------------------------------------------
# ChunkBuffer — snapshot() and clear()
# ---------------------------------------------------------------------------


class TestChunkBufferSnapshotAndClear:
    def test_ring_buffer_snapshot_does_not_clear_buffer(self):
        """snapshot() returns entries without clearing the buffer."""
        buf = ChunkBuffer(capacity=5)
        buf.push("keep me")
        _ = buf.snapshot()
        assert len(buf) == 1

    def test_ring_buffer_clear_removes_all_entries(self):
        """clear() empties the buffer without returning entries."""
        buf = ChunkBuffer(capacity=5)
        buf.push("A")
        buf.push("B")
        buf.clear()
        assert len(buf) == 0

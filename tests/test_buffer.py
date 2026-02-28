"""test_buffer.py - Unit tests for RingBuffer and LogEntry.

Covers:
    - LogEntry field storage
    - RingBuffer push, len, flash, snapshot, clear
    - Overflow: oldest entry evicted when capacity exceeded
    - flash() atomicity: returns entries AND clears buffer in one call
    - 100% branch coverage target for buffer.py
"""

import logging
import time

import pytest

from tracelog.buffer import LogEntry, RingBuffer


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
# RingBuffer — basic operations
# ---------------------------------------------------------------------------


class TestRingBufferBasic:
    def test_ring_buffer_initial_length_is_zero(self):
        """A newly created RingBuffer has no entries."""
        buf = RingBuffer(capacity=10)
        assert len(buf) == 0

    def test_ring_buffer_push_increments_length(self):
        """push() adds one entry and len() reflects it."""
        buf = RingBuffer(capacity=10)
        buf.push(">> foo()", level=logging.DEBUG)
        assert len(buf) == 1

    def test_ring_buffer_push_stores_dsl_line(self):
        """Pushed entries have the correct dsl_line value."""
        buf = RingBuffer(capacity=10)
        buf.push(".. [INFO] starting", level=logging.INFO)
        entries = buf.snapshot()
        assert entries[0].dsl_line == ".. [INFO] starting"

    def test_ring_buffer_push_stores_level(self):
        """Pushed entries carry the provided log level."""
        buf = RingBuffer(capacity=10)
        buf.push("!! oops", level=logging.ERROR)
        assert buf.snapshot()[0].level == logging.ERROR

    def test_ring_buffer_push_records_monotonic_timestamp(self):
        """Each entry has a non-negative monotonic timestamp."""
        buf = RingBuffer()
        before = time.monotonic()
        buf.push(">> bar()")
        after = time.monotonic()
        ts = buf.snapshot()[0].timestamp
        assert before <= ts <= after


# ---------------------------------------------------------------------------
# RingBuffer — flash()
# ---------------------------------------------------------------------------


class TestRingBufferFlash:
    def test_ring_buffer_flash_returns_all_entries(self):
        """flash() returns every entry that was pushed."""
        buf = RingBuffer(capacity=10)
        buf.push("A")
        buf.push("B")
        buf.push("C")
        entries = buf.flash()
        assert [e.dsl_line for e in entries] == ["A", "B", "C"]

    def test_ring_buffer_flash_clears_buffer_after_snapshot(self):
        """After flash(), the buffer is empty."""
        buf = RingBuffer(capacity=10)
        buf.push("A")
        buf.flash()
        assert len(buf) == 0

    def test_ring_buffer_flash_atomic_snapshot_and_clear(self):
        """flash() empties the buffer and returns the snapshot in one call."""
        buf = RingBuffer(capacity=10)
        for i in range(5):
            buf.push(f"line {i}")
        entries = buf.flash()
        # Snapshot captured all 5
        assert len(entries) == 5
        # Buffer is now empty
        assert len(buf) == 0

    def test_ring_buffer_flash_on_empty_buffer_returns_empty_list(self):
        """flash() on an empty buffer returns [] without error."""
        buf = RingBuffer()
        assert buf.flash() == []

    def test_ring_buffer_flash_preserves_insertion_order(self):
        """flash() returns entries oldest-first."""
        buf = RingBuffer(capacity=5)
        for i in range(5):
            buf.push(str(i))
        entries = buf.flash()
        assert [e.dsl_line for e in entries] == ["0", "1", "2", "3", "4"]


# ---------------------------------------------------------------------------
# RingBuffer — overflow / eviction
# ---------------------------------------------------------------------------


class TestRingBufferOverflow:
    def test_ring_buffer_overflow_evicts_oldest_entry(self):
        """When capacity is exceeded, the oldest (not newest) entry is removed."""
        buf = RingBuffer(capacity=3)
        buf.push("first")
        buf.push("second")
        buf.push("third")
        buf.push("fourth")  # should evict "first"

        dsl_lines = [e.dsl_line for e in buf.snapshot()]
        assert "first" not in dsl_lines
        assert "fourth" in dsl_lines

    def test_ring_buffer_overflow_length_stays_at_capacity(self):
        """Buffer length never exceeds capacity even after many pushes."""
        capacity = 5
        buf = RingBuffer(capacity=capacity)
        for i in range(20):
            buf.push(f"entry {i}")
        assert len(buf) == capacity

    def test_ring_buffer_overflow_preserves_most_recent_entries(self):
        """After overflow, the most recent N entries are retained."""
        buf = RingBuffer(capacity=3)
        for i in range(10):
            buf.push(f"entry {i}")
        dsl_lines = [e.dsl_line for e in buf.snapshot()]
        assert dsl_lines == ["entry 7", "entry 8", "entry 9"]


# ---------------------------------------------------------------------------
# RingBuffer — snapshot() and clear()
# ---------------------------------------------------------------------------


class TestRingBufferSnapshotAndClear:
    def test_ring_buffer_snapshot_does_not_clear_buffer(self):
        """snapshot() returns entries without clearing the buffer."""
        buf = RingBuffer(capacity=5)
        buf.push("keep me")
        _ = buf.snapshot()
        assert len(buf) == 1

    def test_ring_buffer_clear_removes_all_entries(self):
        """clear() empties the buffer without returning entries."""
        buf = RingBuffer(capacity=5)
        buf.push("A")
        buf.push("B")
        buf.clear()
        assert len(buf) == 0

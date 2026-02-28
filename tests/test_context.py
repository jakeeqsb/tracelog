"""test_context.py - Unit tests for ContextManager.

Covers:
    - Initial depth is 0
    - increase_depth / decrease_depth symmetry
    - decrease_depth is clamped at 0 (no negative depth)
    - get_trace_id returns 8-char hex string
    - get_trace_id is stable within the same context
    - Thread isolation: each thread has its own depth counter
"""

import threading

import pytest

from tracelog.context import ContextManager


# ---------------------------------------------------------------------------
# Depth management
# ---------------------------------------------------------------------------


class TestContextManagerDepth:
    def setup_method(self):
        """Reset depth to 0 before each test by creating a fresh ContextVar reset."""
        self.ctx = ContextManager()
        # Reset depth to known state
        ContextManager._depth.set(0)

    def test_context_manager_initial_depth_is_zero(self):
        """A fresh context starts at depth 0."""
        assert self.ctx.get_depth() == 0

    def test_context_manager_increase_depth_increments_by_one(self):
        """increase_depth() adds exactly 1 to the current depth."""
        self.ctx.increase_depth()
        assert self.ctx.get_depth() == 1

    def test_context_manager_decrease_depth_decrements_by_one(self):
        """decrease_depth() subtracts exactly 1 from the current depth."""
        self.ctx.increase_depth()
        self.ctx.increase_depth()
        self.ctx.decrease_depth()
        assert self.ctx.get_depth() == 1

    def test_context_manager_depth_symmetric_after_nested_calls(self):
        """After N increases and N decreases, depth returns to starting value."""
        for _ in range(5):
            self.ctx.increase_depth()
        for _ in range(5):
            self.ctx.decrease_depth()
        assert self.ctx.get_depth() == 0

    def test_context_manager_decrease_depth_clamped_at_zero(self):
        """decrease_depth() never goes below 0 even when called excessively."""
        assert self.ctx.get_depth() == 0
        self.ctx.decrease_depth()  # should be a no-op
        self.ctx.decrease_depth()  # should be a no-op
        assert self.ctx.get_depth() == 0

    def test_context_manager_multiple_instances_share_contextvar(self):
        """Two ContextManager instances in the same context see the same depth."""
        ctx1 = ContextManager()
        ctx2 = ContextManager()
        ContextManager._depth.set(0)

        ctx1.increase_depth()
        assert ctx2.get_depth() == 1  # shared ContextVar


# ---------------------------------------------------------------------------
# Trace ID
# ---------------------------------------------------------------------------


class TestContextManagerTraceId:
    def setup_method(self):
        self.ctx = ContextManager()
        ContextManager._trace_id.set("")  # reset to trigger lazy generation

    def test_context_manager_trace_id_is_eight_chars(self):
        """get_trace_id() returns an 8-character string."""
        tid = self.ctx.get_trace_id()
        assert len(tid) == 8

    def test_context_manager_trace_id_is_hexadecimal(self):
        """get_trace_id() returns a valid hex string."""
        tid = self.ctx.get_trace_id()
        int(tid, 16)  # raises ValueError if not valid hex

    def test_context_manager_trace_id_is_stable_within_context(self):
        """Calling get_trace_id() twice returns the same value."""
        tid1 = self.ctx.get_trace_id()
        tid2 = self.ctx.get_trace_id()
        assert tid1 == tid2


# ---------------------------------------------------------------------------
# Thread isolation
# ---------------------------------------------------------------------------


class TestContextManagerThreadIsolation:
    def test_context_manager_depth_is_isolated_per_thread(self):
        """Each thread has its own independent depth counter."""
        results = {}

        def worker(name: str, increments: int):
            ctx = ContextManager()
            ContextManager._depth.set(0)
            for _ in range(increments):
                ctx.increase_depth()
            results[name] = ctx.get_depth()

        t1 = threading.Thread(target=worker, args=("t1", 3))
        t2 = threading.Thread(target=worker, args=("t2", 7))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Each thread accumulated its own depth — no cross-contamination.
        assert results["t1"] == 3
        assert results["t2"] == 7

    def test_context_manager_trace_id_is_isolated_per_thread(self):
        """Each thread generates its own independent Trace ID."""
        trace_ids = {}

        def worker(name: str):
            ctx = ContextManager()
            ContextManager._trace_id.set("")
            trace_ids[name] = ctx.get_trace_id()

        t1 = threading.Thread(target=worker, args=("t1",))
        t2 = threading.Thread(target=worker, args=("t2",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert trace_ids["t1"] != trace_ids["t2"]

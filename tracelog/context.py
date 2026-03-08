"""context.py - Execution context tracking for Trace-DSL indentation.

ContextManager maintains four pieces of per-context state that TraceLog needs:

    Trace ID:
                A short unique identifier for the logical execution flow
                (for example, one request or one worker task). Generated lazily.

    Span ID:
                A short unique identifier for the current active span within the
                trace. Generated lazily and distinct from the trace ID.

    Parent Span ID:
                The parent of the current span, if the active work item was
                spawned from another span.

    Call Depth:
                An integer counter that @trace increments on function entry and
                decrements on function exit (normal or exceptional). TraceLogHandler
                reads this value to compute the indentation level for DSL lines.

All values are stored in ``contextvars.ContextVar`` instances, which provide
automatic isolation across threads, asyncio Tasks, and other concurrent contexts
without any explicit locking.
"""

import contextvars
import uuid
from typing import Optional


class ContextManager:
    """Tracks trace IDs, span IDs, and call-stack depth for the current context.

    This class acts as a thin, stateless facade over two module-level
    ``contextvars.ContextVar`` instances. Multiple ContextManager instances can
    safely coexist (e.g. one in TraceLogHandler and one in instrument.py) because
    they all read from and write to the same underlying ContextVars.

    Attributes:
        _trace_id (ContextVar[str]): Stores the short hex trace ID for the
            current context. Defaults to an empty string, which triggers lazy
            generation on first ``get_trace_id()`` call.
        _span_id (ContextVar[str]): Stores the current span ID for the active
            execution scope. Defaults to an empty string, which triggers lazy
            generation on first ``get_span_id()`` call.
        _parent_span_id (ContextVar[str]): Stores the parent's Span ID if this
            context was spawned by another traced execution flow. Defaults to "".
        _depth (ContextVar[int]): Stores the current call-stack depth as an
            integer. Defaults to 0 (top level, no indentation).

    Example:
        >>> ctx = ContextManager()
        >>> ctx.get_depth()
        0
        >>> ctx.increase_depth()
        >>> ctx.get_depth()
        1
        >>> ctx.decrease_depth()
        >>> ctx.get_depth()
        0
    """

    _trace_id: contextvars.ContextVar[str] = contextvars.ContextVar(
        "tracelog_trace_id", default=""
    )
    _span_id: contextvars.ContextVar[str] = contextvars.ContextVar(
        "tracelog_span_id", default=""
    )
    _parent_span_id: contextvars.ContextVar[str] = contextvars.ContextVar(
        "tracelog_parent_span_id", default=""
    )
    _depth: contextvars.ContextVar[int] = contextvars.ContextVar(
        "tracelog_depth", default=0
    )

    def get_span_id(self) -> str:
        """Return the current Span ID, generating one if absent.

        Span IDs are distinct from Trace IDs. Calling this method also ensures
        that a Trace ID exists for the current execution flow.
        """
        sid = self._span_id.get()
        if not sid:
            self.get_trace_id()
            sid = str(uuid.uuid4())[:8]
            self._span_id.set(sid)
        return sid

    def set_span_id(self, span_id: str) -> None:
        """Explicitly set the current Span ID for the active execution scope."""
        self._span_id.set(span_id)

    def get_parent_span_id(self) -> Optional[str]:
        """Return the parent Span ID for this context, if one was explicitly set.

        Used to link distributed or concurrent execution flows back to their caller.

        Returns:
            The parent Span ID string (e.g. "a1b2c3d4"), or None if no parent
            is associated with this context.
        """
        pid = self._parent_span_id.get()
        return pid if pid else None

    def set_parent_span_id(self, parent_id: str) -> None:
        """Explicitly set the parent Span ID for the current context.

        Typically called automatically by decorators or integration utilities
        when crossing thread or async boundaries.

        Args:
            parent_id: The Span ID string of the parent execution flow.
        """
        self._parent_span_id.set(parent_id)

    def set_trace_id(self, trace_id: str) -> None:
        """Explicitly set the Trace ID for the current execution context."""
        self._trace_id.set(trace_id)

    def get_trace_id(self) -> str:
        """Return the Trace ID for the current context, generating one if absent.

        The ID is a shortened UUID4 (first 8 hex characters) that uniquely
        identifies a logical execution flow within a process. It is generated
        lazily so that contexts that never call this method incur no overhead.

        Returns:
            An 8-character hexadecimal string, e.g. ``"a1b2c3d4"``.

        Example:
            >>> ctx = ContextManager()
            >>> tid = ctx.get_trace_id()
            >>> len(tid)
            8
        """
        tid = self._trace_id.get()
        if not tid:
            tid = str(uuid.uuid4())[:8]
            self._trace_id.set(tid)
        return tid

    def get_depth(self) -> int:
        """Return the current call-stack depth for the active context.

        Returns:
            A non-negative integer representing how many @trace-decorated
            function frames are currently on the call stack. 0 means we are
            at the top level (no active @trace frames).
        """
        return self._depth.get()

    def increase_depth(self) -> None:
        """Increment the call-stack depth by one.

        Called by the @trace decorator immediately after recording a function
        entry (``>>`` DSL line) so that nested calls appear indented relative
        to their caller.
        """
        self._depth.set(self._depth.get() + 1)

    def decrease_depth(self) -> None:
        """Decrement the call-stack depth by one, clamped at zero.

        Called by the @trace decorator on both normal return and exception paths
        to restore the depth to the level of the caller. The floor of 0 prevents
        accidental negative indentation if decrease is called more times than
        increase (e.g. in re-entrant or error-recovery scenarios).
        """
        current = self._depth.get()
        if current > 0:
            self._depth.set(current - 1)

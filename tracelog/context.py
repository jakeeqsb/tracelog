"""context.py - Execution context tracking for Trace-DSL indentation.

ContextManager maintains two pieces of per-context state that TraceLog needs to
produce properly indented Trace-DSL output:

    Trace ID:   A short unique identifier for the current logical execution flow.
                Generated lazily on first access so there is zero cost when the
                ID is never used.

    Call Depth: An integer counter that @trace increments on function entry and
                decrements on function exit (normal or exceptional). TraceLogHandler
                reads this value to compute the indentation level for DSL lines.

Both values are stored in ``contextvars.ContextVar`` instances, which provides
automatic isolation across threads, asyncio Tasks, and other concurrent contexts
without any explicit locking.
"""

import contextvars
import uuid
from typing import Optional


class ContextManager:
    """Tracks Trace ID and call-stack depth for the current execution context.

    This class acts as a thin, stateless facade over two module-level
    ``contextvars.ContextVar`` instances. Multiple ContextManager instances can
    safely coexist (e.g. one in TraceLogHandler and one in instrument.py) because
    they all read from and write to the same underlying ContextVars.

    Attributes:
        _trace_id (ContextVar[str]): Stores the short hex Trace ID for the
            current context. Defaults to an empty string, which triggers lazy
            generation on first ``get_trace_id()`` call.
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
    _depth: contextvars.ContextVar[int] = contextvars.ContextVar(
        "tracelog_depth", default=0
    )

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

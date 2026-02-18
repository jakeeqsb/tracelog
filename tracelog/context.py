import contextvars
import uuid
from typing import Optional

class ContextManager:
    """
    Manages execution context (Trace ID, Call Depth) using contextvars.
    Thread-safe and AsyncIO-safe.
    """
    
    _trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
    _depth: contextvars.ContextVar[int] = contextvars.ContextVar("depth", default=0)

    def get_trace_id(self) -> str:
        """Returns current trace ID. Generates new one if empty."""
        tid = self._trace_id.get()
        if not tid:
            tid = str(uuid.uuid4())[:8]  # Short ID
            self._trace_id.set(tid)
        return tid

    def get_depth(self) -> int:
        """Returns current call stack depth."""
        return self._depth.get()

    def increase_depth(self) -> None:
        """Increments call depth."""
        self._depth.set(self._depth.get() + 1)

    def decrease_depth(self) -> None:
        """Decrements call depth, ensuring it doesn't go below 0."""
        d = self._depth.get()
        if d > 0:
            self._depth.set(d - 1)

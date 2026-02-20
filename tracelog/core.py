"""core.py - Shared buffer access re-exports.

This module previously contained the legacy TraceLog wrapper class. That class
has been superseded by TraceLogHandler, which integrates directly with the Python
standard logging pipeline without requiring developers to change how they log.

The sole responsibility of core.py is now to re-export get_buffer() and
ContextManager so that internal modules (instrument.py, tests) can import them
from a stable location without creating circular imports.

Note:
    ``get_buffer()`` in handler.py is the **single source of truth** for the
    shared per-context RingBuffer. All TraceLog components — TraceLogHandler and
    @trace — call this function to ensure they write into the same buffer within
    one execution context (thread or asyncio Task).
"""

from .handler import get_buffer
from .context import ContextManager

__all__ = ["get_buffer", "ContextManager"]

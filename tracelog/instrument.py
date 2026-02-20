"""instrument.py - Optional @trace decorator for fine-grained Trace-DSL capture.

The @trace decorator enriches the Trace-DSL narrative with function-level events
that the standard logging infrastructure cannot provide on its own:

    ``>>``  Function entry, including all bound argument values.
    ``<<``  Normal return, including the return value.
    ``!!``  Unhandled exception, including exception type and message.

The decorator shares the same context-local RingBuffer as TraceLogHandler (via
``get_buffer()``), so its DSL lines are interleaved correctly with INFO/DEBUG/ERROR
entries produced through standard ``logging`` calls in the same execution context.

Usage:
    @trace is strictly opt-in. Apply it only to functions where the argument
    values and return result are meaningful for post-mortem analysis.

    from tracelog import trace

    @trace
    def process_payment(user_id: int, amount: float) -> Receipt:
        ...

Note:
    When used together with TraceLogHandler, the decorator and handler write to
    the same buffer, so a single ERROR log will dump everything — decorator lines
    included — in one coherent Trace-DSL block.
"""

import logging
from functools import wraps
import inspect
from typing import Callable

from .handler import get_buffer
from .context import ContextManager

# Module-level ContextManager instance.
# ContextManager uses contextvars internally, so this singleton is safe to share
# across threads and async tasks — each context gets its own depth counter.
_ctx = ContextManager()


def trace(func: Callable) -> Callable:
    """Decorator that records function entry, return, and exceptions as Trace-DSL.

    Wraps ``func`` so that every call produces structured DSL lines in the shared
    context-local RingBuffer. The lines use call-stack depth (managed by
    ContextManager) for indentation, matching the visual hierarchy of @trace-
    decorated calls within the same execution context.

    DSL output format:
        ``{indent}>> {qualname}({args})``   on entry
        ``{indent}<< {return_value!r}``     on successful return
        ``{indent}!! {ExcType}: {message}`` on exception (then re-raised)

    Args:
        func: The callable to wrap. Works with regular functions and methods.
            Does *not* currently support async functions (async support is
            planned for Phase 2).

    Returns:
        A wrapped callable with the same signature, name, and docstring as the
        original function (preserved via ``functools.wraps``).

    Raises:
        Any exception raised by ``func`` is re-raised unchanged after the ``!!``
        DSL line is written to the buffer. The decorator never swallows exceptions.

    Example:
        >>> from tracelog import TraceLogHandler, trace
        >>> import logging
        >>> logging.getLogger().addHandler(TraceLogHandler())
        >>> logger = logging.getLogger(__name__)
        >>>
        >>> @trace
        ... def divide(a, b):
        ...     return a / b
        >>>
        >>> divide(10, 2)   # writes ">> divide(a=10, b=2)" and "<< 5.0" to buffer
        5.0
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        buf = get_buffer()
        depth = _ctx.get_depth()
        indent = "  " * depth

        # ------------------------------------------------------------------
        # Capture bound arguments using inspect so we get keyword-argument
        # names even when the caller uses positional syntax.
        # Falls back to "..." for C-extension functions or other edge cases
        # where inspect.signature() raises TypeError.
        # ------------------------------------------------------------------
        try:
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arg_str = ", ".join(f"{k}={v!r}" for k, v in bound.arguments.items())
        except Exception:
            arg_str = "..."

        # >> Entry: record before increasing depth so the entry line aligns
        # with the caller's indentation level.
        buf.push(f"{indent}>> {func.__qualname__}({arg_str})", level=logging.DEBUG)
        _ctx.increase_depth()

        try:
            result = func(*args, **kwargs)

            # << Normal return: decrease depth first so the return line aligns
            # with the entry line, not the body.
            _ctx.decrease_depth()
            ret_indent = "  " * _ctx.get_depth()
            buf.push(f"{ret_indent}<< {result!r}", level=logging.DEBUG)
            return result

        except Exception as exc:
            # !! Exception: decrease depth to match the entry indent, then
            # record the exception type and message before re-raising so the
            # caller's error-handling logic is not disrupted.
            _ctx.decrease_depth()
            err_indent = "  " * _ctx.get_depth()
            buf.push(
                f"{err_indent}!! {type(exc).__name__}: {exc}",
                level=logging.ERROR,
            )
            raise  # Always re-raise; TraceLog must never swallow exceptions.

    return wrapper

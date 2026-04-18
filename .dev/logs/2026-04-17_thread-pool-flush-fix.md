# ThreadPoolExecutor Worker Thread Buffer Flush Fix

**Date**: 2026-04-17
**Branch**: main
**Agent**: Software Engineer

## Goal

Fix a critical SDK design gap: worker thread `ChunkBuffer` instances are never flushed when a `ThreadPoolExecutor` worker raises an exception, because `TraceLogHandler.emit()` only flushes the buffer of the thread that calls `logger.error()` (always the main thread).

## Root Cause

`TraceLogHandler.emit()` calls `get_buffer()` inside the thread that calls `logger.error()`. In `ThreadPoolExecutor` scenarios, the exception propagates to the main thread via `future.result()`, so `get_buffer()` returns the main thread's buffer — not the worker's. Worker buffers accumulate trace entries and are then silently discarded when the thread is recycled.

## Fix Design

### 1. `handler.py` — add `_handler_registry` + `flush_current_context()`

```python
import weakref

_handler_registry: list[weakref.ref] = []

def flush_current_context() -> None:
    """Flush the current thread/task's buffer through all live TraceLogHandler instances."""
    try:
        buf = _buffer_var.get()
    except LookupError:
        return
    entries = buf.flash()
    if not entries:
        return
    for ref in _handler_registry:
        handler = ref()
        if handler is not None:
            handler._exporter.export(entries)
```

In `TraceLogHandler.__init__`, append `weakref.ref(self)` to `_handler_registry`.

### 2. `instrument.py` — call `flush_current_context()` at root span exception

```python
from .handler import get_buffer, flush_current_context

except Exception as exc:
    _ctx.decrease_depth()
    err_indent = "  " * _ctx.get_depth()
    buf.push(f"{err_indent}!! {type(exc).__name__}: {exc}", level=logging.ERROR)
    if depth == 0:          # root span in this thread — buffer won't be flushed otherwise
        flush_current_context()
    raise
```

`depth` is captured at the start of `wrapper` (before `increase_depth`). `depth == 0` means this is the outermost `@trace` call in the current thread.

## Steps

1. Write plan log (this file)
2. Update `docs/sdk/handler.md` — document `flush_current_context()` and `_handler_registry`
3. Update `docs/sdk/instrument.md` — document thread-aware flush behavior
4. Implement in `tracelog/handler.py`
5. Implement in `tracelog/instrument.py`

## Design docs referenced

- `docs/sdk/handler.md`
- `docs/sdk/instrument.md`
- `docs/sdk/overview.md`

## Notes

- `weakref` prevents the registry from keeping dead handlers alive
- `depth == 0` at entry = root span = no parent `@trace` in this thread (see existing leak-prevention check)
- The `!!` DSL line is pushed to the buffer BEFORE `flush_current_context()` is called, so it appears in the final export
- No application code changes required — Zero-Friction principle preserved
- The `finally` block (span context restore) runs after `raise`, which is after `flush_current_context()` — no ordering issue

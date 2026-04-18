# ThreadPoolExecutor Buffer Flush — Full Redesign

**Date**: 2026-04-17
**Branch**: main
**Agent**: Software Engineer

## Goal

Remove the dependency on `@trace` for correct multi-threading behavior. `TraceLogHandler` must work standalone (Zero-Friction principle fully restored). `@trace` reverts to pure DSL enrichment.

## Problem with previous fix

`flush_current_context()` was called inside `@trace`'s root-span exception handler — conflating two unrelated responsibilities:
1. `@trace` = enrichment tool (>> entry, << return, !! exception)
2. `@trace` = thread buffer flush signal ← WRONG

Without `@trace` on the worker function, worker buffers were still silently lost.

## New Design

### Global buffer registry in `handler.py`

Every `ChunkBuffer` created by `get_buffer()` registers itself in a module-level weakref registry. `TraceLogHandler._dump()` drains ALL registered live buffers — not just the current thread's.

```python
_registry_lock: threading.Lock = threading.Lock()
_buffer_registry: set[weakref.ref[ChunkBuffer]] = set()
```

`get_buffer()` on first call per thread:
1. Creates `ChunkBuffer`
2. Calls `_register_buffer(buf)` — appends weakref, cleans dead refs

`TraceLogHandler._dump()`:
1. Snapshot registry under lock
2. For each live buffer: `b.flash()` — collect all entries
3. Sort all entries by timestamp (chronological merge)
4. Export combined entries

### `@trace` reverts to pure enrichment

Remove `flush_current_context()` import and call from `instrument.py`. No infrastructure responsibility.

## Steps

1. Write plan log (this file)
2. Update `docs/sdk/handler.md` — replace deferred-flush section with registry design
3. Update `docs/sdk/instrument.md` — remove "Thread-Aware Root Span Flush" section
4. Implement `handler.py`:
   - Remove `_pending_flush_lock`, `_pending_flush`, `flush_current_context()`
   - Add `_registry_lock`, `_buffer_registry`, `_register_buffer()`
   - Update `get_buffer()` to call `_register_buffer()`
   - Rewrite `TraceLogHandler._dump()` to drain all registered buffers
5. Implement `instrument.py`:
   - Remove `flush_current_context` import
   - Remove `if depth == 0: flush_current_context()` block
6. Run tests

## Design docs referenced

- `docs/sdk/handler.md`
- `docs/sdk/instrument.md`

## Tradeoff

If a non-failing thread is actively mid-execution when ERROR fires, its partial buffer is also included in the dump. After drain, its buffer is empty and it continues cleanly. Tradeoff: some noise from concurrent threads vs. losing all worker traces. Correct data > perfect isolation.

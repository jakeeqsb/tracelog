# handler.py — Design Document

## Role and Purpose

`handler.py` is the **primary integration entry point** for the TraceLog SDK. It carries two main responsibilities:

1. **`get_buffer()`** — A global access function that returns the `ChunkBuffer` bound to the current execution context (thread/coroutine).
2. **`TraceLogHandler`** — A handler inheriting from `logging.Handler` to connect TraceLog to the standard Python logging pipeline.

Developers only need to add one line:

```python
logging.getLogger().addHandler(TraceLogHandler())
```

Afterward, all `logger.info()` and `logger.error()` calls flow automatically through the TraceLog buffer — including across `ThreadPoolExecutor` worker threads.

---

## `get_buffer()` — Buffer Access Function

### What it is

Returns a `ChunkBuffer` instance bound to the current execution context via `ContextVar[ChunkBuffer]`. Creates a new buffer on first call and returns the same instance on subsequent calls within the same context.

On first call, the new buffer is registered in the **global buffer registry** (`_buffer_registry`) so that `TraceLogHandler._dump()` can collect it at error time.

### Interface

```python
_buffer_var: ContextVar[ChunkBuffer] = ContextVar("tracelog_buffer")

def get_buffer(
    capacity: int = 200, max_chunks: int = 50, chunk_dir: Optional[str] = None
) -> ChunkBuffer:
    """Return the ChunkBuffer bound to the current execution context.
    On first access, a new buffer is created, bound to the ContextVar,
    and registered in _buffer_registry.
    """
```

### ContextVar Isolation

Each thread/coroutine gets its own `ChunkBuffer`. Writes from one thread never touch another's buffer.

```
Main Thread:    Thread-A:       Thread-B:
  buf_main        buf_A           buf_B
  (isolated)      (isolated)      (isolated)

All three are registered in _buffer_registry.
_dump() drains all three on ERROR.
```

---

## Global Buffer Registry

### What it is

A module-level weakref set that tracks every `ChunkBuffer` ever created by `get_buffer()`.

```python
import threading
import weakref

_registry_lock: threading.Lock = threading.Lock()
_buffer_registry: set[weakref.ref] = set()
```

### Why it is needed

`TraceLogHandler.emit()` runs in the thread that calls `logger.error()`. In `ThreadPoolExecutor` patterns, that thread is always the **main thread** — worker thread buffers are structurally unreachable from `emit()`.

The registry solves this: `_dump()` iterates all registered live buffers and drains every one, regardless of which thread they belong to. No application code change required — Zero-Friction fully preserved.

### Lifecycle

- **Registration**: `get_buffer()` registers the buffer on first creation via `_register_buffer()`.
- **Cleanup**: Dead weakrefs (GC'd buffers) are pruned inside `_register_buffer()` each time a new buffer is registered.
- **Thread-safety**: All registry access is guarded by `_registry_lock`.

---

## `TraceLogHandler` — Logging Integration Handler

### What it is

A class inheriting from `logging.Handler`. When the Python standard logging framework routes a log record, the `emit()` method inside this class is triggered.

### Attributes

| Attribute | Type | Description |
|---|---|---|
| `_capacity` | `int` | Memory capacity limit passed to ChunkBuffer. |
| `_max_chunks` | `int` | Maximum disk chunks. |
| `_chunk_dir` | `str` | Directory path for disk chunks. |
| `_exporter` | `TraceExporter` | Destination for JSON dumps (Default: `StreamExporter`). |
| `_ctx` | `ContextManager` | Provides call depth for DSL indentation. |

### Interface

```python
class TraceLogHandler(logging.Handler):

    def emit(self, record: logging.LogRecord) -> None:
        """Push record to current thread's buffer. On ERROR, drain all buffers."""

    def _to_dsl(self, record: logging.LogRecord) -> str:
        """Convert LogRecord to Trace-DSL line with level prefix and indent."""

    def _dump(self) -> None:
        """Drain ALL registered buffers, merge by timestamp, export once."""
```

### `_dump()` — Cross-Thread Drain

On every ERROR, `_dump()` collects entries from **all registered live buffers**, sorts them by monotonic timestamp, and exports as one combined dump:

```
_dump()
  ├─ snapshot _buffer_registry under lock
  ├─ for each live buffer ref:
  │    all_entries.extend(buf.flash())   ← drain every thread's buffer
  ├─ all_entries.sort(key=timestamp)     ← chronological merge
  └─ exporter.export(all_entries)        ← ONE combined dump
```

### emit() Processing Flow

```
emit(record)
  ├─ get_buffer() → ChunkBuffer (current thread, also in registry)
  ├─ _to_dsl(record) → ".. [INFO] step one"
  ├─ buf.push(dsl_line, level)
  └─ if record.levelno >= ERROR:
         _dump()
           ├─ drain all registered buffers (all threads)
           └─ exporter.export(merged entries)
```

### ThreadPoolExecutor example — no @trace required

```python
logging.getLogger().addHandler(TraceLogHandler())   # the only required line

def worker(item):
    logger.info("processing %s", item)   # → worker's buffer
    logger.debug("detail: %s", item)     # → worker's buffer
    raise RuntimeError("fail")           # → worker's buffer gets "!! RuntimeError"

with ThreadPoolExecutor() as ex:
    futures = [ex.submit(worker, i) for i in range(4)]
    for f in futures:
        try:
            f.result()
        except RuntimeError as e:
            logger.error("worker failed: %s", e)
            # → _dump() drains ALL buffers (main + all workers)
            # → ONE combined dump with full execution history
```

### Design Decisions

| Decision | Alternative | Reason for Rejection |
|---|---|---|
| Drain ALL registered buffers on ERROR | Drain only current thread's buffer | Current-thread-only misses worker buffers in ThreadPoolExecutor — fundamental structural gap |
| Global weakref registry in `get_buffer()` | Require `@trace` on worker functions | `@trace` is an enrichment tool, not infrastructure; requiring it for correct behavior violates Zero-Friction |
| Sort entries by timestamp | Per-thread ordering | Workers run concurrently; timestamp merge produces the true chronological execution narrative |
| Inherit `logging.Handler` | Custom interceptor | Standard approach gets thread locking, level filtering, and error handling for free |
| Pluggable `TraceExporter` | Hardcoded output | Dump targets must remain flexible for files, streams, and future remote endpoints |
| Dump only on ERROR | Manual `dump()` trigger | Automatic ERROR-driven triggers honor Zero-Friction — no application code changes |

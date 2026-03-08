# handler.py — Design Document

## Role and Purpose

`handler.py` is the **primary integration entry point** for the TraceLog SDK. It carries two main responsibilities:

1. **`get_buffer()`** — A global access function that returns the `ChunkBuffer` bound to the current execution context (thread/coroutine).
2. **`TraceLogHandler`** — A handler inheriting from `logging.Handler` to connect TraceLog to the standard Python logging pipeline.

Developers only need to add one line:

```python
logging.getLogger().addHandler(TraceLogHandler())
```

Afterward, all `logger.info()` and `logger.error()` calls flow automatically through the TraceLog buffer.

---

## `get_buffer()` — Buffer Access Function

### What it is

It returns a `ChunkBuffer` instance bounded to the current execution context via `ContextVar[ChunkBuffer]`. It creates a new buffer on the first call and returns the same instance on subsequent calls within the same context.

### Why it is needed

Directly instantiating `ChunkBuffer` would create disconnected buffers across the same thread. Meanwhile, making it a regular global variable would cause cross-threading contamination. `get_buffer()` acts as the **Single Source of Truth**, forcing all components within the SDK to access the buffer through this specific function.

### Interface

```python
_buffer_var: ContextVar[ChunkBuffer] = ContextVar("tracelog_buffer")

def get_buffer(
    capacity: int = 200, max_chunks: int = 50, chunk_dir: Optional[str] = None
) -> ChunkBuffer:
    """Return the ChunkBuffer bound to the current execution context.
    On first access, a new buffer is created and registered to the ContextVar.

    Args:
        capacity: Maximum items inside memory before offloading to chunk.
        max_chunks: Maximum number of chunk files to keep on disk.
        chunk_dir: Directory to save temporary JSON trace chunks.

    Returns:
        The ChunkBuffer instance bound to the current context.
    """
```

### ContextVar Isolation

```
Main Thread:         Thread-A:            Thread-B:
  get_buffer()         get_buffer()         get_buffer()
  → buf_main           → buf_A              → buf_B
  (Isolated)           (Isolated)           (Isolated)

The buffers are completely independent. A push/flash from one thread has absolutely zero impact on another.
```

---

## `TraceLogHandler` — Logging Integration Handler

### What it is

A class inheriting from `logging.Handler`. When the Python standard logging framework routes a log record, the `emit()` method inside this class is triggered.

### Why it is needed

The Python standard `logging` module employs a Handler-based architecture. Simply mounting `TraceLogHandler` connects all incoming records tied to that logger directly to the TraceLog buffer. No application code needs to be altered.

### Attributes

| Attribute | Type | Description |
|---|---|---|
| `_capacity` | `int` | Memory capacity limit. |
| `_max_chunks`| `int` | Maximum disk chunks. |
| `_exporter` | `TraceExporter` | Destination target used to serialize flushed entries into JSON dumps (Default: `StreamExporter`). |
| `_ctx`      | `ContextManager` | Identifies call depth to apply indents inside `_to_dsl()`. |

### Interface

```python
class TraceLogHandler(logging.Handler):

    def __init__(
        self,
        capacity: int = 200,
        max_chunks: int = 50,
        chunk_dir: str = ".tracelog/chunks",
        dump_stream=None,
        exporter: Optional[TraceExporter] = None,
    ) -> None:
        """Initialize handler.

        Args:
            capacity: Max entries in ChunkBuffer.
            max_chunks: Max temporary disk chunks.
            chunk_dir: Directory path for disk chunks.
            dump_stream: (Deprecated) Downward compatibility output stream.
            exporter: TraceExporter instance (Default: StreamExporter).
        """

    def emit(self, record: logging.LogRecord) -> None:
        """The core method called per record by the Python logging ecosystem.

        Behavior:
            1. Generate Trace-DSL string via _to_dsl(record).
            2. Mount onto buffer using get_buffer().push().
            3. If record.levelno >= ERROR, trigger `_dump()`.
        """

    def _to_dsl(self, record: logging.LogRecord) -> str:
        """Converts LogRecord to single Trace-DSL line.

        Applies indentations based on the current call depth.
        Level prefixes:
            ERROR/CRITICAL → "!! message"
            WARNING        → ".. message"
            INFO/DEBUG     → ".. [LEVEL] message"
        Appends ExcType (Class Name) if exception context exists.
        """

    def _dump(self, buf: ChunkBuffer) -> None:
        """Call `flash()` on the buffer and hand over the list of entries to TraceExporter.

        TraceExporter is exclusively responsible for JSON dump serialization and sink-specific I/O behavior.
        """
```

### Design Decisions

| Decision | Alternative | Reason for Rejection |
|---|---|---|
| Inherit `logging.Handler` | Custom independent interceptor | Using the standard approach takes advantage of the parent class covering Thread Locking, Level filtering, and error handling. |
| Incorporating `try/except` + `handleError()` in `emit()` | Ignoring exceptions | Prevents internal bugs inside TraceLog from swallowing core application error logs. `handleError()` yields to Python's standard error resolution. |
| Pluggable `TraceExporter` | Hardcoded `print()` functions | Dump targets must remain flexible so the SDK can emit JSON dumps to files, streams, or future remote aggregation endpoints. |
| Dump only on ERROR | Exposing manual `dump()` trigger | Automatic ERROR-driven triggers honor the Zero-Friction principle. Manual calls would force users to change their codebases. |

### emit() Processing Flow

```
emit(record)
  ├─ get_buffer() → ChunkBuffer (Current Context)
  ├─ _to_dsl(record) → ".. [INFO] Payment started"
  ├─ buf.push(dsl_line, level)
  └─ if record.levelno >= ERROR:
         _dump(buf)
           ├─ buf.flash() → entries[] + chunk/buf clear
           ├─ exporter.export(entries) → JSON dump
```

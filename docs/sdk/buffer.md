# buffer.py — Design Document

## Role and Purpose

`buffer.py` is the **foundational base layer** of the TraceLog SDK. It provides the data structure to store Trace-DSL entries in-memory and automatically offloads them to disk chunk files upon hitting overflow capacity.

The core philosophy of TraceLog, "Selective Persistence", begins in this file. During normal execution, logs are not written to files or databases; they are solely accumulated in an in-memory buffer. When the buffer reaches its `capacity`, it flushes to a **disk temporary chunk (`.json`)** and clears the memory. The moment an ERROR occurs, all disk chunks and the in-memory buffer are merged to reconstruct the complete execution narrative. This exact behavior is implemented inside the `flash()` method.

---

## Class Design

### `LogEntry`

**What it is:** An immutable data record stored inside the buffer.

**Why it is needed:** By storing entries as a structured object rather than a raw string, level-based filtering or timestamp-based sorting can be performed later without re-parsing the buffer strings. Utilizing `__slots__` also ensures memory efficiency.

#### Attributes

| Attribute | Type | Description |
|---|---|---|
| `timestamp` | `float` | The `time.monotonic()` value. Represents monotonically increasing time, not wall-clock time. |
| `dsl_line` | `str` | An already formatted Trace-DSL string. E.g., `"  .. [INFO] Payment started"` |
| `level` | `int` | Python `logging` level constant (e.g., `logging.ERROR = 40`). Default is 0 (NOTSET). |

#### Design Decisions

- **Use of `__slots__`**: Prohibits the addition of dynamic attributes to reduce memory footprint and forces immutability. This is an optimization for scenarios where hundreds of entries pile up.
- **Pre-formatted `dsl_line`**: Completing string formatting at capture time ensures that no formatting overhead is incurred during `flash()`.
- **`to_dict()` / `from_dict()`**: Built-in JSON serialization and deserialization methods to simplify chunk file I/O operations.

---

### `ChunkBuffer`

**What it is:** A Zero Information Loss fixed-capacity buffer. When memory fills up, it offloads to disk chunks (`.json`). Upon an error trigger, it merges all disk chunks to restore the complete execution history.

**Why it is needed:** A traditional Ring Buffer (like `deque(maxlen=N)`) permanently drops the oldest logs upon exceeding capacity. This could cause the most critical context immediately preceding the error (root function entry points, initial argument values) to vanish. `ChunkBuffer` guarantees data retention by persisting it to disk instead of discarding.

#### Key Attributes

| Attribute | Type | Description |
|---|---|---|
| `_buffer` | `list[LogEntry]` | In-memory storage container. |
| `_capacity` | `int` | Number of memory entries that trigger a chunk flush. |
| `_chunk_dir` | `Path` | Directory path to store chunk files (default: `.tracelog/chunks/`). |
| `_chunk_files` | `list[Path]` | List of disk chunk files belonging to the current span. |
| `_max_chunks` | `int` | Maximum number of chunks to keep. Deletes the oldest chunk file if exceeded. |

#### Interface

```python
class ChunkBuffer:
    def __init__(
        self,
        capacity: int = 200,
        max_chunks: int = 50,
        chunk_dir: Path | str = ".tracelog/chunks",
    ) -> None: ...

    def push(self, dsl_line: str, level: int = 0) -> None:
        """Appends a new entry to the buffer. If capacity is reached, memory contents are flushed to disk."""

    def flash(self) -> List[LogEntry]:
        """Merges all disk chunks and the memory buffer, returns the result, and completely clears everything (atomic operation)."""

    def snapshot(self) -> List[LogEntry]:
        """Returns the complete snapshot including disk chunks + memory buffer without clearing the data."""

    def clear(self) -> None:
        """Completely clears the memory buffer and deletes all disk chunk files."""
```

#### Design Decisions

| Decision | Alternative | Reason for Rejection |
|---|---|---|
| `list`-based in-memory buffer | `deque(maxlen=N)` | `deque` permanently deletes old data when `maxlen` is exceeded. Information loss is unacceptable. |
| Chunk File Format: **JSON** (`.json`) | pickle (`.pkl`) | JSON is human-readable, and external analysis tools / Phase 2 Indexers can parse it without the Python runtime. Pickle is an inflexible Python-specific binary format. |
| Flush I/O managed internally | Flush triggered by Handler | Encourages encapsulation; the buffer handles its own memory-to-disk lifecycle silently. |
| `flash()` = merge + clear in one call | Separate `read()` + `clear()` | Separating them introduces a risk of race conditions. Atomicity guarantees absolute accuracy of error dumps. |

#### Overflow Behavior (capacity=3, max_chunks=2)

```
push("A"), push("B"), push("C") → memory: [A, B, C]
push("D") → capacity reached, flush!
  → disk: chunk_1.json = [A, B, C], memory: [D]
push("E"), push("F"), push("G") → memory: [D, E, F, G]
push("H") → capacity reached, flush!
  → disk: chunk_1.json, chunk_2.json, memory: [H]

ERROR!
  flash() → Read: chunk_1 + chunk_2 + memory[H] → [A..H] completely restored
            Disk chunk files are successfully deleted.
```

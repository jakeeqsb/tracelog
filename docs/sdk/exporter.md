# exporter.py — Design Document

## Role and Purpose

`exporter.py` is the **Pluggable Dump Target** layer for the TraceLog SDK.

It bears the responsibility of determining where and how to save the Trace-DSL entries (`LogEntry` list) extracted from the `ChunkBuffer` upon the occurrence of an ERROR. Isolating this component from `handler.py` allows developers to adopt various output methodologies—like file rotation, remote network dispatches, and cloud storage—without muddying up TraceLog's core logic.

---

## Class Design

### `TraceExporter` (Protocol/ABC)

**What it is:** An abstract base class that all Exporter implementations must follow.

**Interface:**

```python
class TraceExporter(ABC):
    @abstractmethod
    def export(self, entries: List[LogEntry]) -> None:
        """Serialize and save the extracted list of LogEntry items from the buffer."""
```

**Design Decision:**

- Handing over the original `LogEntry` list wholesale grants implementations the absolute freedom to leverage metadata like timestamps or log levels to enact personalized formats.

---

### `StreamExporter`

**What it is:** The default Exporter capable of firing Trace-DSL chunks into designated writable streams (e.g., `sys.stderr`, `sys.stdout`).

**Features:**

- Projects dumps onto standard error streams (stderr) in development environments or orchestration infrastructures like Docker/K8s, leaning on preexisting infra to slurp logs effortlessly.
- Attaches the explicit tags `=== [TraceLog] DUMP ===` at the beginning and the end, simplifying the parsing and querying (i.e., grep) processes.
- Can optionally prepend UTC timestamps.

---

### `FileExporter`

**What it is:** An Exporter that appends dumps natively to a physical footprint (file) on a local disk space.

**Features:**

- Essential for long-running daemonized processes or file-based collector architectures.
- **Supports Automatic Rotation (`max_bytes`)**: Preemptively prevents solitary files from ballooning endlessly. If the file crosses the size ceiling, it swaps to a `.bak` backup file and refreshes with an empty file instance.
- Safely initializes uncreated parent directories during its first `export()` run to prevent I/O errors minus permission lockouts, leaning into the Zero-Friction mantra.

**Interface Example:**

```python
# Maintain up to 10MB; beyond this, overwrites onto trace.log.bak
exporter = FileExporter("/var/log/trace.log", max_bytes=10*1024*1024)
```

---

## Execution Flow (From TraceLogHandler's Perspective)

Inside `handler.py`, the system no longer vomits raw text into a hardcoded `dump_stream`. Outputs now process neatly like so:

```python
# Inside tracelog/handler.py _dump method

def _dump(self, buf: ChunkBuffer) -> None:
    # 1. Snapshot the buffer and instantly purge it (Atomic Action)
    entries = buf.flash()

    # 2. Delegate the formatting and routing responsibilities
    self._exporter.export(entries)
```

Thanks to this decoupling format, incorporating future exporters—such as `NetworkExporter` (HTTP REST pipelines) or `SlackExporter`—will not command a single line of modification to the SDK core (honoring the Open/Closed Principle).

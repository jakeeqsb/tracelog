# context.py — Design Document

## Role and Purpose

`context.py` is the **context state management layer** for TraceLog. It manages two core pieces of information:

1. **Trace ID** — An 8-character hex identifier identifying a single logical execution flow.
2. **Call Depth** — An integer indicating how deep the `@trace` decorator currently is within a stack of nested functions.

Because these two values are stored in `contextvars.ContextVar`, they are **automatically isolated** across threads and asyncio Tasks. Both `TraceLogHandler` and the `@trace` decorator synchronize their indentation depth through this module.

---

## Class Design

### `ContextManager`

**What it is:** A lightweight facade class managing two `contextvars.ContextVar` instances.

**Why it is needed:** Exposing `ContextVar` directly couples the caller to the internal implementation. `ContextManager` provides an explicit interface for this state, preventing caller code from breaking if the internal storage mechanism changes.

#### Internal State (ContextVar)

```python
# Class Variables — all ContextManager instances share the same ContextVars
_trace_id: contextvars.ContextVar[str] = ContextVar("tracelog_trace_id", default="")
_parent_span_id: contextvars.ContextVar[str] = ContextVar("tracelog_parent_span_id", default="")
_depth:    contextvars.ContextVar[int] = ContextVar("tracelog_depth",    default=0)
```

> **Key Takeaway:** Because `_trace_id`, `_parent_span_id`, and `_depth` are **class variables**, creating multiple `ContextManager()` instances will still reference the same `ContextVar`. This is why `TraceLogHandler` and `instrument.py` share the same underlying state despite possessing different `ContextManager()` instances.

#### Interface

```python
class ContextManager:

    def get_span_id(self) -> str:
        """Alias for get_trace_id(). Returns the Span ID for the current context."""

    def get_parent_span_id(self) -> Optional[str]:
        """Return the parent Span ID for this context, if explicitly set."""

    def set_parent_span_id(self, parent_id: str) -> None:
        """Explicitly set the parent Span ID for the current context."""

    def get_trace_id(self) -> str:
        """Returns the Trace ID for the current context. If none exists, generates an 8-character hex based on uuid4 and returns it.
        Repeated calls within the same context always return the same value."""

    def get_depth(self) -> int:
        """Returns current @trace call stack depth. 0 = top level (no indentation)."""

    def increase_depth(self) -> None:
        """Depth +1. Called by @trace decorator immediately after entering a function."""

    def decrease_depth(self) -> None:
        """Depth -1, clamped to a minimum of 0. Called by @trace decorator on return/exception."""
```

#### Design Decisions

| Decision | Alternative | Reason for Rejection |
|---|---|---|
| `contextvars.ContextVar` | `threading.local` | `contextvars` isolates asyncio Tasks. `threading.local` cannot distinguish between different async Tasks running in the same thread. |
| ContextVars declared as class variables | Declared as module variables | Tying them to the class makes them easier to access and reset directly in tests (`ContextManager._depth.set(0)`). |
| `decrease_depth()` clamping (minimum 0) | Allow negative values | Defensive programming against duplicate decrease calls during exception handling. Negative depth leads to indentation errors. |
| Trace ID is first 8 characters of UUID4 | Full UUID | A long UUID is a waste of LLM context tokens. 8 hex characters ensure sufficient uniqueness. |

#### Thread Isolation Behavior

```
Thread 1:                          Thread 2:
  ctx.increase_depth()               ctx.increase_depth()
  ctx.increase_depth()               # Thread 2 depth = 1
  # Thread 1 depth = 2               # Does not affect Thread 1's depth

  ContextVar stores independent values per thread → zero cross-contamination
```

#### Lazy Generation of Trace ID

```python
def get_trace_id(self) -> str:
    tid = self._trace_id.get()
    if not tid:           # Empty string = not generated yet
        tid = str(uuid.uuid4())[:8]
        self._trace_id.set(tid)
    return tid
```

By delaying the creation of the Trace ID until the exact moment it is needed, overhead is kept at 0 for contexts that never invoke the ID.

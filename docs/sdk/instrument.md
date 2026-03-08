# instrument.py — Design Document

## Role and Purpose

`instrument.py` is the **optional deep tracing layer** for the TraceLog SDK. It provides the `@trace` decorator, bringing deeper, function-level events to the Trace-DSL architecture that Python’s conventional `logging` package cannot naturally manifest via typical procedures:

- **Argument values upon function entry** (`>>`)
- **Return values upon standard function conclusions** (`<<`)
- **Exception triggers containing types and subsequent messages** (`!!`)

Given that the decorator piggybacks on `TraceLogHandler`’s same `get_buffer()` allocation, logs cast by the `@trace` decorator blend chronologically into one buffer with standard logging lines.

> ⚠️ **Opt-in Doctrine**: Applying `@trace` across an application is, without exception, non-mandatory setup. Decorators should only be consciously adopted when developers assess that argument structures or returns of particular operations will hold significant weight for future post-mortem investigations.

---

## The `trace` Decorator

### What it is

A function wrapper that automatically registers the entry, conclusion, and error events of any function into the `ChunkBuffer` of the current active context stream.

### Interface

```python
def trace(func: Callable) -> Callable:
    """A decorator chronicling function entries, returns, and exceptions into Trace-DSL.

    Args:
        func: The targeted encapsulation function. Endorses standard and method functionalities.
              Currently devoid of async functionality (Prepared for Phase 2 implementation).

    Returns:
        The wrapper function maintaining an identical signature, name, and docstring (using functools.wraps).

    Raises:
        Forces the precise reappearance of any exception triggered internally within func.
        TraceLog maintains a zero-tolerance policy against suppressing exceptions.
    """
```

### Internal Flow Execution

```python
@wraps(func)
def wrapper(*args, **kwargs):
    buf = get_buffer()                    # Acquire shared buffer
    depth = _ctx.get_depth()
    indent = "  " * depth

    # 1. Capture arguments (using inspect.signature)
    arg_str = ...  # "user_id=1, amount=5000"

    # 2. Map the >> Entry line (with identical indentation to current depth)
    buf.push(f"{indent}>> {func.__qualname__}({arg_str})", level=DEBUG)
    _ctx.increase_depth()                 # Augment internal depth +1

    try:
        result = func(*args, **kwargs)

        # 3. Map the << Return line (Post-depth restoration)
        _ctx.decrease_depth()
        ret_indent = "  " * _ctx.get_depth()
        buf.push(f"{ret_indent}<< {result!r}", level=DEBUG)
        return result

    except Exception as exc:
        # 4. Map the !! Exception line before absolutely raising the condition onwards
        _ctx.decrease_depth()
        err_indent = "  " * _ctx.get_depth()
        buf.push(f"{err_indent}!! {type(exc).__name__}: {exc}", level=ERROR)
        raise  # ← The absolute covenant opposing the swallowing of exceptions.
```

### Argument Capture Engine

```python
sig = inspect.signature(func)
bound = sig.bind(*args, **kwargs)
bound.apply_defaults()
arg_str = ", ".join(f"{k}={v!r}" for k, v in bound.arguments.items())
```

- Injects `inspect.signature` to drag out physical namespace configurations.
- Positional formats are completely shifted into keyword parameters → `foo(1, 2)` → `foo(a=1, b=2)`
- Includes original defaults via `apply_defaults()` → Trace-DSL flaunts comprehensive mappings outlining argument states.
- Yields to `"..."` as a fallback parameter if the system encounters failures querying signature metrics, like inspecting core C-extensions.

### Indentation Synchronization Examples

```python
@trace
def outer():
    # Logs >> with depth = 0
    # Steps up to depth = 1
    inner()
    # Returns down to depth = 0 and secures << log.

@trace
def inner():
    # Logs >> with depth = 1
    # Steps up to depth = 2
    return 42
    # Returns down to depth = 1 and secures << log.
```

DSL Output Equivalent:

```
>> outer()
  >> inner()
  << 42
<< None
```

### Design Decisions

| Decision | Alternative | Reason for Rejection |
|---|---|---|
| Adoption of `functools.wraps` | Non-Adoptive approach | Omitting `wraps` causes properties such as `func.__name__` and `func.__doc__` to be usurped by the wrapper functions. Decimates the legibility of documentation capabilities and debugging. |
| Hybrid Application of `inspect.signature` + `bind` | Direct exposition via `args`, `kwargs` | Failing to unify positional parameters inside keyword format yields outputs matching the likes of `foo(1, 2)`. Prohibits an embedded LLM from matching values into distinct parameters natively. |
| Mandatory Exception Propagation (`raise`) | Swallowing trace instances | Suppressing exceptions forces upstream application error handlers to collapse internally. Bribing user applications goes starkly against TraceLog’s core unyielding covenant. |
| Constructive Opt-In Nature in `@trace` | Default Automatic AST Injections | AST injections inflate development complexity profiles and bloat overarching build dependencies. Conscious manual selection eliminates erratic behavior scenarios natively. |
| Initial Forfeiture of async capabilities in Phase 1 | Direct application attempts | Timing increments of `increase_depth`/`decrease_depth` behaves irrationally amidst the confines of `asyncio.coroutine`. Guaranteed for execution inside Phase 2 leveraging autonomous `async def wrapper` fork paths. |

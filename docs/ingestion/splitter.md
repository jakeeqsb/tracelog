# splitter.py — Design Document (Structural Chunking)

## Role and Purpose

`TraceTreeSplitter` is a structure-aware text splitter specialized for Trace-DSL.

Naive size-based splitting often separates the error line (`!!`) from its parent call context (`>> func`), which weakens downstream LLM analysis. `TraceTreeSplitter` accepts the unified Trace-DSL rendered by the Aggregator and injects the relevant parent call stack into error-containing chunks.

---

## Core Algorithm: Context-Injected Splitting

### What it is

The splitter parses the DSL tree, tracks the path leading to the error line, and injects that path into new chunks when needed.

### Main Steps

1. **Find the error path**: scan for `!!` and record the active `>>` call stack up to that point.
2. **Choose break points**: prefer top-level `>>` boundaries instead of arbitrary character positions.
3. **Inject context**: when a new chunk starts before the error has appeared, prepend the stored call path.

---

## Technical Characteristics

- **LangChain-compatible**: inherits from `TextSplitter`
- **Better clustering quality**: preserved context improves chunk quality for embeddings compared to generic splitters

---

## Interface

```python
class TraceTreeSplitter(TextSplitter):
    def split_text(self, text: str) -> List[str]:
        """Split Aggregator-rendered Trace-DSL into context-preserving chunks."""
```

---

## Break Point Strategy: Tiered Thresholds (Option B)

The splitter uses a tiered threshold system that relaxes the split condition as a chunk grows, preventing unbounded chunk sizes in deeply nested traces:

| Chunk size range | Allowed break point |
| --- | --- |
| `< 1.0x chunk_size` | No split |
| `1.0x – 1.5x chunk_size` | `>>` with `indent ≤ 2` (top-level only) |
| `1.5x – 2.0x chunk_size` | `>>` with `indent ≤ 4` (one level deeper) |
| `>= 2.0x chunk_size` | Any `>>` (hard cap) |

This means the effective maximum chunk size is `~2x chunk_size` (e.g., 2400 chars for `chunk_size=1200`). Uneven chunk sizes are intentional — semantic boundary preservation is prioritized over uniform size.

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| Two-pass scan | The splitter must know where the error is before it can decide which context to inject. |
| Comment-based marking | Injected lines can be marked so LLMs can distinguish them from original log lines. |
| Tiered break point thresholds | Prevents unbounded chunk growth in deeply nested traces while still preferring top-level boundaries. |

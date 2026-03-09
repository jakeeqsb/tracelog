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

## Design Decisions

| Decision | Reason |
| --- | --- |
| Two-pass scan | The splitter must know where the error is before it can decide which context to inject. |
| Comment-based marking | Injected lines can be marked so LLMs can distinguish them from original log lines. |
| Top-level call boundaries | Preserves larger logical units inside each chunk. |

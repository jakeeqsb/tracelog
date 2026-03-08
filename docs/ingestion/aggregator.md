# aggregator.py — Design Document (Context Healing)

## Role and Purpose

`aggregator` is the logical stage that weaves fragmented JSON dumps back into a coherent trace.

Modern Python applications often split execution across `asyncio`, thread pools, or worker boundaries. The Aggregator reconstructs those fragments using `trace_id`, `span_id`, and `parent_span_id`, then renders a single unified Trace-DSL text that is suitable for LLM consumption.

In the MVP, this is implemented as an ingestion-time preprocessing utility rather than a standalone service.

---

## Core Mechanism: JSON Dump-Based Reconstruction

### What it is

Every JSON dump contains `trace_id`, `span_id`, and `parent_span_id`. The Aggregator uses these identifiers to rebuild the span tree. The dump's `dsl_lines` remain untouched until the final rendering phase.

### Why it is needed

- **Asynchronous causality recovery**: when a parent coroutine hands work to a child task, the Aggregator restores the chain so the starting point of a failure remains visible.
- **Better LLM context**: a complete execution tree provides much better root-cause context than isolated log fragments.

---

## Design and Data Flow

### 1. Collection

The SDK `Exporter` emits JSON dumps. At minimum, each dump contains:

```json
{
  "trace_id": "123",
  "span_id": "BBBB",
  "parent_span_id": "AAAA",
  "timestamp": "2026-03-08T10:00:00Z",
  "dsl_lines": [
    ">> send_email(user=\"jake@example.com\")",
    "!! ConnectionError: SMTP server unreachable"
  ]
}
```

### 2. Linkage

- Group dumps by `trace_id`
- Map child spans using `parent_span_id`

### 3. Reconstruction

Start from the root span and walk the span tree with DFS. At this stage, the Aggregator does not parse the text body to find relationships. It only determines how the dump fragments should be ordered in the final trace.

### 4. Rendering

Once the tree is reconstructed, render one final Trace-DSL text by adjusting indentation and placement. Rendering should use normalized whitespace indentation (`2 spaces * depth`) rather than repeated visual branch markers such as `|--`. JSON dump is the assembly format. Trace-DSL is the final presentation format.

---

## Utility Interface

```python
def aggregate_dumps(dumps: List[TraceDump]) -> str:
    """Return one unified Trace-DSL string from fragmented JSON dumps."""
```

---

## Example

### Scenario: async email worker fails during payment processing

#### Fragment A: main thread JSON dump

```json
{
  "trace_id": "123",
  "span_id": "AAAA",
  "parent_span_id": null,
  "dsl_lines": [
    ">> process_payment(order_id=\"ORD-1\")",
    ".. [INFO] Validating payment",
    ".. [INFO] Spawning email worker...",
    "<< \"Payment complete\""
  ]
}
```

#### Fragment B: worker thread JSON dump

```json
{
  "trace_id": "123",
  "span_id": "BBBB",
  "parent_span_id": "AAAA",
  "dsl_lines": [
    ">> send_email(user=\"jake@example.com\")",
    "!! ConnectionError: SMTP server unreachable"
  ]
}
```

### Unified output rendered by the Aggregator

```text
=== [TraceLog] Unified Trace (trace_id: 123) ===
>> process_payment(order_id="ORD-1")
.. [INFO] Validating payment
.. [INFO] Spawning email worker...
  >> send_email(user="jake@example.com")
  !! ConnectionError: SMTP server unreachable
<< "Payment complete"
```

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| Ingestion-time utility | Keeps the MVP small and avoids operating a separate Aggregator service. |
| JSON dump input | Eliminates the need to reparse textual dump headers just to recover identifiers. |
| DFS tree reconstruction | Plain timestamp ordering cannot guarantee causality in asynchronous execution. |
| Render-late strategy | Persist assembly-friendly dumps first and render human-readable DSL only once at the end. |
| Whitespace indentation over `|--` markers | Deep traces remain easier to read, cheaper in tokens, and closer to the original Trace-DSL style. |

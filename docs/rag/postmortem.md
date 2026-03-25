# Incident & Postmortem Data Model — Design Document

## Overview

The RAG knowledge base stores two distinct node types: **INCIDENT** and **POSTMORTEM**.
They are linked by a shared `incident_id` field and stored as separate points in the VectorStore.

This separation allows incidents to be ingested immediately at error time, while resolution
data is added later — after an engineer has confirmed the fix.

---

## Data Model

### INCIDENT node

Created automatically when an error dump arrives from the SDK.

```json
{
  "node_type": "incident",
  "incident_id": "inc_20260310_a1b2c3",
  "tracetree_chunk": "=== DUMP ...\n!! TypeError: ...",
  "timestamp": "2026-03-10T14:32:00Z",
  "service": "warehouse-sync",
  "error_type": "TypeError",
  "status": "open"
}
```

### POSTMORTEM node

Created by an engineer after the incident is resolved.
Not embedded as a vector — stored as a payload-only point linked via `incident_id`.

```json
{
  "node_type": "postmortem",
  "incident_id": "inc_20260310_a1b2c3",
  "root_cause": "fetch_inventory returns string '100 ea' instead of int",
  "fix": "Added int() cast with ERP response validation in fetch_inventory()",
  "action": "Created task to add ERP schema validation at ingestion boundary",
  "resolved_at": "2026-03-10T16:00:00Z"
}
```

---

## Ingestion Lifecycle

```
[Incident occurs]
    SDK FileExporter writes tracelog.jsonl
        ↓
    Aggregator assembles unified Trace-DSL
        ↓
    TraceLogIndexer creates INCIDENT node → VectorStore
        status: "open"

[Engineer resolves the incident]
    Engineer confirms root_cause and fix
        ↓
    `tracelog postmortem commit --incident-id inc_001 ...`
        ↓
    POSTMORTEM node created → VectorStore (linked via incident_id)
    INCIDENT node status updated → "resolved"
```

---

## Retrieval

When a new incident arrives:

1. The current tracetree is embedded and used to search for similar INCIDENT nodes.
2. For each matched INCIDENT, the store is queried for a linked POSTMORTEM (`incident_id` filter).
3. The LLM receives: current tracetree + past tracetree + past root_cause + past fix.

```
No linked POSTMORTEM found:
    LLM: "Similar incident found but no resolution recorded yet."

Linked POSTMORTEM found:
    LLM: "Similar incident — past root cause was X, fix was Y."
```

---

## Similar Incident Links

Similarity between incidents is determined at retrieval time via vector distance —
no explicit `similar_to` edges are stored.

If explicit linkage becomes necessary (e.g. for recurring pattern dashboards),
a `similar_incident_ids` payload field can be added without changing the schema.

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| Separate nodes for incident and postmortem | Incident is available immediately; postmortem comes later — merging them would block ingestion |
| `incident_id` as link key | Simple equality filter; no graph DB required |
| Postmortem is payload-only (not embedded) | Resolution text should not dilute the incident's semantic vector |
| `status` field on INCIDENT | Enables filtering to only open or only resolved incidents |

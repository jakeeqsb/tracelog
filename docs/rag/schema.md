# TraceLog RAG — Schema Design

> Use case details: [usecases.md](usecases.md)

## MVP Core Loop

```
[Error occurs]
   ↓  SDK auto-generates dump file via FileExporter
   ↓
tracelog index ./dumps/
   ↓  INCIDENT node created in Qdrant for each dump chunk
   ↓
tracelog diagnose ./dumps/new_error.log
   ↓  Finds semantically similar past INCIDENTs
   ↓  Loads any linked POSTMORTEM (root cause + fix)
   ↓  LLM produces diagnosis → printed to terminal
   ↓
Engineer applies fix
   ↓
tracelog postmortem commit --incident-id <id> --root-cause "..." --fix "..."
   ↓  POSTMORTEM node created, INCIDENT status → resolved
   ↓
Next occurrence of same error → diagnose returns prior root cause and fix
```

---

## Collection Design

Two separate collections. INCIDENT nodes are searched semantically (find
similar past errors). POSTMORTEM nodes are looked up by key (fetch the fix
linked to a specific incident). These are different access patterns with
different vector needs, so they live in separate collections.

| Collection | Purpose | Vector |
| --- | --- | --- |
| `tracelog_incidents` | Stores TraceTree chunks from error dumps | Dense (cosine, 1536-dim) |
| `tracelog_postmortems` | Stores root cause and fix for resolved incidents | None — payload-only key lookup |

---

## Payload Schema

### INCIDENT node (`tracelog_incidents`)

| Field | Type | Description |
| --- | --- | --- |
| `incident_id` | `string` | Deterministic ID: `"{file_name}::{chunk_index}"`. Shared with linked POSTMORTEM. |
| `error_type` | `string` | Exception class extracted from dump file name (e.g. `ValueError`). |
| `file_name` | `string` | Source dump file name. |
| `chunk_index` | `int` | Index of this chunk within the dump file. |
| `chunk_text` | `string` | Raw TraceTree chunk text. |
| `has_error` | `bool` | `true` if the chunk contains a `!!` error marker. |
| `occurred_at` | `string` | ISO-8601 timestamp derived from dump file mtime. |
| `status` | `string` | `"open"` on creation. Updated to `"resolved"` when POSTMORTEM is committed. |

### POSTMORTEM node (`tracelog_postmortems`)

| Field | Type | Description |
| --- | --- | --- |
| `incident_id` | `string` | Links this POSTMORTEM to its INCIDENT node. |
| `root_cause` | `string` | Engineer-written root cause description. |
| `fix` | `string` | Description of the fix applied. |
| `resolved_at` | `string` | ISO-8601 timestamp of when `postmortem commit` was run. |

---

## Payload Indexes

Fields used in payload filters must be indexed for O(log n) lookup instead
of full collection scan.

### `tracelog_incidents`

| Field | Index type | Used by |
| --- | --- | --- |
| `incident_id` | `keyword` | Linked POSTMORTEM retrieval |
| `error_type` | `keyword` | `filter_error_type` in retriever |
| `has_error` | `bool` | `only_error_chunks` filter in retriever |
| `status` | `keyword` | Filter open vs resolved incidents |

### `tracelog_postmortems`

| Field | Index type | Used by |
| --- | --- | --- |
| `incident_id` | `keyword` | Fetch linked POSTMORTEM after INCIDENT search |

---

## ID Strategy

Qdrant points require a `uint64` or UUID as ID.

**INCIDENT** — deterministic `uint64` derived from file name and chunk index:

```python
incident_id = f"{file_name}::{chunk_index}"   # payload field (string)
point_id = abs(hash(incident_id)) % (10 ** 18)  # Qdrant point ID (uint64)
```

**POSTMORTEM** — deterministic `uint64` derived from `incident_id`:

```python
point_id = abs(hash(f"postmortem::{incident_id}")) % (10 ** 18)
```

---

## Linking Strategy

Qdrant has no foreign keys. INCIDENT and POSTMORTEM are linked by the
`incident_id` payload field.

**Retrieval flow at diagnose time:**

```
1. Embed query chunk
2. Search tracelog_incidents  (dense cosine, filter: has_error=true)
3. For each returned INCIDENT, extract incident_id from payload
4. Filter tracelog_postmortems where incident_id IN [retrieved ids]
5. Return INCIDENT + matched POSTMORTEM pairs to diagnoser
```

Step 4 is a payload filter lookup (no vector search), so it is fast regardless
of collection size.

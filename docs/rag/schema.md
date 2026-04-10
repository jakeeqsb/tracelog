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

Two separate collections, each with its own vector space.

INCIDENT nodes embed TraceTree execution structure — used to find structurally
similar past errors. POSTMORTEM nodes embed resolution text (root cause + fix)
— used to find similar past solutions. These two text types occupy different
semantic spaces, so mixing them in a single collection would degrade retrieval
quality for both.

| Collection | Purpose | Embedded text | Vector |
| --- | --- | --- | --- |
| `tracelog_incidents` | TraceTree chunks from error dumps | `chunk_text` (Trace-DSL) | Dense cosine, 1536-dim |
| `tracelog_postmortems` | Root cause and fix for resolved incidents | `root_cause + "\n" + fix` | Dense cosine, 1536-dim |

---

## Collection Creation Parameters

### `tracelog_incidents`

```python
client.create_collection(
    collection_name="tracelog_incidents",
    vectors_config=VectorParams(
        size=1536,
        distance=Distance.COSINE,
        on_disk=False,       # in-memory for MVP; set True for production
    ),
    hnsw_config=HnswConfigDiff(
        m=16,                # default — no tuning evidence yet
        ef_construct=100,
    ),
)
```

### `tracelog_postmortems`

```python
client.create_collection(
    collection_name="tracelog_postmortems",
    vectors_config=VectorParams(
        size=1536,
        distance=Distance.COSINE,
        on_disk=False,
    ),
    hnsw_config=HnswConfigDiff(
        m=16,
        ef_construct=100,
    ),
)
```

Both collections use the same embedding model (`text-embedding-3-small`) and
distance metric. HNSW parameters use Qdrant defaults for MVP; tune when
collection size exceeds 10k points.

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

### Indexes — `tracelog_incidents`

| Field | Index type | Used by |
| --- | --- | --- |
| `incident_id` | `keyword` | Linked POSTMORTEM retrieval |
| `error_type` | `keyword` | `filter_error_type` in retriever |
| `has_error` | `bool` | `only_error_chunks` filter in retriever |
| `status` | `keyword` | Filter open vs resolved incidents |

### Indexes — `tracelog_postmortems`

| Field | Index type | Used by |
| --- | --- | --- |
| `incident_id` | `keyword` | Fetch linked POSTMORTEM after INCIDENT search |

---

## ID Strategy

Qdrant points require a `uint64` or UUID as ID.

**INCIDENT** — deterministic `uint64` derived from file name and chunk index:

```python
incident_id = f"{file_name}::{chunk_index}"          # payload field (string)
point_id = abs(hash(incident_id)) % (10 ** 18)       # Qdrant point ID (uint64)
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

Step 4 is a payload filter lookup (no vector search on postmortems at diagnose
time), so it is fast regardless of collection size.

**Independent POSTMORTEM search:**

```
1. Embed query text (e.g. "fix for card number validation failure")
2. Search tracelog_postmortems  (dense cosine)
3. Return matching root_cause + fix entries
```

This path enables a future "search past fixes" use case without changing the
collection structure.

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| Two separate collections | chunk_text (Trace-DSL) and root_cause+fix (natural language) occupy different semantic spaces — mixing them degrades retrieval quality |
| POSTMORTEM also has a vector | Enables independent semantic search on past resolutions; payload-only would block future "find similar fix" use cases |
| Same embedding model for both | Simplifies the ingestion pipeline; acceptable because the two collections are never searched together |
| HNSW defaults for MVP | No evidence yet that tuning is needed; revisit at >10k points |

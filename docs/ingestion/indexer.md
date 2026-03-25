# indexer.py — Design Document (RAG Indexing)

## Role and Purpose

`TraceLogIndexer` embeds chunks produced after aggregation and splitting, then stores them via a `VectorStore` adapter for retrieval.

Beyond storing plain text, it also persists metadata payloads such as error type and file name so later retrieval can combine semantic similarity with filtering.

The Indexer depends on the `VectorStore` Protocol (`tracelog/rag/store.py`) rather than any specific database client. The concrete backend (Qdrant, ChromaDB, etc.) is injected at construction time.

---

## Core Design Elements

### 1. Embedding Strategy

- **Model**: `OpenAI text-embedding-3-small` (1536 dimensions)
- **Rationale**: captures Trace-DSL structure and error patterns as semantic vectors

### 2. Metadata Payload

Each INCIDENT point stores:

| Field | Description |
| --- | --- |
| `node_type` | `"incident"` |
| `incident_id` | Unique identifier shared with its linked POSTMORTEM |
| `error_type` | Exception class name extracted from the tracetree |
| `file_name` | Source file where the error surfaced |
| `has_error` | Boolean flag for payload filtering |
| `chunk_text` | Raw TraceTree chunk text |
| `timestamp` | ISO-8601 timestamp of the error dump |
| `service` | Service name (if available) |
| `status` | `"open"` initially; updated to `"resolved"` when POSTMORTEM is linked |

### 3. Deterministic IDs

Re-indexing the same source should avoid duplicates, so the Indexer uses deterministic identifiers together with Qdrant `upsert`.

---

## Data Flow

1. **Input**: JSON dump fragments emitted by the SDK, or a unified Trace-DSL file rendered by the Aggregator
2. **Aggregation**: when needed, assemble fragments by `trace_id`, `span_id`, and `parent_span_id`
3. **Chunking**: split the unified trace with `TraceTreeSplitter`
4. **Embedding**: convert chunks into vectors through OpenAI
5. **Storage**: `upsert` vectors and payloads into Qdrant

---

## Technology Choices

| Component | Choice | Reason |
| --- | --- | --- |
| Storage interface | `VectorStore` Protocol | Decouples indexing logic from DB vendor |
| Default backend | Qdrant | Strong payload filtering and hybrid search |
| Local-first backend | ChromaDB | No server required; zero setup for development |
| Distance | Cosine similarity | Fits semantic comparison of DSL patterns |
| Batch size | Auto-tuned | Balances OpenAI API latency and cost |

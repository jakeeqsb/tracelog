# indexer.py — Design Document (RAG Indexing)

## Role and Purpose

`TraceLogIndexer` embeds chunks produced after aggregation and splitting, then stores them in Qdrant for retrieval.

Beyond storing plain text, it also persists metadata payloads such as error type and file name so later retrieval can combine semantic similarity with filtering.

---

## Core Design Elements

### 1. Embedding Strategy

- **Model**: `OpenAI text-embedding-3-small` (1536 dimensions)
- **Rationale**: captures Trace-DSL structure and error patterns as semantic vectors

### 2. Metadata Payload

Each point stores:

- `error_type`
- `file_name`
- `has_error`
- `chunk_text`

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
| Vector DB | Qdrant | Strong payload filtering and easy local testing |
| Distance | Cosine similarity | Fits semantic comparison of DSL patterns |
| Batch size | Auto-tuned | Balances OpenAI API latency and cost |

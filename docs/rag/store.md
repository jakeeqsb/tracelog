# VectorStore Abstraction — Design Document

## Role and Purpose

`VectorStore` is a `Protocol`-based interface defined in `tracelog/rag/store.py`.

It decouples all RAG logic (`indexer.py`, `retriever.py`) from any specific vector database client.
Swapping the backend requires only injecting a different adapter — no changes to indexing or retrieval code.

---

## Interface

```python
class VectorStore(Protocol):
    def upsert(
        self,
        ids: list[str],
        vectors: list[list[float]],
        payloads: list[dict],
    ) -> None: ...

    def search(
        self,
        vector: list[float],
        top_k: int,
        filter: dict | None = None,
    ) -> list[dict]: ...

    def fetch_by_filter(
        self,
        filter: dict,
    ) -> list[dict]: ...

    def count(self) -> int: ...
```

- `search` — semantic similarity search; vector is required. Returns payload dicts each including at minimum `chunk_text` and `score`.
- `fetch_by_filter` — exact payload filter lookup with no vector; returns all matching payload dicts. Used when the caller has a known key (e.g. `incident_id`) and does not need similarity ranking.
- `count` — total number of stored points.

---

## Adapters

### QdrantStore (`tracelog/rag/stores/qdrant.py`) — default

- Wraps `qdrant_client.QdrantClient`
- Supports in-memory (`:memory:`), local file, and remote server modes
- Default backend for production use

#### `fetch_by_filter` implementation

Uses Qdrant `scroll()` — filter-only retrieval without a query vector:

```python
def fetch_by_filter(self, filter: dict) -> list[dict]:
    qdrant_filter = self._build_filter(filter)
    results, _ = self._client.scroll(
        collection_name=self.collection_name,
        scroll_filter=qdrant_filter,
        with_payload=True,
        with_vectors=False,
        limit=100,
    )
    return [point.payload for point in results]
```

`scroll()` is the correct Qdrant API for this pattern — `query_points()` requires
a vector, `scroll()` does not.

#### `_ensure_collection` — full spec

Collection creation must include HNSW config and payload index creation.
Payload indexes must be created after `create_collection()`:

```python
from qdrant_client.models import (
    Distance, HnswConfigDiff, PayloadSchemaType, VectorParams,
)

def _ensure_collection(self) -> None:
    existing = {c.name for c in self._client.get_collections().collections}
    if self.collection_name not in existing:
        self._client.create_collection(
            collection_name=self.collection_name,
            vectors_config=VectorParams(
                size=self.vector_dim,
                distance=Distance.COSINE,
                on_disk=False,
            ),
            hnsw_config=HnswConfigDiff(
                m=16,
                ef_construct=100,
            ),
        )
        self._create_payload_indexes()

def _create_payload_indexes(self) -> None:
    ...  # see per-collection index spec below
```

#### Payload indexes — per collection

**`tracelog_incidents`**

```python
for field in ("incident_id", "error_type", "status"):
    self._client.create_payload_index(
        collection_name=self.collection_name,
        field_name=field,
        field_schema=PayloadSchemaType.KEYWORD,
    )
self._client.create_payload_index(
    collection_name=self.collection_name,
    field_name="has_error",
    field_schema=PayloadSchemaType.BOOL,
)
```

**`tracelog_postmortems`**

```python
self._client.create_payload_index(
    collection_name=self.collection_name,
    field_name="incident_id",
    field_schema=PayloadSchemaType.KEYWORD,
)
```

`_create_payload_indexes` should branch on `self.collection_name` to apply the
correct index set. Alternatively, the caller can pass the index spec at
construction time — the implementation choice is left to the Software Engineer.

---

## Usage

Two stores are instantiated independently — one per collection:

```python
from tracelog.rag.stores.qdrant import QdrantStore

incident_store   = QdrantStore(collection_name="tracelog_incidents")
postmortem_store = QdrantStore(collection_name="tracelog_postmortems")
```

**Diagnose flow** — INCIDENT similarity search, then linked POSTMORTEM exact lookup:

```python
# 1. find similar past incidents
similar = incident_store.search(query_vector, top_k=5, filter={"has_error": True})

# 2. fetch linked postmortem for each matched incident
for incident in similar:
    postmortems = postmortem_store.fetch_by_filter({"incident_id": incident["incident_id"]})
```

**Independent postmortem search** — find similar past fixes:

```python
results = postmortem_store.search(embed("card number validation failure"), top_k=5)
```

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| Protocol over ABC | No forced inheritance; any object with matching methods qualifies |
| `fetch_by_filter` separate from `search` | `search` requires a vector; exact key lookup (e.g. `incident_id`) should not require a dummy vector — the two access patterns have different semantics |
| Two stores, one Protocol | `tracelog_incidents` and `tracelog_postmortems` use the same interface but are independent instances — no special multi-collection abstraction needed |
| Payload as `dict` | Backend-neutral; avoids importing vendor-specific model classes in caller code |

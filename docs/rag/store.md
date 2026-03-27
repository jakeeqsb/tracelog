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
```

`search` returns a list of payload dicts, each including at minimum `chunk_text` and `score`.

---

## Adapters

### QdrantStore (`tracelog/rag/stores/qdrant.py`) — default

- Wraps `qdrant_client.QdrantClient`
- Supports in-memory (`:memory:`), local file, and remote server modes
- Enables hybrid search (dense + BM25 sparse) via Qdrant's native support
- Default backend for production use

---

## Usage

```python
from tracelog.rag.stores.qdrant import QdrantStore
from tracelog.rag.indexer import TraceLogIndexer

store = QdrantStore(collection_name="tracelog")
indexer = TraceLogIndexer(store=store)
```

---

## Design Decisions

| Decision | Reason |
| --- | --- |
| Protocol over ABC | No forced inheritance; any object with `upsert` + `search` qualifies |
| Two-method surface | Keeps adapters thin and easy to implement |
| Payload as `dict` | Backend-neutral; avoids importing vendor-specific model classes in caller code |

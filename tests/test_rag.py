"""Unit tests for the RAG pipeline.

Covers:
    - VectorStore Protocol conformance check
    - QdrantStore: collection creation, upsert, search, count, filter
    - TraceLogIndexer: file indexing, directory indexing, error-type extraction
    - TraceLogRetriever: search delegation, filter building, result mapping
    - TraceLogDiagnoser: prompt building, JSON parse, parse-error fallback
"""

import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from tracelog.rag.store import VectorStore
from tracelog.rag.stores.qdrant import QdrantStore
from tracelog.rag.indexer import TraceLogIndexer
from tracelog.rag.retriever import TraceLogRetriever, RetrievedChunk
from tracelog.rag.diagnoser import TraceLogDiagnoser


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

SAMPLE_DSL = """\
>> outer_fn
  >> inner_fn
    !! ValueError: bad input
  << inner_fn
<< outer_fn
"""


class InMemoryStore:
    """Minimal VectorStore implementation for testing (no Qdrant dependency)."""

    def __init__(self):
        self._points: list[dict] = []

    def upsert(self, ids, vectors, payloads) -> None:
        for id_, vec, payload in zip(ids, vectors, payloads):
            self._points.append({"id": id_, "vector": vec, "payload": payload})

    def search(self, vector, top_k, filter=None) -> list[dict]:
        results = self._points
        if filter:
            results = [
                p for p in results
                if all(p["payload"].get(k) == v for k, v in filter.items())
            ]
        return [
            {"score": 1.0, **p["payload"]}
            for p in results[:top_k]
        ]

    def count(self) -> int:
        return len(self._points)


# ---------------------------------------------------------------------------
# VectorStore Protocol
# ---------------------------------------------------------------------------

class TestVectorStoreProtocol:
    def test_in_memory_store_satisfies_protocol(self):
        store = InMemoryStore()
        assert isinstance(store, VectorStore)

    def test_object_missing_count_does_not_satisfy_protocol(self):
        class Incomplete:
            def upsert(self, ids, vectors, payloads): ...
            def search(self, vector, top_k, filter=None): ...

        assert not isinstance(Incomplete(), VectorStore)


# ---------------------------------------------------------------------------
# QdrantStore
# ---------------------------------------------------------------------------

class TestQdrantStore:
    """Tests QdrantStore using the in-memory Qdrant client (no server needed)."""

    def _make_store(self, collection_name: str | None = None) -> QdrantStore:
        # Force in-memory mode regardless of QDRANT_URL in the environment.
        # Use a unique collection name per call to prevent cross-test data leakage.
        name = collection_name or f"test_{uuid.uuid4().hex}"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("QDRANT_URL", None)
            return QdrantStore(collection_name=name)

    def test_store_satisfies_protocol(self):
        store = self._make_store()
        assert isinstance(store, VectorStore)

    def test_count_starts_at_zero(self):
        store = self._make_store()
        assert store.count() == 0

    def test_upsert_increments_count(self):
        store = self._make_store()
        store.upsert(
            ids=[1],
            vectors=[[0.0] * 1536],
            payloads=[{"has_error": True, "chunk_text": "hello"}],
        )
        assert store.count() == 1

    def test_upsert_is_idempotent_same_id(self):
        store = self._make_store()
        store.upsert(ids=[1], vectors=[[0.0] * 1536], payloads=[{"v": "a"}])
        store.upsert(ids=[1], vectors=[[0.0] * 1536], payloads=[{"v": "b"}])
        assert store.count() == 1

    def test_search_returns_top_k_results(self):
        store = self._make_store()
        for i in range(5):
            store.upsert(
                ids=[i],
                vectors=[[float(i)] + [0.0] * 1535],
                payloads=[{"has_error": True, "chunk_text": f"chunk {i}"}],
            )
        results = store.search(vector=[1.0] + [0.0] * 1535, top_k=3)
        assert len(results) == 3

    def test_search_result_includes_score(self):
        store = self._make_store()
        store.upsert(
            ids=[1],
            vectors=[[1.0] + [0.0] * 1535],
            payloads=[{"has_error": True, "chunk_text": "err chunk"}],
        )
        results = store.search(vector=[1.0] + [0.0] * 1535, top_k=1)
        assert "score" in results[0]

    def test_search_filter_by_has_error(self):
        store = self._make_store()
        store.upsert(ids=[1], vectors=[[1.0] + [0.0] * 1535], payloads=[{"has_error": True,  "chunk_text": "err"}])
        store.upsert(ids=[2], vectors=[[0.5] + [0.0] * 1535], payloads=[{"has_error": False, "chunk_text": "ok"}])

        results = store.search(
            vector=[1.0] + [0.0] * 1535,
            top_k=5,
            filter={"has_error": True},
        )
        assert all(r["has_error"] is True for r in results)
        assert len(results) == 1

    def test_two_collections_are_independent(self):
        store_a = self._make_store("col_a")
        store_b = self._make_store("col_b")
        store_a.upsert(ids=[1], vectors=[[0.0] * 1536], payloads=[{"x": 1}])
        assert store_b.count() == 0


# ---------------------------------------------------------------------------
# TraceLogIndexer
# ---------------------------------------------------------------------------

def _make_mock_embeddings() -> MagicMock:
    """Returns a mock Embeddings backend that returns fixed 1536-dim vectors."""
    mock = MagicMock(spec=Embeddings)
    mock.embed_documents.side_effect = lambda texts: [[0.1] * 1536 for _ in texts]
    mock.embed_query.return_value = [0.1] * 1536
    return mock


def _make_mock_llm(response_payload: dict | None = None) -> MagicMock:
    """Returns a mock BaseChatModel with a fixed AIMessage response."""
    mock = MagicMock(spec=BaseChatModel)
    mock.model_name = "gpt-4o-mini"
    content = json.dumps(response_payload or {"root_cause_function": "fn"})
    mock.invoke.return_value = AIMessage(
        content=content,
        usage_metadata={"input_tokens": 100, "output_tokens": 50, "total_tokens": 150},
    )
    return mock


class TestTraceLogIndexer:
    def _make_indexer(self) -> tuple[TraceLogIndexer, InMemoryStore]:
        store = InMemoryStore()
        indexer = TraceLogIndexer(store=store, embeddings=_make_mock_embeddings())
        return indexer, store

    def test_index_file_returns_chunk_count(self):
        indexer, store = self._make_indexer()

        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", delete=False) as f:
            f.write(SAMPLE_DSL)
            path = Path(f.name)

        count = indexer.index_file(path)
        assert count > 0
        assert store.count() == count

    def test_index_file_stores_correct_metadata(self):
        indexer, store = self._make_indexer()

        with tempfile.NamedTemporaryFile(
            suffix=".log", prefix="ValueError", mode="w", delete=False
        ) as f:
            f.write(SAMPLE_DSL)
            path = Path(f.name)

        indexer.index_file(path)
        point = store._points[0]["payload"]
        assert "chunk_text" in point
        assert "has_error" in point
        assert "file_name" in point
        assert "chunk_index" in point

    def test_index_empty_file_returns_zero(self):
        indexer, store = self._make_indexer()
        indexer.splitter.split_text = lambda text: []

        with tempfile.NamedTemporaryFile(suffix=".log", mode="w", delete=False) as f:
            f.write("")
            path = Path(f.name)

        count = indexer.index_file(path)
        assert count == 0
        assert store.count() == 0

    def test_index_directory_sums_all_files(self):
        indexer, store = self._make_indexer()

        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(3):
                p = Path(tmpdir) / f"dump{i}.log"
                p.write_text(SAMPLE_DSL)

            total = indexer.index_directory(Path(tmpdir))
            assert total == store.count()
            assert total > 0

    def test_extract_error_type_known_prefix(self):
        indexer, _ = self._make_indexer()
        assert indexer._extract_error_type("ValueError_2024.log") == "ValueError"
        assert indexer._extract_error_type("TimeoutError_dump.log") == "TimeoutError"

    def test_extract_error_type_unknown_prefix(self):
        indexer, _ = self._make_indexer()
        assert indexer._extract_error_type("unknown_dump.log") == "Unknown"

    def test_count_delegates_to_store(self):
        indexer, store = self._make_indexer()
        # Manually insert a point
        store._points.append({"id": 99, "vector": [], "payload": {}})
        assert indexer.count() == 1


# ---------------------------------------------------------------------------
# TraceLogRetriever
# ---------------------------------------------------------------------------

class TestTraceLogRetriever:
    def _make_retriever(self, store=None) -> TraceLogRetriever:
        if store is None:
            store = InMemoryStore()
        return TraceLogRetriever(store=store, embeddings=_make_mock_embeddings())

    def _seed_store(self, store: InMemoryStore, n=3, has_error=True):
        for i in range(n):
            store.upsert(
                ids=[i],
                vectors=[[0.1] * 1536],
                payloads=[{
                    "chunk_text": f">> fn_{i} !! Error {i}" if has_error else f">> fn_{i}",
                    "error_type": "ValueError",
                    "file_name": f"file_{i}.log",
                    "chunk_index": i,
                    "has_error": has_error,
                }],
            )

    def test_search_returns_retrieved_chunk_list(self):
        store = InMemoryStore()
        self._seed_store(store)
        retriever = self._make_retriever(store)
        results = retriever.search("!! Error", top_k=3)
        assert isinstance(results, list)
        assert all(isinstance(r, RetrievedChunk) for r in results)

    def test_search_respects_top_k(self):
        store = InMemoryStore()
        self._seed_store(store, n=5)
        retriever = self._make_retriever(store)
        results = retriever.search("!! Error", top_k=2)
        assert len(results) <= 2

    def test_search_only_error_chunks_filters_correctly(self):
        store = InMemoryStore()
        self._seed_store(store, n=2, has_error=True)
        self._seed_store(store, n=2, has_error=False)
        retriever = self._make_retriever(store)
        results = retriever.search("!! Error", top_k=10, only_error_chunks=True)
        assert all(r.has_error for r in results)

    def test_search_no_filter_when_only_error_chunks_false(self):
        store = InMemoryStore()
        self._seed_store(store, n=2, has_error=False)
        retriever = self._make_retriever(store)
        results = retriever.search("query", top_k=10, only_error_chunks=False)
        assert len(results) == 2

    def test_search_maps_fields_to_retrieved_chunk(self):
        store = InMemoryStore()
        self._seed_store(store, n=1)
        retriever = self._make_retriever(store)
        result = retriever.search("!! Error", top_k=1)[0]
        assert hasattr(result, "score")
        assert hasattr(result, "chunk_text")
        assert hasattr(result, "error_type")
        assert hasattr(result, "file_name")
        assert hasattr(result, "chunk_index")
        assert hasattr(result, "has_error")

    def test_embed_calls_embeddings_backend(self):
        store = InMemoryStore()
        mock_embeddings = _make_mock_embeddings()
        retriever = TraceLogRetriever(store=store, embeddings=mock_embeddings)
        retriever.search("query", top_k=1, only_error_chunks=False)
        mock_embeddings.embed_query.assert_called_once_with("query")


# ---------------------------------------------------------------------------
# TraceLogDiagnoser
# ---------------------------------------------------------------------------

class TestTraceLogDiagnoser:
    def _make_diagnoser(self, payload: dict | None = None) -> TraceLogDiagnoser:
        return TraceLogDiagnoser(llm=_make_mock_llm(payload))

    def _make_chunk(self, i=0) -> RetrievedChunk:
        return RetrievedChunk(
            score=0.9,
            chunk_text=f">> fn_{i} !! Error",
            error_type="ValueError",
            file_name=f"file_{i}.log",
            chunk_index=i,
            has_error=True,
        )

    def test_diagnose_returns_parsed_json(self):
        payload = {"root_cause_function": "fn_0", "confidence": "high"}
        diagnoser = self._make_diagnoser(payload)
        result = diagnoser.diagnose("!! Error", [self._make_chunk()])
        assert result["root_cause_function"] == "fn_0"
        assert result["confidence"] == "high"

    def test_diagnose_appends_meta(self):
        diagnoser = self._make_diagnoser()
        result = diagnoser.diagnose("!! Error", [])
        assert "_meta" in result
        assert "model" in result["_meta"]
        assert "input_tokens" in result["_meta"]
        assert "output_tokens" in result["_meta"]

    def test_diagnose_parse_error_fallback(self):
        mock_llm = MagicMock(spec=BaseChatModel)
        mock_llm.model_name = "gpt-4o-mini"
        mock_llm.invoke.return_value = AIMessage(
            content="not valid json at all",
            usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        )
        diagnoser = TraceLogDiagnoser(llm=mock_llm)
        result = diagnoser.diagnose("!! Error", [])
        assert result.get("parse_error") is True
        assert "raw_response" in result

    def test_build_context_includes_similar_chunks(self):
        diagnoser = self._make_diagnoser()
        chunks = [self._make_chunk(i) for i in range(2)]
        context = diagnoser._build_context("!! current error", chunks)
        assert "PAST SIMILAR INCIDENTS" in context
        assert "Past Incident #1" in context
        assert "Past Incident #2" in context
        assert "CURRENT ERROR" in context
        assert "!! current error" in context

    def test_build_context_no_similar_chunks(self):
        diagnoser = self._make_diagnoser()
        context = diagnoser._build_context("!! current error", [])
        assert "PAST SIMILAR INCIDENTS" not in context
        assert "CURRENT ERROR" in context

    def test_diagnose_similar_chunks_used_in_meta(self):
        diagnoser = self._make_diagnoser()
        chunks = [self._make_chunk(i) for i in range(3)]
        result = diagnoser.diagnose("!! Error", chunks)
        assert result["_meta"]["similar_chunks_used"] == 3

    def test_diagnose_calls_llm_invoke(self):
        mock_llm = _make_mock_llm()
        diagnoser = TraceLogDiagnoser(llm=mock_llm)
        diagnoser.diagnose("!! Error", [])
        mock_llm.invoke.assert_called_once()

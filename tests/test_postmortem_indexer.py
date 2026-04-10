"""Unit tests for PostmortemIndexer."""

from unittest.mock import MagicMock

import pytest
from langchain_core.embeddings import Embeddings

from tracelog.rag.postmortem_indexer import PostmortemIndexer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class InMemoryStore:
    def __init__(self):
        self._points: list[dict] = []

    def upsert(self, ids, vectors, payloads) -> None:
        for id_, vec, payload in zip(ids, vectors, payloads):
            existing = next((p for p in self._points if p["id"] == id_), None)
            if existing:
                existing["payload"] = payload
            else:
                self._points.append({"id": id_, "vector": vec, "payload": payload})

    def search(self, vector, top_k, filter=None) -> list[dict]:
        return []

    def fetch_by_filter(self, filter: dict) -> list[dict]:
        return [
            p["payload"]
            for p in self._points
            if all(p["payload"].get(k) == v for k, v in filter.items())
        ]

    def count(self) -> int:
        return len(self._points)


def _make_mock_embeddings() -> MagicMock:
    mock = MagicMock(spec=Embeddings)
    mock.embed_query.return_value = [0.1] * 1536
    return mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPostmortemIndexer:
    def _make_indexer(self) -> tuple[PostmortemIndexer, InMemoryStore]:
        store = InMemoryStore()
        indexer = PostmortemIndexer(store=store, embeddings=_make_mock_embeddings())
        return indexer, store

    def test_commit_stores_one_point(self):
        indexer, store = self._make_indexer()
        indexer.commit(
            incident_id="err.log::0",
            root_cause="missing int cast",
            fix="added int() at boundary",
        )
        assert store.count() == 1

    def test_commit_payload_fields(self):
        indexer, store = self._make_indexer()
        indexer.commit(
            incident_id="err.log::0",
            root_cause="missing int cast",
            fix="added int() at boundary",
        )
        payload = store._points[0]["payload"]
        assert payload["incident_id"] == "err.log::0"
        assert payload["root_cause"] == "missing int cast"
        assert payload["fix"] == "added int() at boundary"
        assert "resolved_at" in payload

    def test_commit_uses_deterministic_id(self):
        indexer, store = self._make_indexer()
        indexer.commit("err.log::0", "cause", "fix")
        indexer.commit("err.log::0", "cause updated", "fix updated")
        # Same incident_id → same deterministic point_id → upsert overwrites
        assert store.count() == 1
        assert store._points[0]["payload"]["root_cause"] == "cause updated"

    def test_commit_embeds_root_cause_and_fix(self):
        mock_embeddings = _make_mock_embeddings()
        store = InMemoryStore()
        indexer = PostmortemIndexer(store=store, embeddings=mock_embeddings)
        indexer.commit("err.log::0", "cause A", "fix B")
        mock_embeddings.embed_query.assert_called_once_with("cause A\nfix B")

    def test_update_incident_status_sets_resolved(self):
        incident_store = InMemoryStore()
        incident_store.upsert(
            ids=[1],
            vectors=[[0.1] * 1536],
            payloads=[{
                "incident_id": "err.log::0",
                "chunk_text": ">> fn !! ValueError",
                "status": "open",
            }],
        )
        _, postmortem_store = self._make_indexer()
        indexer = PostmortemIndexer(store=postmortem_store, embeddings=_make_mock_embeddings())
        indexer.update_incident_status(incident_store, "err.log::0")

        updated = incident_store.fetch_by_filter({"incident_id": "err.log::0"})
        assert updated[0]["status"] == "resolved"

    def test_update_incident_status_no_op_on_missing(self):
        incident_store = InMemoryStore()
        _, postmortem_store = self._make_indexer()
        indexer = PostmortemIndexer(store=postmortem_store, embeddings=_make_mock_embeddings())
        # Should not raise even if incident_id is not found
        indexer.update_incident_status(incident_store, "nonexistent::0")
        assert incident_store.count() == 0

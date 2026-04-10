"""TraceLog RAG Retriever.

Searches the VectorStore for error chunks semantically similar
to a given query trace, using dense vector cosine similarity.

Usage:
    retriever = TraceLogRetriever(store=indexer.store)
    results = retriever.search(">> verify_user_token !! Session expired", top_k=5)
    for chunk in results:
        print(chunk.score, chunk.error_type)
"""

import logging
import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from tracelog.rag.store import VectorStore

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


@dataclass
class RetrievedFix:
    """A postmortem retrieved by fix similarity search.

    Attributes:
        score: Cosine similarity score (0.0–1.0, higher is more similar).
        incident_id: Incident this postmortem is linked to.
        root_cause: Confirmed root cause description.
        fix: Fix that was applied.
        resolved_at: ISO-8601 timestamp of when the postmortem was committed.
    """

    score: float
    incident_id: str
    root_cause: str
    fix: str
    resolved_at: str | None = None


@dataclass
class RetrievedChunk:
    """A retrieved chunk with its metadata and relevance score.

    Attributes:
        score: Cosine similarity score (0.0–1.0, higher is more similar).
        chunk_text: The raw Trace-DSL chunk text.
        error_type: Error category extracted from the source file name.
        file_name: Source dump file name.
        chunk_index: Index of this chunk within its source file.
        has_error: Whether this chunk contains an error marker (!!).
        incident_id: Unique incident identifier (``"{file_name}::{chunk_index}"``).
        root_cause: Confirmed root cause from linked POSTMORTEM, if available.
        fix: Confirmed fix from linked POSTMORTEM, if available.
    """

    score: float
    chunk_text: str
    error_type: str
    file_name: str
    chunk_index: int
    has_error: bool
    incident_id: str = ""
    root_cause: str | None = None
    fix: str | None = None


class TraceLogRetriever:
    """Searches indexed Trace-DSL chunks for semantic similarity.

    Performs dense vector search (cosine similarity) against the VectorStore.
    Optionally filters by error type or has_error flag.

    Args:
        store: VectorStore backend (must share the same collection as the indexer).

    Example:
        retriever = TraceLogRetriever(store=indexer.store)
        hits = retriever.search("!! Session validation failed", top_k=3)
        for hit in hits:
            print(hit.error_type, f"{hit.score:.3f}")
    """

    def __init__(
        self,
        store: VectorStore,
        embeddings: Embeddings | None = None,
        postmortem_store: VectorStore | None = None,
    ):
        """Initializes the retriever.

        Args:
            store: VectorStore backend for tracelog_incidents.
            embeddings: LangChain Embeddings backend. Defaults to OpenAIEmbeddings.
                Must match the embeddings used during indexing.
            postmortem_store: Optional VectorStore backend for tracelog_postmortems.
                When provided, each retrieved chunk is enriched with its linked
                POSTMORTEM root_cause and fix (if one exists).
        """
        self.store = store
        self.embeddings: Embeddings = embeddings or OpenAIEmbeddings(model=EMBEDDING_MODEL)
        self.postmortem_store = postmortem_store

    def _embed(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text)

    def search(
        self,
        query_text: str,
        top_k: int = 5,
        filter_error_type: Optional[str] = None,
        only_error_chunks: bool = True,
    ) -> list[RetrievedChunk]:
        """Searches for chunks similar to the given query text.

        Args:
            query_text: The error chunk or query string to search with.
            top_k: Maximum number of results to return.
            filter_error_type: If set, restricts results to matching error_type.
            only_error_chunks: If True, restricts results to chunks containing
                error markers (has_error == True).

        Returns:
            List of RetrievedChunk objects sorted by descending score.
        """
        query_vector = self._embed(query_text)

        filter_dict: dict = {}
        if only_error_chunks:
            filter_dict["has_error"] = True
        if filter_error_type:
            filter_dict["error_type"] = filter_error_type

        results_raw = self.store.search(
            vector=query_vector,
            top_k=top_k,
            filter=filter_dict or None,
        )

        results = [
            RetrievedChunk(
                score=r.get("score", 0.0),
                chunk_text=r.get("chunk_text", ""),
                error_type=r.get("error_type", "Unknown"),
                file_name=r.get("file_name", ""),
                chunk_index=r.get("chunk_index", -1),
                has_error=r.get("has_error", False),
                incident_id=r.get("incident_id", ""),
            )
            for r in results_raw
        ]

        if self.postmortem_store:
            for chunk in results:
                if chunk.incident_id:
                    pm = self.postmortem_store.fetch_by_filter(
                        {"incident_id": chunk.incident_id}
                    )
                    if pm:
                        chunk.root_cause = pm[0].get("root_cause")
                        chunk.fix = pm[0].get("fix")

        logger.info(
            "Retrieved %d chunks for query (filter=%s)",
            len(results),
            filter_error_type,
        )
        return results

    def search_fixes(
        self,
        query_text: str,
        top_k: int = 5,
    ) -> list[RetrievedFix]:
        """Searches postmortems by fix similarity.

        Embeds ``query_text`` and searches ``tracelog_postmortems`` directly
        — no INCIDENT lookup involved.

        Args:
            query_text: Free-text description of the problem or fix to search for.
            top_k: Maximum number of results to return.

        Returns:
            List of RetrievedFix objects sorted by descending score.

        Raises:
            RuntimeError: If ``postmortem_store`` was not injected at construction.
        """
        if self.postmortem_store is None:
            raise RuntimeError(
                "search_fixes requires postmortem_store to be injected at construction."
            )

        query_vector = self._embed(query_text)
        results_raw = self.postmortem_store.search(vector=query_vector, top_k=top_k)

        results = [
            RetrievedFix(
                score=r.get("score", 0.0),
                incident_id=r.get("incident_id", ""),
                root_cause=r.get("root_cause", ""),
                fix=r.get("fix", ""),
                resolved_at=r.get("resolved_at"),
            )
            for r in results_raw
        ]

        logger.info("search_fixes returned %d results for query", len(results))
        return results

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
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from tracelog.rag.store import VectorStore

load_dotenv()

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"


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
    """

    score: float
    chunk_text: str
    error_type: str
    file_name: str
    chunk_index: int
    has_error: bool


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

    def __init__(self, store: VectorStore, embeddings: Embeddings | None = None):
        """Initializes the retriever.

        Args:
            store: VectorStore backend shared with the indexer.
            embeddings: LangChain Embeddings backend. Defaults to OpenAIEmbeddings.
                Must match the embeddings used during indexing.
        """
        self.store = store
        self.embeddings: Embeddings = embeddings or OpenAIEmbeddings(model=EMBEDDING_MODEL)

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
            )
            for r in results_raw
        ]

        logger.info(
            "Retrieved %d chunks for query (filter=%s)",
            len(results),
            filter_error_type,
        )
        return results

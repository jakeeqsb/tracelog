"""TraceLog RAG Retriever.

Searches the Qdrant vector store for error chunks semantically similar
to a given query trace, using dense vector cosine similarity.

Usage:
    retriever = TraceLogRetriever(indexer.client)
    results = retriever.search(">> verify_user_token !! Session expired", top_k=5)
    for chunk in results:
        print(chunk.score, chunk.payload["error_type"])
"""

import logging
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue

load_dotenv()

logger = logging.getLogger(__name__)

COLLECTION_NAME = "tracelog_chunks"
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

    Performs dense vector search (cosine similarity) against the
    Qdrant collection. Optionally filters by error type or
    has_error payload flag.

    Args:
        client: Shared Qdrant client (must point to same collection as indexer).
        collection_name: Name of the Qdrant collection to search.

    Example:
        retriever = TraceLogRetriever(client=indexer.client)
        hits = retriever.search("!! Session validation failed", top_k=3)
        for hit in hits:
            print(hit.error_type, f"{hit.score:.3f}")
    """

    def __init__(
        self,
        client: QdrantClient,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initializes the retriever.

        Args:
            client: A Qdrant client instance (shared with indexer).
            collection_name: Qdrant collection to search in.
        """
        self.client = client
        self.openai = OpenAI()
        self.collection_name = collection_name

    def _embed(self, text: str) -> list[float]:
        """Embeds a single query string.

        Args:
            text: The query text to embed.

        Returns:
            Embedding vector as a list of floats.
        """
        response = self.openai.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[text],
        )
        return response.data[0].embedding

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

        # Build optional payload filter
        conditions = []
        if only_error_chunks:
            conditions.append(
                FieldCondition(key="has_error", match=MatchValue(value=True))
            )
        if filter_error_type:
            conditions.append(
                FieldCondition(
                    key="error_type", match=MatchValue(value=filter_error_type)
                )
            )

        search_filter = Filter(must=conditions) if conditions else None

        hits = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=top_k,
            query_filter=search_filter,
            with_payload=True,
        ).points

        results = [
            RetrievedChunk(
                score=hit.score,
                chunk_text=hit.payload.get("chunk_text", ""),
                error_type=hit.payload.get("error_type", "Unknown"),
                file_name=hit.payload.get("file_name", ""),
                chunk_index=hit.payload.get("chunk_index", -1),
                has_error=hit.payload.get("has_error", False),
            )
            for hit in hits
        ]

        logger.info(
            "Retrieved %d chunks for query (filter=%s)",
            len(results),
            filter_error_type,
        )
        return results

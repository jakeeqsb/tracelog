"""QdrantStore — VectorStore adapter backed by Qdrant.

Connection is configured via environment variables:

    QDRANT_URL      Remote Qdrant server URL (e.g. http://localhost:6333).
                    If not set, an in-memory client is used.
    QDRANT_API_KEY  API key for Qdrant Cloud. Ignored when QDRANT_URL is unset.
"""

import logging
import os
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

VECTOR_DIM = 1536  # text-embedding-3-small


class QdrantStore:
    """VectorStore adapter for Qdrant.

    Reads ``QDRANT_URL`` and ``QDRANT_API_KEY`` from the environment to
    determine the connection target. Falls back to an in-memory client when
    ``QDRANT_URL`` is not set.

    Args:
        collection_name: Qdrant collection to use.
        vector_dim: Embedding dimension. Must match the embedding model.

    Example:
        # In-memory (default when QDRANT_URL is not set)
        store = QdrantStore()

        # Remote server
        # QDRANT_URL=http://localhost:6333
        store = QdrantStore()

        # Qdrant Cloud
        # QDRANT_URL=https://xyz.qdrant.io  QDRANT_API_KEY=secret
        store = QdrantStore()
    """

    def __init__(
        self,
        collection_name: str = "tracelog_chunks",
        vector_dim: int = VECTOR_DIM,
    ):
        url = os.getenv("QDRANT_URL")
        api_key = os.getenv("QDRANT_API_KEY")

        if url:
            self._client = QdrantClient(url=url, api_key=api_key or None)
            logger.info("QdrantStore connected to %s", url)
        else:
            self._client = QdrantClient(":memory:")
            logger.info("QdrantStore running in-memory")

        self.collection_name = collection_name
        self.vector_dim = vector_dim
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = {c.name for c in self._client.get_collections().collections}
        if self.collection_name not in existing:
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=self.vector_dim,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s", self.collection_name)

    def upsert(
        self,
        ids: list[Any],
        vectors: list[list[float]],
        payloads: list[dict],
    ) -> None:
        points = [
            PointStruct(id=id_, vector=vec, payload=payload)
            for id_, vec, payload in zip(ids, vectors, payloads)
        ]
        self._client.upsert(collection_name=self.collection_name, points=points)

    def search(
        self,
        vector: list[float],
        top_k: int,
        filter: dict | None = None,
    ) -> list[dict]:
        qdrant_filter = self._build_filter(filter) if filter else None
        hits = self._client.query_points(
            collection_name=self.collection_name,
            query=vector,
            limit=top_k,
            query_filter=qdrant_filter,
            with_payload=True,
        ).points
        return [{"score": hit.score, **hit.payload} for hit in hits]

    def count(self) -> int:
        return self._client.count(collection_name=self.collection_name).count

    def _build_filter(self, filter: dict) -> Filter:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filter.items()
        ]
        return Filter(must=conditions)

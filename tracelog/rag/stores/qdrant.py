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
    DatetimeRange,
    Distance,
    FieldCondition,
    Filter,
    HnswConfigDiff,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

VECTOR_DIM = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))


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
        collection_name: str = os.getenv("TRACELOG_INCIDENTS_COLLECTION", "tracelog_incidents"),
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
                    on_disk=False,
                ),
                hnsw_config=HnswConfigDiff(
                    m=16,
                    ef_construct=100,
                ),
            )
            self._create_payload_indexes()
            logger.info("Created Qdrant collection: %s", self.collection_name)

    def _create_payload_indexes(self) -> None:
        incidents_col = os.getenv("TRACELOG_INCIDENTS_COLLECTION", "tracelog_incidents")
        postmortems_col = os.getenv("TRACELOG_POSTMORTEMS_COLLECTION", "tracelog_postmortems")

        if self.collection_name == incidents_col:
            for field in ("incident_id", "error_type", "status", "file_name",
                          "trace_id", "span_id", "parent_span_id"):
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
            self._client.create_payload_index(
                collection_name=self.collection_name,
                field_name="occurred_at",
                field_schema=PayloadSchemaType.DATETIME,
            )
        elif self.collection_name == postmortems_col:
            self._client.create_payload_index(
                collection_name=self.collection_name,
                field_name="incident_id",
                field_schema=PayloadSchemaType.KEYWORD,
            )

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

    def count(self) -> int:
        return self._client.count(collection_name=self.collection_name).count

    def _build_filter(self, filter: dict) -> Filter:
        conditions = []
        for k, v in filter.items():
            if isinstance(v, dict) and ("gte" in v or "lte" in v):
                conditions.append(
                    FieldCondition(
                        key=k,
                        range=DatetimeRange(
                            gte=v.get("gte"),
                            lte=v.get("lte"),
                        ),
                    )
                )
            else:
                conditions.append(FieldCondition(key=k, match=MatchValue(value=v)))
        return Filter(must=conditions)

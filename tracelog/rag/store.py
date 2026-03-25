"""VectorStore protocol — backend-neutral interface for RAG storage."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for vector storage backends.

    Any object implementing ``upsert``, ``search``, and ``count`` satisfies
    this interface without requiring explicit inheritance.

    The ``filter`` argument to ``search`` is a plain dict of
    ``{field: value}`` conditions (all must match). Adapters are responsible
    for converting this to their backend's native filter representation.
    """

    def upsert(
        self,
        ids: list[Any],
        vectors: list[list[float]],
        payloads: list[dict],
    ) -> None:
        """Insert or update points in the store.

        Args:
            ids: Unique identifiers for each point (int or str).
            vectors: Embedding vectors, one per point.
            payloads: Metadata dicts, one per point.
        """
        ...

    def search(
        self,
        vector: list[float],
        top_k: int,
        filter: dict | None = None,
    ) -> list[dict]:
        """Search for the most similar vectors.

        Args:
            vector: Query embedding vector.
            top_k: Maximum number of results to return.
            filter: Optional equality filter, e.g. ``{"has_error": True}``.
                All conditions must match (AND semantics).

        Returns:
            List of payload dicts, each including at minimum
            ``chunk_text`` and ``score``.
        """
        ...

    def count(self) -> int:
        """Return the total number of stored points."""
        ...

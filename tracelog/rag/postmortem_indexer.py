"""PostmortemIndexer — ingests POSTMORTEM nodes into tracelog_postmortems collection."""

import logging
import os
from datetime import datetime, timezone

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from tracelog.rag.store import VectorStore
from tracelog.rag.stores.qdrant import QdrantStore

logger = logging.getLogger(__name__)

COLLECTION_NAME = os.getenv("TRACELOG_POSTMORTEMS_COLLECTION", "tracelog_postmortems")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")


class PostmortemIndexer:
    """Ingests POSTMORTEM nodes into the tracelog_postmortems VectorStore.

    Each postmortem is embedded as ``root_cause + "\\n" + fix`` and linked
    to its INCIDENT via the shared ``incident_id`` payload field.

    Args:
        store: VectorStore backend for tracelog_postmortems.
        embeddings: LangChain Embeddings backend.
    """

    def __init__(
        self,
        store: VectorStore | None = None,
        embeddings: Embeddings | None = None,
    ):
        self.store: VectorStore = store or QdrantStore(collection_name=COLLECTION_NAME)
        self.embeddings: Embeddings = embeddings or OpenAIEmbeddings(model=EMBEDDING_MODEL)

    def _embed(self, text: str) -> list[float]:
        return self.embeddings.embed_query(text)

    def commit(self, incident_id: str, root_cause: str, fix: str) -> None:
        """Create a POSTMORTEM node and link it to an INCIDENT.

        Args:
            incident_id: The ``incident_id`` of the matched INCIDENT node
                (format: ``"{file_name}::{chunk_index}"``).
            root_cause: Engineer-written description of the root cause.
            fix: Description of the fix applied.
        """
        text = root_cause + "\n" + fix
        vector = self._embed(text)
        point_id = abs(hash(f"postmortem::{incident_id}")) % (10**18)
        payload = {
            "incident_id": incident_id,
            "root_cause": root_cause,
            "fix": fix,
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        }
        self.store.upsert(ids=[point_id], vectors=[vector], payloads=[payload])
        logger.info("Committed postmortem for incident_id=%s", incident_id)

    def update_incident_status(
        self, incident_store: VectorStore, incident_id: str
    ) -> None:
        """Update the INCIDENT node status to 'resolved'.

        Fetches the INCIDENT point by ``incident_id``, then re-upserts it
        with ``status`` set to ``"resolved"``.

        Args:
            incident_store: VectorStore for tracelog_incidents.
            incident_id: The incident_id to resolve.
        """
        matches = incident_store.fetch_by_filter({"incident_id": incident_id})
        if not matches:
            logger.warning("No incident found for incident_id=%s", incident_id)
            return

        for payload in matches:
            payload["status"] = "resolved"
            point_id = abs(hash(incident_id)) % (10**18)
            # Re-embed chunk_text to get the original vector for upsert
            vector = self.embeddings.embed_query(payload.get("chunk_text", ""))
            incident_store.upsert(ids=[point_id], vectors=[vector], payloads=[payload])

        logger.info("Updated incident status to resolved for incident_id=%s", incident_id)

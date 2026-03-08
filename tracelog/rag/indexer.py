"""TraceLog RAG Indexer.

Ingests Trace-DSL dump files into a Qdrant vector store using
TraceTreeSplitter for structure-aware chunking and OpenAI embeddings.

Usage:
    indexer = TraceLogIndexer()
    indexer.index_directory(Path("docs/eval/simulators/large_dumps"))
    print(f"Indexed {indexer.count()} chunks")
"""

import re
import logging
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
)

from tracelog.chunking import TraceTreeSplitter

logger = logging.getLogger(__name__)

COLLECTION_NAME = "tracelog_chunks"
VECTOR_DIM = 1536  # text-embedding-3-small
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 100


class TraceLogIndexer:
    """Indexes Trace-DSL dump files into Qdrant for semantic search.

    Uses TraceTreeSplitter for structure-aware chunking (preserves parent
    call context around error points) and OpenAI embeddings for vectorization.

    Attributes:
        client: Qdrant client instance.
        openai: OpenAI client instance.
        splitter: TraceTreeSplitter instance.
        collection_name: Name of the Qdrant collection.

    Example:
        indexer = TraceLogIndexer()
        indexer.index_directory(Path("docs/eval/simulators/large_dumps"))
        print(indexer.count())
    """

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initializes the indexer with Qdrant and OpenAI clients.

        Args:
            qdrant_client: Optional pre-configured Qdrant client.
                Defaults to in-memory client.
            collection_name: Name of the Qdrant collection to use.
        """
        self.client = qdrant_client or QdrantClient(":memory:")
        self.openai = OpenAI()
        self.splitter = TraceTreeSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        self.collection_name = collection_name
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Creates the Qdrant collection if it does not exist."""
        existing = [c.name for c in self.client.get_collections().collections]
        if self.collection_name not in existing:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(
                    size=VECTOR_DIM,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection: %s", self.collection_name)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a list of texts using OpenAI embeddings.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (each a list of floats).
        """
        response = self.openai.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]

    def _extract_error_type(self, file_name: str) -> str:
        """Extracts the error type label from a dump file name.

        Args:
            file_name: Dump file name, e.g. 'AuthError_abc123.log'.

        Returns:
            Error type string, e.g. 'AuthError', or 'Unknown'.
        """
        match = re.match(r"^([A-Za-z]+(?:Error|Exception|Limit))", file_name)
        return match.group(1) if match else "Unknown"

    def index_file(self, file_path: Path) -> int:
        """Indexes a single Trace-DSL dump file into Qdrant.

        Args:
            file_path: Path to the .log dump file.

        Returns:
            Number of chunks indexed from this file.
        """
        text = file_path.read_text(encoding="utf-8")
        chunks = self.splitter.split_text(text)

        if not chunks:
            logger.warning("No chunks produced for %s", file_path.name)
            return 0

        error_type = self._extract_error_type(file_path.name)
        has_error_flags = ["!!" in chunk for chunk in chunks]

        vectors = self._embed(chunks)

        # Build point IDs deterministically: hash of (filename + chunk_index)
        start_id = abs(hash(file_path.name)) % (10**9)

        points = [
            PointStruct(
                id=start_id + idx,
                vector=vec,
                payload={
                    "error_type": error_type,
                    "file_name": file_path.name,
                    "chunk_index": idx,
                    "chunk_text": chunk,
                    "has_error": has_error_flag,
                },
            )
            for idx, (chunk, vec, has_error_flag) in enumerate(
                zip(chunks, vectors, has_error_flags)
            )
        ]

        self.client.upsert(collection_name=self.collection_name, points=points)
        logger.info(
            "Indexed %d chunks from %s (error_type=%s)",
            len(points),
            file_path.name,
            error_type,
        )
        return len(points)

    def index_directory(self, dump_dir: Path, pattern: str = "*.log") -> int:
        """Indexes all dump files in a directory.

        Args:
            dump_dir: Directory containing .log dump files.
            pattern: Glob pattern for dump files.

        Returns:
            Total number of chunks indexed.
        """
        files = sorted(dump_dir.glob(pattern))
        if not files:
            logger.warning("No files matching %s in %s", pattern, dump_dir)
            return 0

        total = 0
        for f in files:
            total += self.index_file(f)
        logger.info("Total chunks indexed: %d from %d files", total, len(files))
        return total

    def count(self) -> int:
        """Returns the total number of vectors stored in the collection.

        Returns:
            Integer count of indexed chunks.
        """
        return self.client.count(collection_name=self.collection_name).count

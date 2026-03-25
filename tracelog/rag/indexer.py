"""TraceLog RAG Indexer.

Ingests Trace-DSL dump files into a VectorStore using
TraceTreeSplitter for structure-aware chunking and OpenAI embeddings.

Usage:
    indexer = TraceLogIndexer()
    indexer.index_directory(Path("docs/eval/simulators/large_dumps"))
    print(f"Indexed {indexer.count()} chunks")
"""

import re
import logging
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from tracelog.chunking import TraceTreeSplitter
from tracelog.rag.store import VectorStore
from tracelog.rag.stores.qdrant import QdrantStore

load_dotenv()

logger = logging.getLogger(__name__)

COLLECTION_NAME = "tracelog_chunks"
VECTOR_DIM = 1536  # text-embedding-3-small
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 100


class TraceLogIndexer:
    """Indexes Trace-DSL dump files into a VectorStore for semantic search.

    Uses TraceTreeSplitter for structure-aware chunking (preserves parent
    call context around error points) and OpenAI embeddings for vectorization.

    The storage backend is injected via ``store``. Defaults to
    ``QdrantStore``, which reads ``QDRANT_URL`` / ``QDRANT_API_KEY`` from
    the environment (falls back to in-memory when unset).

    Attributes:
        store: VectorStore backend.
        openai: OpenAI client instance.
        splitter: TraceTreeSplitter instance.

    Example:
        indexer = TraceLogIndexer()
        indexer.index_directory(Path("docs/eval/simulators/large_dumps"))
        print(indexer.count())
    """

    def __init__(
        self,
        store: VectorStore | None = None,
        embeddings: Embeddings | None = None,
        collection_name: str = COLLECTION_NAME,
    ):
        """Initializes the indexer.

        Args:
            store: VectorStore backend. Defaults to QdrantStore (env-configured).
            embeddings: LangChain Embeddings backend. Defaults to OpenAIEmbeddings.
                Swap to any langchain-compatible embeddings (Cohere, Bedrock, etc.).
            collection_name: Collection name passed to the default QdrantStore
                when ``store`` is not provided.
        """
        self.store: VectorStore = store or QdrantStore(collection_name=collection_name)
        self.embeddings: Embeddings = embeddings or OpenAIEmbeddings(model=EMBEDDING_MODEL)
        self.splitter = TraceTreeSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embeds a list of texts using the configured Embeddings backend."""
        return self.embeddings.embed_documents(texts)

    def _extract_error_type(self, file_name: str) -> str:
        """Extracts the error type label from a dump file name."""
        match = re.match(r"^([A-Za-z]+(?:Error|Exception|Limit))", file_name)
        return match.group(1) if match else "Unknown"

    def index_file(self, file_path: Path) -> int:
        """Indexes a single Trace-DSL dump file.

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

        # Deterministic IDs: hash of (filename + chunk_index)
        base_id = abs(hash(file_path.name)) % (10**9)
        ids = [base_id + idx for idx in range(len(chunks))]
        payloads = [
            {
                "error_type": error_type,
                "file_name": file_path.name,
                "chunk_index": idx,
                "chunk_text": chunk,
                "has_error": has_error_flag,
            }
            for idx, (chunk, has_error_flag) in enumerate(
                zip(chunks, has_error_flags)
            )
        ]

        self.store.upsert(ids=ids, vectors=vectors, payloads=payloads)
        logger.info(
            "Indexed %d chunks from %s (error_type=%s)",
            len(chunks),
            file_path.name,
            error_type,
        )
        return len(chunks)

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

        total = sum(self.index_file(f) for f in files)
        logger.info("Total chunks indexed: %d from %d files", total, len(files))
        return total

    def count(self) -> int:
        """Returns the total number of vectors stored."""
        return self.store.count()

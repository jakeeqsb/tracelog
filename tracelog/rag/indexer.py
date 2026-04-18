"""TraceLog RAG Indexer.

Ingests Trace-DSL dump files into a VectorStore using
TraceTreeSplitter for structure-aware chunking and OpenAI embeddings.

Usage:
    indexer = TraceLogIndexer()
    indexer.index_directory(Path("docs/eval/simulators/large_dumps"))
    print(f"Indexed {indexer.count()} chunks")
"""

import json
import os
import re
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from tracelog.chunking import TraceTreeSplitter
from tracelog.rag.store import VectorStore
from tracelog.rag.stores.qdrant import QdrantStore

load_dotenv()

logger = logging.getLogger(__name__)

COLLECTION_NAME = os.getenv("TRACELOG_INCIDENTS_COLLECTION", "tracelog_incidents")
EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
VECTOR_DIM = int(os.getenv("OPENAI_EMBEDDING_DIM", "1536"))
CHUNK_SIZE = int(os.getenv("TRACELOG_CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.getenv("TRACELOG_CHUNK_OVERLAP", "100"))


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

    def _build_embed_text(self, chunk: str, error_type: str) -> str:
        """Builds a natural-language summary of the error context for embedding.

        Produces a 3-line NL summary from a Trace-DSL chunk, so embeddings land
        in the natural-language vector space (matching user NL queries) rather
        than the Trace-DSL symbol space.

        For chunks with no ``!!`` marker, falls back to the first 500 chars of
        the raw chunk text.

        Args:
            chunk: Raw Trace-DSL chunk text.
            error_type: Error class extracted from the dump file name.

        Returns:
            Natural-language embed text string.
        """
        lines = chunk.splitlines()

        error_idx = next(
            (i for i in range(len(lines) - 1, -1, -1) if "!!" in lines[i]),
            None,
        )
        if error_idx is None:
            return chunk[:500]

        error_line = lines[error_idx].strip()
        error_msg = re.sub(r"^.*!!\s*", "", error_line).strip()

        preceding_call_lines = [
            l for l in lines[:error_idx] if l.strip().startswith(">>")
        ][-3:]

        def _fn_name(line: str) -> str:
            raw = line.strip().lstrip(">").strip()
            return raw.split("(")[0].strip()

        fn_names = [_fn_name(l) for l in preceding_call_lines]
        call_path = " > ".join(fn_names) if fn_names else "(unknown)"
        last_fn = fn_names[-1] if fn_names else "unknown"

        brief = error_msg.split(":")[0].strip() if ":" in error_msg else error_msg[:60]

        return (
            f"{error_type} raised — {brief} in {last_fn}.\n"
            f"Call path: {call_path}.\n"
            f"Error detail: {error_msg}"
        )

    def index_file(self, file_path: Path) -> int:
        """Indexes a single Trace-DSL dump file.

        Args:
            file_path: Path to the .log dump file.

        Returns:
            Number of chunks indexed from this file.
        """
        raw = file_path.read_text(encoding="utf-8")

        # Parse JSON Lines format (FileExporter output) to extract span metadata.
        # Falls back to plain-text DSL if the first line is not valid JSON.
        trace_id = span_id = parent_span_id = None
        try:
            first_line = raw.splitlines()[0]
            meta = json.loads(first_line)
            trace_id = meta.get("trace_id")
            span_id = meta.get("span_id")
            parent_span_id = meta.get("parent_span_id")
            dsl_text = "\n".join(meta.get("dsl_lines", []))
        except (json.JSONDecodeError, IndexError, AttributeError):
            dsl_text = raw

        chunks = self.splitter.split_text(dsl_text)

        if not chunks:
            logger.warning("No chunks produced for %s", file_path.name)
            return 0

        error_type = self._extract_error_type(file_path.name)
        has_error_flags = ["!!" in chunk for chunk in chunks]
        embed_texts = [self._build_embed_text(chunk, error_type) for chunk in chunks]
        vectors = self._embed(embed_texts)

        occurred_at = datetime.fromtimestamp(file_path.stat().st_mtime).isoformat()

        # Deterministic IDs: hash of (filename::chunk_index)
        ids = [
            abs(hash(f"{file_path.name}::{idx}")) % (10**18)
            for idx in range(len(chunks))
        ]
        payloads = [
            {
                "incident_id": f"{file_path.name}::{idx}",
                "error_type": error_type,
                "file_name": file_path.name,
                "chunk_index": idx,
                "chunk_text": chunk,
                "embed_text": embed_text,
                "has_error": has_error_flag,
                "occurred_at": occurred_at,
                "status": "open",
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
            }
            for idx, (chunk, embed_text, has_error_flag) in enumerate(
                zip(chunks, embed_texts, has_error_flags)
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

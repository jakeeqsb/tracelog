"""TraceLog RAG pipeline package.

This package provides the Retrieval-Augmented Generation (RAG) pipeline
for TraceLog, enabling semantic search over past error traces and
LLM-powered root cause diagnosis.

Components:
    indexer   - Ingests Trace-DSL dumps into Qdrant vector store.
    retriever - Searches for similar error chunks using vector similarity.
    diagnoser - Combines retrieved context with LLM for root cause analysis.
"""

from tracelog.rag.indexer import TraceLogIndexer
from tracelog.rag.retriever import TraceLogRetriever
from tracelog.rag.diagnoser import TraceLogDiagnoser

__all__ = ["TraceLogIndexer", "TraceLogRetriever", "TraceLogDiagnoser"]

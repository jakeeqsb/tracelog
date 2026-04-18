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
from tracelog.rag.retriever import TraceLogRetriever, RetrievedFix
from tracelog.rag.diagnoser import TraceLogDiagnoser
from tracelog.rag.postmortem_indexer import PostmortemIndexer
from tracelog.rag.agent import TraceLogAgent

__all__ = ["TraceLogIndexer", "TraceLogRetriever", "RetrievedFix", "TraceLogDiagnoser", "PostmortemIndexer", "TraceLogAgent"]

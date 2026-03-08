"""Ingestion utilities for TraceLog."""

from .aggregator import TraceDump, aggregate_dumps, aggregate_traces

__all__ = ["TraceDump", "aggregate_dumps", "aggregate_traces"]

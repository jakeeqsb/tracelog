"""tracelog/__init__.py - Public API for the TraceLog package.

TraceLog is a context-aware logging system designed for LLM-assisted debugging.
It captures the full execution narrative leading up to an error and serialises it
as Trace-DSL — a compact, structured format optimised for LLM context windows.

Quick start:
    import logging
    from tracelog import TraceLogHandler   # required — the core integration point
    from tracelog import trace             # optional — for fine-grained tracing

    # 1. Attach to the root logger (or any specific logger)
    logging.getLogger().addHandler(TraceLogHandler())

    # 2. Use standard logging as usual — TraceLog captures everything silently
    logger = logging.getLogger(__name__)
    logger.info("job started")
    logger.debug("fetched 42 records")
    logger.error("database timeout")    # triggers full Trace-DSL dump to stderr

    # 3. Optionally annotate critical functions with @trace for richer DSL output
    @trace
    def process(order_id: int) -> dict:
        ...

    # 4. Dump to a file instead of stderr
    from tracelog import FileExporter
    logging.getLogger().addHandler(TraceLogHandler(exporter=FileExporter("/var/log/trace.log")))

Exported names:
    TraceLogHandler: The logging.Handler subclass that drives buffering and dumps.
    trace:           Decorator that adds >>, <<, and !! lines to the Trace-DSL.
    get_buffer:      Low-level accessor for the current context's RingBuffer
                     (primarily used by tests and advanced integrations).
    StreamExporter:  Dumps Trace-DSL to a writable stream (default: stderr).
    FileExporter:    Appends Trace-DSL dumps to a file on disk, with rotation support.
"""

from .handler import TraceLogHandler, get_buffer
from .instrument import trace
from .exporter import TraceExporter, StreamExporter, FileExporter

__all__ = [
    "TraceLogHandler",
    "trace",
    "get_buffer",
    "TraceExporter",
    "StreamExporter",
    "FileExporter",
]
__version__ = "0.1.0"

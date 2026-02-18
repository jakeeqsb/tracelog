import logging
import threading
from typing import Optional, Any
from .buffer import RingBuffer
from .context import ContextManager

# Singleton or ThreadLocal storage for the buffer?
# We want one buffer per thread/context.
_local_storage = threading.local()

def get_buffer() -> RingBuffer:
    """Retrieves or creates a thread-local RingBuffer."""
    if not hasattr(_local_storage, 'buffer'):
        _local_storage.buffer = RingBuffer(capacity=100)
    return _local_storage.buffer

class TraceLog:
    """
    The main Logger class for TraceLog.
    Supports 'Delegation Pattern' to wrap an existing logger.
    """
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.delegate = logger
        self.context = ContextManager()

    @property
    def buffer(self) -> RingBuffer:
        return get_buffer()

    def _format_message(self, level: str, msg: str) -> str:
        depth = self.context.get_depth()
        indent = "  " * depth
        return f"{indent}.. [{level}] {msg}"

    def info(self, msg: str, **kwargs) -> None:
        """Log INFO level."""
        # 1. Write to Buffer
        log_line = self._format_message("INFO", msg)
        self.buffer.push(log_line)
        
        # 2. Delegate to original logger if exists
        if self.delegate:
            self.delegate.info(msg, **kwargs)

    def debug(self, msg: str, **kwargs) -> None:
        """Log DEBUG level."""
        log_line = self._format_message("DEBUG", msg)
        self.buffer.push(log_line)
        
        if self.delegate:
            self.delegate.debug(msg, **kwargs)
            
    def error(self, msg: str, exc_info: bool = True, **kwargs) -> None:
        """
        Log ERROR level and TRIGGER DUMP.
        """
        # 1. Write to Buffer
        log_line = self._format_message("ERROR", msg)
        self.buffer.push(log_line)
        
        # 2. Delegate
        if self.delegate:
            self.delegate.error(msg, exc_info=exc_info, **kwargs)
            
        # 3. Dump Trigger (Immediate persistence for MVP)
        self.dump()

    def dump(self) -> None:
        """Flushes the buffer and prints DUMP to stderr (MVP)."""
        import sys
        
        print("\n\n=== [TraceLog] DUMP START ===", file=sys.stderr)
        entries = self.buffer.flash()
        for entry in entries:
            # Simple formatting for now
            print(f"{entry.message}", file=sys.stderr)
        print("=== [TraceLog] DUMP END ===\n", file=sys.stderr)

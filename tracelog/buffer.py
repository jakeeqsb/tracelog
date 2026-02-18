from collections import deque
from typing import List, Any
import time

class LogEntry:
    def __init__(self, timestamp: float, message: str):
        self.timestamp = timestamp
        self.message = message
        
    def __repr__(self):
        return f"{self.timestamp:.3f} {self.message}"

class RingBuffer:
    """
    Thread-safe(ish) circular buffer for storing log entries.
    Uses collections.deque which is thread-safe for append/pop operations.
    """
    def __init__(self, capacity: int = 100):
        self._buffer: deque[LogEntry] = deque(maxlen=capacity)
        
    def push(self, message: str) -> None:
        """Adds a new message to the buffer, automatically dropping oldest if full."""
        entry = LogEntry(time.time(), message)
        self._buffer.append(entry)
        
    def flash(self) -> List[LogEntry]:  
        # Using list() on deque creates a copy, which is thread-safe enough for snapshotting
        # However, clearing it afterwards might race if not locked.
        # For MVP, we'll accept minor race conditions or just return a snapshot without clearing.
        # But 'dump' usually implies clearing or at least capturing the state at that moment.
        # Let's return a snapshot. If we want to clear, we should decide if we clear on dump.
        # Usually dump is for error analysis, so we might want to keep the history if the app continues?
        # But the requirement says "Flush and Dump".
        
        # Taking a snapshot
        data = list(self._buffer)
        return data

    def clear(self) -> None:
        self._buffer.clear()

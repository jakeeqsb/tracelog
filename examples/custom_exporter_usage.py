"""examples/custom_exporter_usage.py - Implement and plug in a custom exporter.

Shows how to subclass TraceExporter to forward Trace-DSL dumps to any
destination — in this example, an in-memory list (useful for testing) and
a simulated JSON-over-HTTP POST to a remote aggregator.

Run:
    python examples/custom_exporter_usage.py
"""

import json
import logging
from typing import List
from urllib.request import Request, urlopen
from urllib.error import URLError

from tracelog import TraceLogHandler, trace
from tracelog.exporter import TraceExporter
from tracelog.buffer import LogEntry


# ---------------------------------------------------------------------------
# Custom Exporter 1: In-Memory Collector (great for unit tests)
# ---------------------------------------------------------------------------


class MemoryExporter(TraceExporter):
    """Stores all Trace-DSL dumps in memory.

    Useful for assertions in integration tests where you want to
    verify what would have been emitted without writing anywhere.

    Attributes:
        dumps: Each element is a list of DSL lines from one ERROR event.

    Example:
        >>> exporter = MemoryExporter()
        >>> handler = TraceLogHandler(exporter=exporter)
        >>> # ... trigger an error ...
        >>> assert "InsufficientFunds" in exporter.dumps[0][0]
    """

    def __init__(self) -> None:
        self.dumps: List[List[str]] = []

    def export(self, entries: List[LogEntry]) -> None:
        self.dumps.append([e.dsl_line for e in entries])


# ---------------------------------------------------------------------------
# Custom Exporter 2: JSON-over-HTTP (simulate sending to remote aggregator)
# ---------------------------------------------------------------------------


class HttpJsonExporter(TraceExporter):
    """Sends Trace-DSL dumps as JSON via HTTP POST to a remote endpoint.

    In a real deployment this would point to the TraceLog Aggregator service.
    Here we simulate it with a print statement when the HTTP call fails.

    Args:
        endpoint: Full URL of the aggregator endpoint.
        timeout: Request timeout in seconds.
    """

    def __init__(self, endpoint: str, timeout: int = 5) -> None:
        self._endpoint = endpoint
        self._timeout = timeout

    def export(self, entries: List[LogEntry]) -> None:
        payload = json.dumps(
            {"entries": [e.dsl_line for e in entries]},
            ensure_ascii=False,
        ).encode("utf-8")

        req = Request(
            self._endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(req, timeout=self._timeout) as resp:
                print(
                    f"[HttpJsonExporter] Sent {len(entries)} entries → HTTP {resp.status}"
                )
        except URLError as exc:
            # Do NOT swallow the trace — print to stderr as fallback
            print(
                f"[HttpJsonExporter] WARNING: could not reach {self._endpoint} "
                f"({exc.reason}). Trace-DSL dump follows:\n"
            )
            for entry in entries:
                print(f"  {entry.dsl_line}")


# ---------------------------------------------------------------------------
# Business logic (same payment example, reused for clarity)
# ---------------------------------------------------------------------------


def run_with_exporter(exporter: TraceExporter, label: str) -> MemoryExporter | None:
    """Run a payment scenario with the provided exporter and return it."""
    logger = logging.getLogger(f"demo.{label}")
    logger.setLevel(logging.DEBUG)
    handler = TraceLogHandler(capacity=50, exporter=exporter)
    logger.addHandler(handler)

    @trace
    def pay(amount: int) -> None:
        logger.info(f"Paying {amount}")
        if amount > 1000:
            logger.error(f"Limit exceeded: {amount}")
            raise ValueError("LimitExceeded")
        logger.info("Payment OK")

    try:
        pay(5000)  # triggers ERROR → dump
    except ValueError:
        pass

    logger.removeHandler(handler)
    return exporter


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # --- Demo 1: MemoryExporter ---
    print("=" * 60)
    print("Demo 1: MemoryExporter (all dumps captured in-memory)")
    print("=" * 60)
    mem = MemoryExporter()
    run_with_exporter(mem, "mem")
    print(f"Captured {len(mem.dumps)} dump(s). First dump contents:")
    for line in mem.dumps[0]:
        print(f"  {line}")

    print()

    # --- Demo 2: HttpJsonExporter (will fail gracefully — no real server) ---
    print("=" * 60)
    print("Demo 2: HttpJsonExporter (fallback to stderr on connection failure)")
    print("=" * 60)
    http = HttpJsonExporter(endpoint="http://localhost:9876/api/traces")
    run_with_exporter(http, "http")

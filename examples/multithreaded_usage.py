"""examples/multithreaded_usage.py - Thread context isolation demo.

Demonstrates that each thread maintains its own independent Trace-DSL buffer.
An ERROR in Thread-B dumps only Thread-B's context — Thread-A's successful
records are NOT included in that dump, and vice versa.

This is one of TraceLog's most important guarantees: per-context isolation
via contextvars means concurrent requests never bleed into each other's trace.

Run:
    python examples/multithreaded_usage.py
"""

import logging
import sys
import threading
import time

from tracelog import TraceLogHandler, trace

# ---------------------------------------------------------------------------
# Setup: one handler on the root logger, picked up by all threads
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] [thread=%(threadName)s] %(message)s",
)
root_logger = logging.getLogger()
root_logger.addHandler(TraceLogHandler(capacity=50))

logger = logging.getLogger("order_service")


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------


@trace
def fetch_inventory(product_id: int) -> int:
    """Simulate a DB read for product stock."""
    logger.debug(f"Fetching inventory: product_id={product_id}")
    time.sleep(0.01)  # simulate DB latency
    stock = {1: 10, 2: 0, 3: 5}  # product 2 is out-of-stock
    return stock.get(product_id, 0)


@trace
def place_order(order_id: int, product_id: int, qty: int) -> dict:
    """Attempt to place an order for the given product and quantity."""
    logger.info(
        f"Order received: order_id={order_id}, product_id={product_id}, qty={qty}"
    )
    stock = fetch_inventory(product_id)

    if stock < qty:
        logger.error(
            f"Insufficient stock: product_id={product_id}, "
            f"requested={qty}, available={stock}"
        )
        raise RuntimeError(f"OutOfStock: product_id={product_id}")

    logger.info(f"Order placed: order_id={order_id}")
    return {"order_id": order_id, "status": "confirmed"}


# ---------------------------------------------------------------------------
# Simulate two concurrent HTTP requests in separate threads
# ---------------------------------------------------------------------------


def worker(order_id: int, product_id: int, qty: int) -> None:
    """Worker function representing a single HTTP request handler."""
    try:
        result = place_order(order_id=order_id, product_id=product_id, qty=qty)
        print(
            f"[Thread {threading.current_thread().name}] SUCCESS: {result}",
            file=sys.stdout,
        )
    except RuntimeError as exc:
        print(
            f"[Thread {threading.current_thread().name}] "
            f"ERROR: {exc}  ← DSL dump above belongs to THIS thread only",
            file=sys.stdout,
        )


if __name__ == "__main__":
    print("=" * 60)
    print("Launching two concurrent order requests...")
    print("  Thread-A: product_id=1, qty=3  → success (stock=10)")
    print("  Thread-B: product_id=2, qty=1  → fail    (stock=0, OUT OF STOCK)")
    print("=" * 60)
    print()

    t_a = threading.Thread(
        target=worker,
        args=(1001, 1, 3),
        name="Thread-A",
    )
    t_b = threading.Thread(
        target=worker,
        args=(1002, 2, 1),
        name="Thread-B",
    )

    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    print()
    print("Notice: the Trace-DSL dump above contains ONLY Thread-B context.")
    print("Thread-A's successful records were never written anywhere.")

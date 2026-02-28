"""examples/file_exporter_usage.py - Dump Trace-DSL to a file instead of stderr.

Demonstrates how to replace the default StreamExporter with a FileExporter
to retain Trace-DSL dumps on disk. Also shows the max_bytes rotation feature.

Run:
    python examples/file_exporter_usage.py
    cat /tmp/tracelog_demo/trace.log
"""

import logging
import os

from tracelog import TraceLogHandler, trace
from tracelog.exporter import FileExporter

# ---------------------------------------------------------------------------
# Setup: swap the default stderr exporter for a file exporter
# ---------------------------------------------------------------------------
LOG_FILE = "/tmp/tracelog_demo/trace.log"

file_exporter = FileExporter(
    path=LOG_FILE,
    max_bytes=1 * 1024 * 1024,  # rotate when file exceeds 1 MB
)

handler = TraceLogHandler(capacity=100, exporter=file_exporter)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("payment_service")
logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------


@trace
def authorize(user_id: int, amount: int) -> bool:
    """Check if a user is authorised to make a payment of the given amount."""
    logger.info(f"Authorising: user_id={user_id}, amount={amount}")
    if amount > 10_000:
        logger.warning("Amount exceeds daily limit — authorisation failed")
        return False
    return True


@trace
def charge(user_id: int, amount: int) -> dict:
    """Charge the user and return a receipt (simulated)."""
    logger.debug(f"Charging user_id={user_id}, amount={amount}")
    if not authorize(user_id, amount):
        logger.error(f"Authorisation denied for user_id={user_id}, amount={amount}")
        raise PermissionError(f"DailyLimitExceeded: user_id={user_id}")
    receipt = {"status": "ok", "user_id": user_id, "charged": amount}
    logger.info(f"Charge successful: {receipt}")
    return receipt


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Trace-DSL dumps will be written to: {LOG_FILE}")
    print()

    # Successful charge — nothing written to file (no ERROR triggered)
    try:
        receipt = charge(user_id=1, amount=500)
        print(f"[OK] Receipt: {receipt}")
    except PermissionError:
        pass

    print()

    # Failed charge (amount > 10 000) — ERROR triggers DSL dump to file
    try:
        charge(user_id=2, amount=50_000)
    except PermissionError as e:
        print(f"[FAIL] Caught: {e}")

    print()
    if os.path.exists(LOG_FILE):
        print(f"--- Contents of {LOG_FILE} ---")
        with open(LOG_FILE) as f:
            print(f.read())
    else:
        print("No dump file created (no ERROR occurred).")

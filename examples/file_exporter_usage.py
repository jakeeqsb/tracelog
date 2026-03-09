"""examples/file_exporter_usage.py - Write JSON dumps to a file instead of stderr.

Demonstrates how to replace the default StreamExporter with a FileExporter
to retain JSON dumps on disk. Dump and chunk paths are read from the
TRACELOG_DUMP_DIR and TRACELOG_CHUNK_DIR environment variables (see .env).

Run:
    PYTHONPATH=. uv run examples/file_exporter_usage.py
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from tracelog import TraceLogHandler, trace
from tracelog.exporter import FileExporter

# Load .env from the project root (two levels up from this file if nested, or cwd)
load_dotenv()

# ---------------------------------------------------------------------------
# Resolve paths from environment variables (with sensible fallbacks)
# ---------------------------------------------------------------------------
DUMP_DIR = os.environ.get("TRACELOG_DUMP_DIR", ".tracelog/dumps")
CHUNK_DIR = os.environ.get("TRACELOG_CHUNK_DIR", ".tracelog/chunks")
LOG_FILE = str(Path(DUMP_DIR) / "trace.log")

# ---------------------------------------------------------------------------
# Setup: swap the default stderr exporter for a file exporter
# ---------------------------------------------------------------------------
file_exporter = FileExporter(
    path=LOG_FILE,
    max_bytes=1 * 1024 * 1024,  # rotate when file exceeds 1 MB
)

handler = TraceLogHandler(capacity=100, exporter=file_exporter, chunk_dir=CHUNK_DIR)

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
    print(f"Chunk dir  : {CHUNK_DIR}")
    print(f"Dump file  : {LOG_FILE}")
    print()

    # Successful charge — nothing written to file (no ERROR triggered)
    try:
        receipt = charge(user_id=1, amount=500)
        print(f"[OK] Receipt: {receipt}")
    except PermissionError:
        pass

    print()

    # Failed charge (amount > 10 000) — ERROR triggers JSON dump to file
    try:
        charge(user_id=2, amount=50_000)
    except PermissionError as e:
        print(f"[FAIL] Caught: {e}")

    print()
    if os.path.exists(LOG_FILE):
        print(f"--- Contents of {LOG_FILE} ---")
        with open(LOG_FILE) as f:
            raw = f.read()
            print(raw)
            print("--- Pretty JSON ---")
            for line in raw.splitlines():
                if line.strip():
                    print(json.dumps(json.loads(line), indent=2, ensure_ascii=False))
    else:
        print("No dump file created (no ERROR occurred).")

    # --------------------------------------------------------------------------
    # Chunk file verification (capacity=3)
    # Creates a ChunkBuffer that flushes every 3 entries so we can inspect the
    # resulting .json chunk files on disk. flash() is NOT called here — the chunk
    # files are left on disk intentionally so you can open them in your editor.
    # --------------------------------------------------------------------------
    import json
    from tracelog.buffer import ChunkBuffer

    print()
    print("=" * 60)
    print("Chunk file verification (capacity=3)")
    print("=" * 60)

    chunk_dir_path = Path(CHUNK_DIR)
    chunk_dir_path.mkdir(parents=True, exist_ok=True)
    buf: ChunkBuffer = ChunkBuffer(capacity=3, chunk_dir=str(chunk_dir_path))

    # Push 7 entries — flushes happen automatically at entries 3 and 6
    for i in range(1, 8):
        buf.push(f".. [INFO] step {i}", level=20)

    # Show chunk files still on disk (flash() was NOT called)
    chunk_files = sorted(chunk_dir_path.glob("*.json"))
    print(f"\nChunk files in {chunk_dir_path.resolve()}/ : {len(chunk_files)} file(s)")
    for f in chunk_files:
        data = json.loads(f.read_text())
        print(f"\n  [{f.name}]  ({len(data)} entries)")
        for entry in data:
            print(f"    {entry['dsl_line']}")
        print(f"  → open: {f.resolve()}")

    in_memory = len(buf)
    print(f"\nIn-memory buffer (not yet flushed): {in_memory} entries")
    print(
        f"\n[NOTE] Chunk files above are still on disk at {chunk_dir_path.resolve()}/"
    )
    print(
        "       In production, flash() on ERROR merges them all and deletes the files."
    )

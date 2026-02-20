"""examples/basic_usage.py - TraceLog integration demo.

Demonstrates two usage levels:
    Scenario A — with @trace: full Trace-DSL including >> / << / !!
    Scenario B — without @trace: handler-only, captures logging calls only
"""

import logging
from tracelog import TraceLogHandler, trace

# ---------------------------------------------------------------------------
# Standard logger setup (no changes from what a developer already has)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("app")

# ---------------------------------------------------------------------------
# TraceLog integration: one line added to the existing setup
# ---------------------------------------------------------------------------
logging.getLogger().addHandler(TraceLogHandler(capacity=50))


# ===========================================================================
# Scenario A: with @trace  (full Trace-DSL — recommended for critical paths)
# ===========================================================================


@trace
def get_balance(user_id: int) -> int:
    """Simulate a DB balance query (decorated)."""
    logger.debug(f"Querying balance from DB: user_id={user_id}")
    return 3_000


@trace
def pay(user_id: int, amount: int) -> None:
    """Simulate a payment flow (decorated)."""
    logger.info(f"Payment attempt: user_id={user_id}, amount={amount}")
    balance = get_balance(user_id)

    if balance < amount:
        logger.error(
            f"Insufficient funds (balance={balance}, requested={amount})",
            exc_info=False,
        )
        raise ValueError(f"InsufficientFunds: balance={balance}, amount={amount}")

    logger.info("Payment successful")


# ===========================================================================
# Scenario B: without @trace  (handler-only — zero code change required)
# ===========================================================================


def get_balance_plain(user_id: int) -> int:
    """Simulate a DB balance query (NOT decorated)."""
    logger.debug(f"Querying balance from DB: user_id={user_id}")
    return 3_000


def pay_plain(user_id: int, amount: int) -> None:
    """Simulate a payment flow (NOT decorated — standard logging only)."""
    logger.info(f"Payment attempt: user_id={user_id}, amount={amount}")
    balance = get_balance_plain(user_id)

    if balance < amount:
        # TraceLogHandler still catches this ERROR and dumps all buffered
        # INFO / DEBUG lines above it as Trace-DSL — no decorator needed.
        logger.error(
            f"Insufficient funds (balance={balance}, requested={amount})",
            exc_info=False,
        )
        raise ValueError(f"InsufficientFunds: balance={balance}, amount={amount}")

    logger.info("Payment successful")


# ---------------------------------------------------------------------------
# Run both scenarios
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Scenario A: with @trace (>> / << / !! included in DSL)")
    print("=" * 60)
    try:
        pay(user_id=101, amount=5_000)
    except ValueError:
        pass

    print()
    print("=" * 60)
    print("Scenario B: without @trace (logging calls only)")
    print("=" * 60)
    try:
        pay_plain(user_id=202, amount=5_000)
    except ValueError:
        pass

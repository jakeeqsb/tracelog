import logging

from tracelog.core import TraceLog
from tracelog.instrument import trace


# 1. Setup Original Logger
original_logger = logging.getLogger("app")
original_logger.setLevel(logging.INFO)
# Console Handler
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('ORIGINAL: %(message)s'))
original_logger.addHandler(ch)

# 2. Inject into TraceLog
logger = TraceLog(logger=original_logger)

@trace
def nested_func(x):
    logger.debug(f"Handling nested value {x}")
    if x < 0:
        raise ValueError("Negative value not allowed!")
    return x * 2

@trace
def main_process():
    logger.info("Starting process...")
    try:
        val = nested_func(10)
        logger.info(f"Computed: {val}")
        
        # Trigger Error
        nested_func(-5)
    except Exception as e:
        logger.error(f"Caught top-level exception: {e}")

if __name__ == "__main__":
    print("=== STARTING TRACELOG DEMO ===")
    main_process()
    print("=== FINISHED TRACELOG DEMO ===")

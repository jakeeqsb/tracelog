import threading
import time
from concurrent.futures import ThreadPoolExecutor

# Decorator for tracing function calls
def trace(func):
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        return result
    return wrapper

# Thread-local storage to hold context information
_ctx = threading.local()

class TaskExecutor:
    def __init__(self, storage_size):
        self.storage = [0] * storage_size
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.logger = self.setup_logger()

    def setup_logger(self):
        import logging
        logger = logging.getLogger("TaskExecutor")
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s [%(threadName)s] %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        return logger

    def set_context(self, mode):
        self.logger.info(f"Setting context: {mode}")
        _ctx.is_admin = (mode == "ADMIN")
        if _ctx.is_admin:
            self.logger.info("Administrative mode enabled")

    def process_index(self, val):
        self.logger.info(f"Processing index for value: {val}")
        is_admin = getattr(_ctx, 'is_admin', False)
        
        if is_admin:
            self.logger.debug("Administrative override active")
            res = val
        else:
            self.logger.debug("Standard validation active")
            res = val % len(self.storage)
            
        self.logger.info(f"Resulting index: {res}")
        return res

    @trace
    def sync_telemetry(self):
        self.logger.debug("Syncing system telemetry")

    @trace
    def apply_update(self, idx):
        self.logger.info(f"Applying update to storage at index: {idx}")
        self.executor.submit(self.sync_telemetry)
        self.storage[idx] = 1
        self.logger.info("Update successful")

    @trace
    def execute_task(self, mode, val):
        self.set_context(mode)
        idx = self.process_index(val)
        self.apply_update(idx)

    @trace
    def run(self):
        self.logger.info("Sequence started")
        
        f1 = self.executor.submit(self.execute_task, "ADMIN", 5)
        f1.result()
        
        self.logger.info("Task 1 complete")
        time.sleep(0.05)

        f2 = self.executor.submit(self.execute_task, "USER", 15)
        try:
            f2.result()
        except Exception as e:
            self.logger.error(f"Task 2 failed: {str(e)}")
            raise e
        finally:
            self.executor.shutdown(wait=False)

# Example usage
if __name__ == "__main__":
    executor = TaskExecutor(storage_size=10)
    executor.run()

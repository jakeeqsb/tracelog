import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info("Starting main process")
        self.process_checkout()
        self.fetch_product_details()
        self.calculate_total()
        self.logger.info("Finished main process")
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.audit_log)

    @trace
    def process_checkout(self):
        self.logger.info("Processing checkout")
        self.simulate_cache_hit()
        self.logger.debug("Queue depth: 5")

    @trace
    def fetch_product_details(self):
        self.logger.info("Fetching product details")
        product_id = "abc123"
        self.logger.debug(f"Product ID: {product_id}")
        self.simulate_retry("fetch_product_details")

    @trace
    def calculate_total(self):
        self.logger.info("Calculating total price")
        price = 19.99
        quantity = "2"  # Bug: quantity should be an integer, not a string
        self.logger.debug(f"Price: {price}, Quantity: {quantity}")
        # This will raise a TypeError
        total = price * quantity
        self.logger.debug(f"Total calculated: {total}")
        return total

    @trace
    def audit_log(self):
        self.logger.info("Writing to audit log")
        self.logger.debug("No issues detected")

    def simulate_cache_hit(self):
        self.logger.info("Cache hit for product details")

    def simulate_retry(self, method_name):
        self.logger.warning(f"Retrying {method_name} due to transient error")

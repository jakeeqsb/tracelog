import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        # Main process chain
        self.logger.info("Starting checkout process.")
        order_amount = 120.50
        tax_rate = self.calculate_tax_rate()  # Tax calculation
        total_cost = self.calculate_total_cost(order_amount, tax_rate)
        if self.process_payment(order_amount, total_cost):
            self.logger.info("Payment process completed successfully.")
        else:
            self.logger.warning("Payment failed.")

        # Side process
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.audit_log, order_amount, total_cost)

    @trace
    def calculate_tax_rate(self):
        # Pretend external service call
        self.logger.debug("Queried tax rate service.")
        return 0.075  # 7.5%

    @trace
    def calculate_total_cost(self, order_amount, tax_rate):
        # Calculating total cost with tax
        self.logger.debug(f"Calculating total cost for order amount: {order_amount} with tax rate: {tax_rate}")
        total_cost = order_amount * tax_rate  # Bug: should be (order_amount * (1 + tax_rate))
        self.logger.info(f"Total cost computed: {total_cost}")
        return total_cost

    @trace
    def process_payment(self, order_amount, total_cost):
        # Processing payment (dummy implementation)
        self.logger.debug("Connecting to payment gateway.")
        if total_cost <= 0:
            raise ValueError("Total cost must be greater than zero.")
        elif total_cost < order_amount:
            self.logger.error("Processed payment is less than the order amount!")
            return False
        return True

    @trace
    def audit_log(self, order_amount, total_cost):
        # External audit logging
        self.logger.info(f"Audit log - Order: {order_amount}, Total: {total_cost}")

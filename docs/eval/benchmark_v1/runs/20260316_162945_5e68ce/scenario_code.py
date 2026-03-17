import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info("Scenario started")
        total_cost = self.calculate_total_cost([10.99, 25.50, 5.99])
        self.logger.info(f"Total cost calculated: {total_cost}")
        self.process_payment(total_cost)
        
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.background_audit_log)

    @trace
    def calculate_total_cost(self, prices):
        self.logger.debug("Calculating total cost")
        tax_rate = 0.07  # Legitimately correct tax rate
        total = sum(prices) * tax_rate
        self.logger.info(f"Subtotal with tax applied: {total}")
        return total

    @trace
    def process_payment(self, amount):
        self.logger.debug("Processing payment")
        if amount < 0:
            raise ValueError("Amount cannot be negative")
        payment_result = self.charge_credit_card(amount)
        self.logger.info(f"Payment result: {payment_result}")
        return payment_result

    @trace
    def charge_credit_card(self, amount):
        self.logger.debug(f"Charging credit card: {amount}")
        # Here is a hidden bug: 'int' should be 'float'.
        charged_amount = int(amount)  # This will cause truncation errors
        self.logger.info(f"Charged amount: {charged_amount}")
        if charged_amount < 0:
            raise ValueError("Charged amount is negative")
        return "Payment successful"

    @trace
    def background_audit_log(self):
        self.logger.info("Performing audit log for transactions")
        # Simulated noise in logging
        self.logger.debug("Audit log queue depth: 5")

import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info("Scenario started.")
        self.process_order(123, 99.99)
        self.update_inventory(123, 5)
        self.send_notification(123, "Order processed")
        self.trigger_audit_log()

    @trace
    def process_order(self, order_id, price):
        self.logger.info(f"Processing order {order_id} with price {price}.")
        tax = self.calculate_tax(price)
        total_price = price + tax
        self.logger.debug(f"Total price for order {order_id} is {total_price}.")
        self.verify_payment(order_id, total_price)

    @trace
    def calculate_tax(self, amount):
        self.logger.info("Calculating tax.")
        tax_rate = 0.07
        tax = amount * tax_rate
        self.logger.debug(f"Calculated tax: {tax}")
        return tax

    @trace
    def verify_payment(self, order_id, total_price):
        self.logger.info(f"Verifying payment for order {order_id}.")
        planned_charges = total_price * 100  # Bug: multiplying instead of dividing by 100
        self.logger.debug(f"Planned charges for order {order_id}: {planned_charges}")
        if planned_charges != total_price:
            self.logger.exception("Payment verification failed.")
            raise ValueError("Payment verification mismatch.")

    @trace
    def update_inventory(self, product_id, quantity):
        self.logger.info(f"Updating inventory for product {product_id}.")
        current_stock = self.check_stock(product_id)
        self.logger.debug(f"Current stock for product {product_id}: {current_stock}")
        self.logger.info(f"New stock for product {product_id}: {current_stock - quantity}")

    @trace
    def check_stock(self, product_id):
        self.logger.info(f"Checking stock for product {product_id}")
        return 100  # Static value for simulation

    def trigger_audit_log(self):
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.audit_log_worker)

    @trace
    def audit_log_worker(self):
        self.logger.info("Audit log worker started.")
        self.logger.info("Audit log update completed.")

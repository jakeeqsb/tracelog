import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info("Starting e-commerce checkout process.")
        order_amount = self.calculate_discounted_price(100, 0.15)
        self.process_payment(order_amount)
        self.update_inventory()
        self.send_confirmation_email(order_amount)

    @trace
    def calculate_discounted_price(self, price, discount):
        discounted_price = price - (price * discount * 10)  # Incorrect multiplier
        self.logger.debug(f"Calculated discounted price: {discounted_price}")
        return discounted_price

    @trace
    def process_payment(self, amount):
        self.logger.info("Processing payment.")
        if amount <= 0:
            raise ValueError("Payment amount must be positive.")
        self.logger.info("Payment processed successfully.")

    @trace
    def update_inventory(self):
        self.logger.info("Updating inventory.")
        # Simulating inventory update noise
        self.logger.debug("Inventory update cached.")
        self.logger.debug("Inventory update committed.")

    @trace
    def send_confirmation_email(self, amount):
        self.logger.info("Sending confirmation email.")
        with ThreadPoolExecutor() as executor:
            executor.submit(self._background_email_worker, amount)

    @trace
    def _background_email_worker(self, amount):
        # Simulating unrelated background task noise
        self.logger.debug(f"Queue depth: {5}")
        self.logger.info(f"Confirmation email sent for amount: {amount}")

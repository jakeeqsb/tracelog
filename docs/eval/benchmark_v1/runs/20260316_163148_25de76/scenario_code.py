import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace


class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info('Service started')
        total_price = self.calculate_total_price()  # Root cause
        self.check_inventory()
        self.process_payment(total_price)  # Surface error
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.background_audit_log)

    @trace
    def calculate_total_price(self):
        prices = [29.99, 49.99, 19.99]  # Assume these are fetched from a service
        shipping_fee = "5.0"  # Bug: should be a float, not a string
        total_price = sum(prices) + shipping_fee  # Raises TypeError
        self.logger.debug(f'Calculated total price: {total_price}')
        return total_price

    @trace
    def check_inventory(self):
        self.logger.info('Checking inventory levels')
        try:
            # Simulate inventory check
            self.logger.debug('Inventory levels sufficient for order')
        except Exception as e:
            self.logger.exception('Error during inventory check')

    @trace
    def process_payment(self, amount):
        self.logger.info('Processing payment')
        try:
            # Simulate payment processing
            self.logger.debug(f'Payment amount: {amount}')
        except Exception as e:
            self.logger.exception('Payment processing failed')

    @trace
    def background_audit_log(self):
        self.logger.debug('Starting background audit log')
        # Simulate background logging task
        self.logger.debug('Audit log complete')

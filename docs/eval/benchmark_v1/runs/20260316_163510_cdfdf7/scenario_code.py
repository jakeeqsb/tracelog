import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info('Scenario started.')
        total_cost = self.calculate_total_cost(5, '3.50')
        available_stock = self.check_inventory(total_cost)
        self.process_payment(total_cost)
        self.logger.info('Scenario completed.')
        
        # Background worker
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.record_audit_log, "Order processed.")

    @trace
    def calculate_total_cost(self, quantity, price_per_item):
        self.logger.debug(f'Calculating total cost for quantity {quantity} and price {price_per_item}.')
        total_cost = quantity * price_per_item  # Bug: price_per_item should be converted to float
        self.logger.info(f'Total cost calculated: {total_cost:.2f}')
        self.logger.debug('Cost calculation finished.')
        return total_cost

    @trace
    def check_inventory(self, requested_units):
        available_units = 50  # Simulated available stock
        self.logger.debug(f'Checking inventory for {requested_units} units.')
        if requested_units > available_units:
            self.logger.warning('Not enough stock available!')
        else:
            self.logger.info('Sufficient stock available.')
        self.logger.info(f'Inventory check returned {available_units - requested_units} remaining units.')
        return available_units

    @trace
    def process_payment(self, amount):
        self.logger.debug(f'Processing payment of amount {amount}.')
        if amount > 100.00:  # Random threshold for payment processing
            self.logger.warning('High payment amount flagged for review.')
        if isinstance(amount, str):
            self.logger.exception('Failed to process payment: Amount is not a valid number.')
            raise ValueError('Invalid amount for payment processing.')
        self.logger.info('Payment processed successfully.')

    @trace
    def record_audit_log(self, message):
        self.logger.debug(f'Recording audit log: {message}')
        # Simulating delay in logging
        self.logger.info('Audit log recorded.')

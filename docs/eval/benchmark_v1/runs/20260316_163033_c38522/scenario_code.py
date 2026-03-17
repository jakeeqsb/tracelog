import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info('Scenario started.')
        self.process_order(123)
        self.finalize_transaction(123)
        # Start background worker for audit logging
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.audit_log, 123)

    @trace
    def process_order(self, order_id):
        self.logger.info(f'Processing order: {order_id}')
        items = self.retrieve_order_items(order_id)
        self.verify_stock(items)

    @trace
    def retrieve_order_items(self, order_id):
        self.logger.debug(f'Retrieving items for order: {order_id}')
        # Wrong hardcoded items, creates a bug
        items = ['item1', 'item2', 'item3', 5]  # Numeric instead of string identifier
        self.logger.debug(f'Order items: {items}')
        return items

    @trace
    def verify_stock(self, items):
        self.logger.info('Verifying stock for items.')
        for item in items:
            if not isinstance(item, str) or len(item) == 0:
                raise ValueError(f'Item identifier is not valid: {item}')
            self.logger.debug(f'Stock level checked: {item}')
        self.logger.info('Stock verification complete.')

    @trace
    def finalize_transaction(self, order_id):
        self.logger.info(f'Finalizing transaction for order: {order_id}')
        self.logger.info('Transaction complete.')

    @trace
    def audit_log(self, order_id):
        self.logger.info(f'Logging audit for order: {order_id}')
        self.logger.info('Audit log complete.')

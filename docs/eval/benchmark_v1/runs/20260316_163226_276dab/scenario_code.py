import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info('Starting service run.')
        self._process_order()
        self._sync_inventory()
        self._notify_customer()
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self._background_audit_log)

    @trace
    def _process_order(self):
        self.logger.info('Processing order.')
        total_price = self._calculate_total_price([100, 150, 200])
        self.logger.info(f'Total price calculated: {total_price}')

    @trace
    def _calculate_total_price(self, prices):
        total_price = sum(prices) - 10  # Bug: Incorrect hardcoded discount
        self.logger.debug(f'Total price with discount: {total_price}')
        return total_price

    @trace
    def _sync_inventory(self):
        self.logger.info('Syncing inventory.')
        product_count = self._fetch_product_count()
        self.logger.info(f'Product count fetched: {product_count}')
        adjusted_count = self._adjust_inventory_count(product_count)
        self.logger.info(f'Inventory adjusted: {adjusted_count}')

    @trace
    def _fetch_product_count(self):
        self.logger.info('Fetching product count.')
        return 20

    @trace
    def _adjust_inventory_count(self, count):
        if count > 10:
            raise ValueError('Inventory count exceeds threshold!')
        adjusted_count = count - 5  # Simulating adjustment
        self.logger.debug(f'Adjusted count: {adjusted_count}')
        return adjusted_count

    @trace
    def _notify_customer(self):
        self.logger.info('Notifying customer.')
        try:
            self._send_notification('Your order has been processed.')
        except Exception as e:
            self.logger.exception('Failed to send notification')

    @trace
    def _send_notification(self, message):
        if len(message) > 50:
            raise ValueError('Message too long!')
        self.logger.debug(f'Notification sent: {message}')

    @trace
    def _background_audit_log(self):
        self.logger.info('Audit log service running.')
        self.logger.info('Checking log integrity.')

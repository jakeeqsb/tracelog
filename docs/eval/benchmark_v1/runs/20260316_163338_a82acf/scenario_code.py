import logging
from concurrent.futures import ThreadPoolExecutor
from tracelog import trace

class Scenario:
    def __init__(self, logger):
        self.logger = logger

    @trace
    def run(self):
        self.logger.info('Starting checkout process.')
        order_total = self.calculate_order_total(items=[("item1", 2), ("item2", 3.5), ("item3", 1)])
        self.logger.debug(f'Order total calculated: {order_total}')
        self.apply_discount(order_total)
        self.logger.info('Checkout process complete.')

        # Launching a background process for audit logging
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(self.audit_log, "Checkout completed.")

    @trace
    def calculate_order_total(self, items):
        self.logger.debug('Calculating order total.')
        total = sum(qty for item, qty in items)
        self.logger.debug(f'Total computed: {total}')
        return total

    @trace
    def apply_discount(self, amount):
        self.logger.debug(f'Applying discount to amount: {amount}')
        discount = self.determine_discount()
        final_amount = amount - discount
        self.logger.debug(f'Final amount after discount: {final_amount}')
        self.process_payment(final_amount)

    @trace
    def determine_discount(self):
        self.logger.info('Determining discount.')
        # Incorrectly returning a string instead of a numeric value
        discount = "5"
        self.logger.debug(f'Discount computed: {discount}')
        return discount

    @trace
    def process_payment(self, amount):
        self.logger.info(f'Processing payment for amount: {amount}')
        if amount < 0:
            self.logger.warning('Warning: Negative payment amount detected.')
        # The bug will cause an exception when adding numbers and strings
        payment_result = amount + 0
        self.logger.debug(f'Payment processed: {payment_result}')
        if payment_result:
            self.logger.info('Payment successful.')
        else:
            self.logger.error('Payment failed.')

    @trace
    def audit_log(self, message):
        # Simulating a noisy log message not related to the bug
        self.logger.info(f'Audit log: {message}')
        self.logger.info('Queue depth: 42')
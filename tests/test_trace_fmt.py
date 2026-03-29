import logging
from tracelog import trace, TraceLogHandler, FileExporter

tmpfile = '/tmp/tracelog_test3.log'
logger = logging.getLogger('test')
logger.setLevel(logging.DEBUG)
handler = TraceLogHandler(exporter=FileExporter(tmpfile))
logger.addHandler(handler)

@trace
def validate_card(card: str) -> bool:
    raise ValueError('invalid card number')

@trace
def process_payment(amount: float):
    validate_card('1234')

try:
    process_payment(99.9)
except Exception as e:
    logger.error('payment error: %s', e)

with open(tmpfile) as f:
    import json
    for line in f:
        data = json.loads(line)
        for dsl in data['dsl_lines']:
            print(dsl)

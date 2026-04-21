import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict
from tracelog import trace


@dataclass
class Transaction:
    tx_id: str
    tx_type: str
    amount: float
    source_account: str
    destination_account: str


@dataclass
class SettlementRate:
    account: str
    tx_type: str
    multiplier: float


@dataclass
class LedgerEntry:
    tx_id: str
    account_id: str
    posted_amount: float
    tx_type: str


class Scenario:
    def __init__(self, logger):
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._lock = threading.Lock()
        self._settlement_rates: Dict[str, Dict[str, float]] = {
            "CASH":        {"TRANSFER": 1.00, "DEBIT":  1.00, "CREDIT": 1.02, "ADJUSTMENT": 1.00},
            "RECEIVABLE":  {"TRANSFER": 1.33, "DEBIT":  1.05, "CREDIT": 1.00, "ADJUSTMENT": 1.00},
            "PAYABLE":     {"TRANSFER": 1.00, "DEBIT":  1.00, "CREDIT": 1.00, "ADJUSTMENT": 1.01},
            "EQUITY":      {"TRANSFER": 1.00, "DEBIT":  1.00, "CREDIT": 1.00, "ADJUSTMENT": 1.00},
        }
        self._transactions: Dict[str, Transaction] = {
            "CREDIT":     Transaction("TX-C001", "CREDIT",      500.0, "RECEIVABLE", "REVENUE"),
            "DEBIT":      Transaction("TX-D001", "DEBIT",       300.0, "CASH",       "PAYABLE"),
            "TRANSFER":   Transaction("TX-T001", "TRANSFER",    750.0, "CASH",       "RECEIVABLE"),
            "ADJUSTMENT": Transaction("TX-A001", "ADJUSTMENT",  100.0, "EQUITY",     "RETAINED"),
        }
        self.ledger: List[LedgerEntry] = []
        self.total_posted: float = 0.0
        self.expected_total: float = 1650.0

    @trace
    def validate_transaction(self, tx: Transaction) -> bool:
        self.logger.info(f"Validating {tx.tx_id}: type={tx.tx_type}, amount={tx.amount:.2f}")
        if tx.amount <= 0:
            raise ValueError(f"Non-positive amount in {tx.tx_id}: {tx.amount}")
        self.logger.debug(f"{tx.tx_id} passed validation — source={tx.source_account}, dest={tx.destination_account}")
        return True

    @trace
    def get_settlement_multiplier(self, tx: Transaction) -> float:
        self.logger.info(f"Fetching settlement multiplier for {tx.tx_id}")
        account_rates = self._settlement_rates.get(tx.destination_account, {})
        multiplier = account_rates.get(tx.tx_type, 1.0)
        self.logger.debug(f"Multiplier for {tx.tx_id} via account={tx.destination_account}: {multiplier}")
        return multiplier

    @trace
    def apply_ledger_rule(self, tx: Transaction) -> float:
        self.logger.info(f"Applying ledger rule for {tx.tx_id}")
        multiplier = self.get_settlement_multiplier(tx)
        posting_amount = tx.amount * multiplier
        self.logger.debug(f"{tx.tx_id}: {tx.amount:.2f} x {multiplier} = {posting_amount:.2f}")
        return posting_amount

    @trace
    def record_entry(self, tx: Transaction, posting_amount: float):
        self.logger.info(f"Recording ledger entry for {tx.tx_id}: amount={posting_amount:.2f}")
        entry = LedgerEntry(
            tx_id=tx.tx_id,
            account_id=tx.destination_account,
            posted_amount=posting_amount,
            tx_type=tx.tx_type,
        )
        with self._lock:
            self.ledger.append(entry)
            self.total_posted += posting_amount
        self.logger.debug(f"Running total posted: {self.total_posted:.2f}")

    @trace
    def audit_entry(self, tx: Transaction, posting_amount: float):
        self.logger.debug(
            f"Audit — {tx.tx_id}: source={tx.source_account}, dest={tx.destination_account}, posted={posting_amount:.2f}"
        )

    @trace
    def verify_settlement(self):
        self.logger.info(f"Verifying settlement: posted={self.total_posted:.2f}, expected={self.expected_total:.2f}")
        delta = abs(self.total_posted - self.expected_total)
        self.logger.debug(f"Settlement delta: {delta:.4f}")
        if delta > 0.01:
            raise ValueError(
                f"Settlement mismatch: posted={self.total_posted:.2f}, expected={self.expected_total:.2f}"
            )

    @trace
    def process_transaction(self, tx_type: str):
        self.logger.info(f"Processor started: {tx_type}")
        tx = self._transactions[tx_type]
        self.validate_transaction(tx)
        posting_amount = self.apply_ledger_rule(tx)
        self.record_entry(tx, posting_amount)
        self.audit_entry(tx, posting_amount)
        self.logger.info(f"Processor completed: {tx_type}")

    @trace
    def run(self):
        self.logger.info("Ledger settlement pipeline started")
        tx_types = ["CREDIT", "DEBIT", "TRANSFER", "ADJUSTMENT"]
        futures = {self.executor.submit(self.process_transaction, t): t for t in tx_types}
        for future in as_completed(futures):
            tx_type = futures[future]
            try:
                future.result()
            except Exception as e:
                self.logger.error(f"Processor failed — {tx_type}: {str(e)}")
                self.executor.shutdown(wait=False)
                raise
        self.verify_settlement()
        self.logger.info("Settlement verification complete")
        self.executor.shutdown(wait=False)
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Dict
from tracelog import trace


@dataclass
class CategoryConfig:
    name: str
    tax_rate: float
    discount_rate: float
    min_margin: float
    supplier_code: str


@dataclass
class OrderItem:
    item_id: str
    base_price: float
    cost_basis: float
    quantity: int


@dataclass
class ProcessedBatch:
    category: str
    adjusted_prices: Dict[str, float]
    total_revenue: float = 0.0
    total_cost: float = 0.0


class Scenario:
    def __init__(self, logger):
        self.logger = logger
        self.executor = ThreadPoolExecutor(max_workers=4)
        self._configs = {
            "ELECTRONICS": CategoryConfig("ELECTRONICS", 1.12, 0.85, 0.08, "ELEC-001"),
            "APPAREL":     CategoryConfig("APPAREL",     1.07, 0.75, 0.12, "APPL-002"),
            "SEASONAL":    CategoryConfig("SEASONAL",    1.08, 0.65, 0.05, "SEAS-003"),
            "PERISHABLE":  CategoryConfig("PERISHABLE",  1.05, 0.90, 0.15, "PERI-004"),
        }
        self._items = {
            "ELECTRONICS": [
                OrderItem("E001", 299.99, 210.0, 5),
                OrderItem("E002", 149.99, 105.0, 10),
                OrderItem("E003",  89.99,  62.0, 15),
            ],
            "APPAREL": [
                OrderItem("A001", 59.99, 35.0, 20),
                OrderItem("A002", 89.99, 52.0, 15),
                OrderItem("A003", 34.99, 22.0, 30),
            ],
            "SEASONAL": [
                OrderItem("S001", 100.0, 80.0,  8),
                OrderItem("S002", 120.0, 95.0,  6),
                OrderItem("S003",  75.0, 60.0, 12),
            ],
            "PERISHABLE": [
                OrderItem("P001", 24.99, 18.0,  50),
                OrderItem("P002", 39.99, 28.0,  30),
                OrderItem("P003", 14.99, 11.0, 100),
            ],
        }
        self.dispatch_log: List[str] = []

    @trace
    def fetch_config(self, category: str) -> CategoryConfig:
        self.logger.info(f"Fetching configuration for category: {category}")
        config = self._configs[category]
        self.logger.debug(f"Config loaded — supplier: {config.supplier_code}, tax_rate: {config.tax_rate:.4f}")
        return config

    @trace
    def load_items(self, category: str) -> List[OrderItem]:
        self.logger.info(f"Loading order items for category: {category}")
        items = self._items[category]
        self.logger.debug(f"Loaded {len(items)} items for {category}")
        return items

    @trace
    def enrich_item_metadata(self, items: List[OrderItem], config: CategoryConfig) -> List[OrderItem]:
        self.logger.debug(f"Enriching {len(items)} items with supplier data for {config.name}")
        for item in items:
            self.logger.debug(f"  {item.item_id}: base={item.base_price:.2f}, cost={item.cost_basis:.2f}")
        return items

    @trace
    def apply_category_rules(self, config: CategoryConfig, items: List[OrderItem]) -> Dict[str, float]:
        self.logger.info(f"Applying pricing rules for category: {config.name}")
        adjusted = {}
        for item in items:
            if config.name == "SEASONAL":
                adjusted_price = item.base_price * config.tax_rate
            else:
                adjusted_price = item.base_price * config.tax_rate
            adjusted[item.item_id] = adjusted_price
            self.logger.debug(f"  {item.item_id}: {item.base_price:.2f} -> {adjusted_price:.2f}")
        return adjusted

    @trace
    def validate_margin(self, batch: ProcessedBatch, config: CategoryConfig):
        self.logger.info(f"Validating margin for {batch.category}: revenue={batch.total_revenue:.2f}, cost={batch.total_cost:.2f}")
        if batch.total_revenue <= 0:
            raise ValueError(f"Zero revenue for {batch.category}")
        margin = (batch.total_revenue - batch.total_cost) / batch.total_revenue
        self.logger.debug(f"Margin for {batch.category}: {margin:.4f}")
        if margin < 0:
            raise ValueError(f"Negative margin for {batch.category}: {margin:.4f}")

    @trace
    def compute_totals(self, batch: ProcessedBatch, items: List[OrderItem], config: CategoryConfig):
        self.logger.info(f"Computing totals for: {batch.category}")
        batch.total_revenue = sum(batch.adjusted_prices[item.item_id] * item.quantity for item in items)
        batch.total_cost = sum(item.cost_basis * item.quantity for item in items)
        self.logger.debug(f"Totals — revenue: {batch.total_revenue:.2f}, cost: {batch.total_cost:.2f}")
        self.validate_margin(batch, config)

    @trace
    def sync_dispatch_record(self, category: str, revenue: float):
        self.logger.debug(f"Syncing dispatch record — category: {category}, revenue: {revenue:.2f}")
        self.dispatch_log.append(category)

    @trace
    def submit_batch(self, batch: ProcessedBatch):
        self.logger.info(f"Submitting batch: {batch.category}")
        self.sync_dispatch_record(batch.category, batch.total_revenue)
        self.logger.info(f"Batch submitted: {batch.category}")

    @trace
    def process_category_worker(self, category: str):
        self.logger.info(f"Worker started: {category}")
        config = self.fetch_config(category)
        items = self.load_items(category)
        items = self.enrich_item_metadata(items, config)
        adjusted_prices = self.apply_category_rules(config, items)
        batch = ProcessedBatch(category=category, adjusted_prices=adjusted_prices)
        self.compute_totals(batch, items, config)
        self.submit_batch(batch)
        self.logger.info(f"Worker completed: {category}")

    @trace
    def run(self):
        self.logger.info("Order dispatch pipeline started")
        categories = ["ELECTRONICS", "APPAREL", "SEASONAL", "PERISHABLE"]
        futures = {self.executor.submit(self.process_category_worker, cat): cat for cat in categories}
        for future in as_completed(futures):
            cat = futures[future]
            try:
                future.result()
            except Exception as e:
                self.logger.error(f"Worker failed — {cat}: {str(e)}")
                self.executor.shutdown(wait=False)
                raise
        self.logger.info(f"Pipeline complete. Dispatched: {self.dispatch_log}")
        self.executor.shutdown(wait=False)
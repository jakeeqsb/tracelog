"""Operational benchmark scenarios used by the notebook-driven eval suite."""

from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tracelog import FileExporter, TraceLogHandler, get_buffer, trace
from tracelog.context import ContextManager


@dataclass(frozen=True)
class IncidentSpec:
    """One benchmark incident with sealed-truth metadata."""

    incident_id: str
    scenario_family: str
    variant_id: str
    difficulty: str
    split: str
    root_cause_id: str
    root_cause_function: str
    root_cause_type: str
    surface_error_function: str
    error_type: str
    expected_error_surface_chain: list[str]
    expected_evidence_markers: list[str]
    expected_fix_region: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def truth_payload(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "scenario_family": self.scenario_family,
            "variant_id": self.variant_id,
            "difficulty": self.difficulty,
            "root_cause_id": self.root_cause_id,
            "root_cause_function": self.root_cause_function,
            "root_cause_type": self.root_cause_type,
            "surface_error_function": self.surface_error_function,
            "error_type": self.error_type,
            "expected_error_surface_chain": self.expected_error_surface_chain,
            "expected_evidence_markers": self.expected_evidence_markers,
            "expected_fix_region": self.expected_fix_region,
        }


def incident_specs() -> tuple[IncidentSpec, ...]:
    """Returns the fixed benchmark matrix used by the notebook."""

    return (
        IncidentSpec(
            incident_id="checkout_coupon_flip_h1",
            scenario_family="ecommerce_bulk_checkout",
            variant_id="coupon_sign_flip",
            difficulty="hard",
            split="historical",
            root_cause_id="coupon_sign_flip",
            root_cause_function="normalize_coupon",
            root_cause_type="deep_propagated_state_bug",
            surface_error_function="charge_payment",
            error_type="ValueError",
            expected_error_surface_chain=[
                "process_bulk_checkout",
                "price_cart",
                "charge_payment",
            ],
            expected_evidence_markers=[
                "coupon_code=LEGACY15",
                "campaign=legacy-vip",
                "normalize_coupon returned 1.15",
                "gateway rejected non-positive authorization amount",
            ],
            expected_fix_region="normalize_coupon legacy discount parsing",
            parameters={
                "tenant": "north-america",
                "coupon_code": "LEGACY15",
                "campaign": "legacy-vip",
                "item_count": 34,
            },
        ),
        IncidentSpec(
            incident_id="checkout_coupon_flip_h2",
            scenario_family="ecommerce_bulk_checkout",
            variant_id="coupon_sign_flip",
            difficulty="hard",
            split="historical",
            root_cause_id="coupon_sign_flip",
            root_cause_function="normalize_coupon",
            root_cause_type="deep_propagated_state_bug",
            surface_error_function="charge_payment",
            error_type="ValueError",
            expected_error_surface_chain=[
                "process_bulk_checkout",
                "price_cart",
                "charge_payment",
            ],
            expected_evidence_markers=[
                "coupon_code=LEGACY20",
                "campaign=legacy-loyalty",
                "normalize_coupon returned 1.2",
                "gateway rejected non-positive authorization amount",
            ],
            expected_fix_region="normalize_coupon legacy discount parsing",
            parameters={
                "tenant": "eu-central",
                "coupon_code": "LEGACY20",
                "campaign": "legacy-loyalty",
                "item_count": 41,
            },
        ),
        IncidentSpec(
            incident_id="checkout_coupon_flip_q1",
            scenario_family="ecommerce_bulk_checkout",
            variant_id="coupon_sign_flip",
            difficulty="hard",
            split="query",
            root_cause_id="coupon_sign_flip",
            root_cause_function="normalize_coupon",
            root_cause_type="deep_propagated_state_bug",
            surface_error_function="charge_payment",
            error_type="ValueError",
            expected_error_surface_chain=[
                "process_bulk_checkout",
                "price_cart",
                "charge_payment",
            ],
            expected_evidence_markers=[
                "coupon_code=LEGACY18",
                "campaign=legacy-reengage",
                "normalize_coupon returned 1.18",
                "gateway rejected non-positive authorization amount",
            ],
            expected_fix_region="normalize_coupon legacy discount parsing",
            parameters={
                "tenant": "apac",
                "coupon_code": "LEGACY18",
                "campaign": "legacy-reengage",
                "item_count": 38,
            },
        ),
        IncidentSpec(
            incident_id="warehouse_snapshot_leak_h1",
            scenario_family="warehouse_sync_reservation",
            variant_id="snapshot_version_leak",
            difficulty="hard",
            split="historical",
            root_cause_id="snapshot_version_leak",
            root_cause_function="sync_warehouse_snapshot",
            root_cause_type="async_state_leak",
            surface_error_function="reserve_bin_stock",
            error_type="TimeoutError",
            expected_error_surface_chain=[
                "consume_order_event",
                "reconcile_delta",
                "reserve_bin_stock",
            ],
            expected_evidence_markers=[
                "expected_version=v48",
                "sync_warehouse_snapshot returned v41",
                "reservation timed out waiting for snapshot quorum",
            ],
            expected_fix_region="snapshot cache version handoff in sync_warehouse_snapshot",
            parameters={
                "warehouse_id": "SEA-01",
                "expected_version": "v48",
                "stale_version": "v41",
                "quantity": 7,
            },
        ),
        IncidentSpec(
            incident_id="warehouse_dedupe_collision_h1",
            scenario_family="warehouse_sync_reservation",
            variant_id="dedupe_key_collision",
            difficulty="hard",
            split="historical",
            root_cause_id="dedupe_key_collision",
            root_cause_function="build_dedupe_key",
            root_cause_type="doppelganger_error",
            surface_error_function="reserve_bin_stock",
            error_type="TimeoutError",
            expected_error_surface_chain=[
                "consume_order_event",
                "reconcile_delta",
                "reserve_bin_stock",
            ],
            expected_evidence_markers=[
                "build_dedupe_key truncated",
                "duplicate replay lane engaged",
                "reservation timed out waiting for snapshot quorum",
            ],
            expected_fix_region="dedupe key generation width in build_dedupe_key",
            parameters={
                "warehouse_id": "LAX-04",
                "expected_version": "v19",
                "stale_version": "v19",
                "quantity": 5,
            },
        ),
        IncidentSpec(
            incident_id="warehouse_snapshot_leak_q1",
            scenario_family="warehouse_sync_reservation",
            variant_id="snapshot_version_leak",
            difficulty="hard",
            split="query",
            root_cause_id="snapshot_version_leak",
            root_cause_function="sync_warehouse_snapshot",
            root_cause_type="async_state_leak",
            surface_error_function="reserve_bin_stock",
            error_type="TimeoutError",
            expected_error_surface_chain=[
                "consume_order_event",
                "reconcile_delta",
                "reserve_bin_stock",
            ],
            expected_evidence_markers=[
                "expected_version=v52",
                "sync_warehouse_snapshot returned v46",
                "reservation timed out waiting for snapshot quorum",
            ],
            expected_fix_region="snapshot cache version handoff in sync_warehouse_snapshot",
            parameters={
                "warehouse_id": "DFW-02",
                "expected_version": "v52",
                "stale_version": "v46",
                "quantity": 6,
            },
        ),
        IncidentSpec(
            incident_id="gateway_refresh_order_h1",
            scenario_family="api_gateway_audit",
            variant_id="tenant_refresh_ordering",
            difficulty="hard",
            split="historical",
            root_cause_id="tenant_refresh_ordering",
            root_cause_function="verify_token",
            root_cause_type="hidden_bad_input",
            surface_error_function="execute_business_action",
            error_type="PermissionError",
            expected_error_surface_chain=[
                "handle_request",
                "load_profile",
                "execute_business_action",
            ],
            expected_evidence_markers=[
                "requested_tenant=tenant-bravo",
                "verify_token returned tenant-alpha",
                "policy denied write_inventory",
            ],
            expected_fix_region="tenant refresh ordering in verify_token",
            parameters={
                "requested_tenant": "tenant-bravo",
                "stale_tenant": "tenant-alpha",
                "path": "/inventory/reprice",
            },
        ),
        IncidentSpec(
            incident_id="gateway_refresh_order_h2",
            scenario_family="api_gateway_audit",
            variant_id="tenant_refresh_ordering",
            difficulty="hard",
            split="historical",
            root_cause_id="tenant_refresh_ordering",
            root_cause_function="verify_token",
            root_cause_type="hidden_bad_input",
            surface_error_function="execute_business_action",
            error_type="PermissionError",
            expected_error_surface_chain=[
                "handle_request",
                "load_profile",
                "execute_business_action",
            ],
            expected_evidence_markers=[
                "requested_tenant=tenant-green",
                "verify_token returned tenant-blue",
                "policy denied approve_refund",
            ],
            expected_fix_region="tenant refresh ordering in verify_token",
            parameters={
                "requested_tenant": "tenant-green",
                "stale_tenant": "tenant-blue",
                "path": "/refunds/approve",
            },
        ),
        IncidentSpec(
            incident_id="gateway_tenant_cache_h1",
            scenario_family="api_gateway_audit",
            variant_id="tenant_cache_reuse",
            difficulty="hard",
            split="historical",
            root_cause_id="tenant_cache_reuse",
            root_cause_function="load_profile",
            root_cause_type="doppelganger_error",
            surface_error_function="execute_business_action",
            error_type="PermissionError",
            expected_error_surface_chain=[
                "handle_request",
                "load_profile",
                "execute_business_action",
            ],
            expected_evidence_markers=[
                "profile cache hit from previous tenant",
                "policy denied write_inventory",
            ],
            expected_fix_region="tenant cache key invalidation in load_profile",
            parameters={
                "requested_tenant": "tenant-bravo",
                "stale_tenant": "tenant-bravo",
                "path": "/inventory/reprice",
            },
        ),
        IncidentSpec(
            incident_id="gateway_refresh_order_q1",
            scenario_family="api_gateway_audit",
            variant_id="tenant_refresh_ordering",
            difficulty="hard",
            split="query",
            root_cause_id="tenant_refresh_ordering",
            root_cause_function="verify_token",
            root_cause_type="hidden_bad_input",
            surface_error_function="execute_business_action",
            error_type="PermissionError",
            expected_error_surface_chain=[
                "handle_request",
                "load_profile",
                "execute_business_action",
            ],
            expected_evidence_markers=[
                "requested_tenant=tenant-coral",
                "verify_token returned tenant-amber",
                "policy denied write_inventory",
            ],
            expected_fix_region="tenant refresh ordering in verify_token",
            parameters={
                "requested_tenant": "tenant-coral",
                "stale_tenant": "tenant-amber",
                "path": "/inventory/reprice",
            },
        ),
    )


def _reset_trace_context() -> None:
    ctx = ContextManager()
    ctx._trace_id.set("")
    ctx._span_id.set("")
    ctx._parent_span_id.set("")
    ctx._depth.set(0)
    try:
        get_buffer().clear()
    except Exception:
        pass


def _configure_logger(logger_name: str, mode: str, output_path: Path) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.handlers = []
    logger.propagate = False

    if mode == "standard":
        handler: logging.Handler = logging.FileHandler(output_path, mode="w")
        handler.setFormatter(
            logging.Formatter(
                "[%(asctime)s] [%(threadName)s] %(levelname)s %(name)s - %(message)s"
            )
        )
    else:
        handler = TraceLogHandler(
            exporter=FileExporter(str(output_path)),
            capacity=2000,
            max_chunks=100,
        )

    logger.addHandler(handler)
    return logger


def _propagate_to_worker(func, *args, **kwargs):
    ctx = ContextManager()
    propagated_trace = ctx.get_trace_id()
    propagated_parent = ctx.get_span_id()

    def _runner():
        worker_ctx = ContextManager()
        worker_ctx.set_trace_id(propagated_trace)
        worker_ctx.set_span_id("")
        worker_ctx.set_parent_span_id(propagated_parent)
        worker_ctx._depth.set(0)
        func(*args, **kwargs)

    thread_ctx = contextvars.copy_context()
    return thread_ctx.run(_runner)


class ECommerceBulkCheckoutScenario:
    def __init__(self, logger: logging.Logger, spec: IncidentSpec):
        self.logger = logger
        self.spec = spec

    @trace
    def process_bulk_checkout(self) -> None:
        params = self.spec.parameters
        items = self._build_items(params["item_count"])
        coupon_code = params["coupon_code"]
        tenant = params["tenant"]
        self.logger.info(
            "bulk checkout started cart=%s user=%s tenant=%s items=%d",
            self.spec.incident_id,
            f"user-{tenant}",
            tenant,
            len(items),
        )
        self.verify_session(tenant)
        receipt_summary = {"cart": self.spec.incident_id, "items": len(items)}
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="receipt") as pool:
            receipt_future = pool.submit(
                _propagate_to_worker, self.emit_receipt_worker, receipt_summary
            )
            discount_rate = self.normalize_coupon(coupon_code, params["campaign"])
            priced_items = self.price_cart(items, discount_rate)
            self.reserve_inventory(priced_items)
            total = sum(item["final_amount"] for item in priced_items)
            self.charge_payment(total, tenant)
            receipt_future.result()

    @trace
    def verify_session(self, tenant: str) -> dict[str, str]:
        self.logger.info("verifying session tenant=%s", tenant)
        self.logger.debug("session cache refreshed tenant=%s", tenant)
        return {"tenant": tenant, "state": "valid"}

    @trace
    def normalize_coupon(self, coupon_code: str, campaign: str) -> float:
        self.logger.debug("normalizing coupon campaign=%s code=%s", campaign, coupon_code)
        discount = float(coupon_code.replace("LEGACY", "")) / 100.0
        if self.spec.variant_id == "coupon_sign_flip":
            return 1.0 + discount
        return discount

    @trace
    def price_cart(self, items: list[dict[str, float]], discount_rate: float) -> list[dict[str, float]]:
        priced: list[dict[str, float]] = []
        for index, item in enumerate(items, 1):
            if index % 6 == 0:
                self.logger.warning(
                    "pricing noise shipping estimator recalculated sku=%s lane=%s",
                    item["sku"],
                    "ground",
                )
            else:
                self.logger.info("pricing item sku=%s qty=%d", item["sku"], item["qty"])

            gross = item["qty"] * item["unit_price"]
            final_amount = round(gross * (1 - discount_rate), 2)
            priced.append({**item, "gross": gross, "final_amount": final_amount})

        return priced

    @trace
    def reserve_inventory(self, priced_items: list[dict[str, float]]) -> None:
        for index, item in enumerate(priced_items, 1):
            if index % 11 == 0:
                self.logger.warning(
                    "inventory retry for sku=%s after lock wait", item["sku"]
                )
            else:
                self.logger.debug("inventory reserved sku=%s qty=%d", item["sku"], item["qty"])

    @trace
    def charge_payment(self, total_amount: float, tenant: str) -> str:
        self.logger.info(
            "charging payment tenant=%s total_amount=%.2f gateway=acme-pay",
            tenant,
            total_amount,
        )
        self.logger.warning("payment gateway retry scheduled due to jitter")
        if total_amount <= 0:
            raise ValueError("gateway rejected non-positive authorization amount")
        return "auth-ok"

    @trace
    def emit_receipt_worker(self, summary: dict[str, Any]) -> None:
        self.logger.info(
            "receipt worker flushed audit summary cart=%s items=%d",
            summary["cart"],
            summary["items"],
        )
        self.logger.debug("notification worker archived template render")

    def _build_items(self, item_count: int) -> list[dict[str, float]]:
        items = []
        for idx in range(item_count):
            items.append(
                {
                    "sku": f"SKU-{idx:03d}",
                    "qty": 1 + (idx % 3),
                    "unit_price": 18.0 + (idx % 5) * 2.5,
                }
            )
        return items


class WarehouseSyncScenario:
    def __init__(self, logger: logging.Logger, spec: IncidentSpec):
        self.logger = logger
        self.spec = spec

    @trace
    def consume_order_event(self) -> None:
        params = self.spec.parameters
        self.logger.info(
            "consuming order event incident=%s warehouse=%s qty=%d",
            self.spec.incident_id,
            params["warehouse_id"],
            params["quantity"],
        )
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="sync") as pool:
            snapshot_future = pool.submit(
                _propagate_to_worker,
                self.sync_warehouse_snapshot,
                params["warehouse_id"],
                params["expected_version"],
                params["stale_version"],
            )
            dedupe_key = self.build_dedupe_key(self.spec.incident_id)
            snapshot_version = snapshot_future.result()
            self.reconcile_delta(dedupe_key, snapshot_version)
            self.reserve_bin_stock(snapshot_version, params["expected_version"])

    @trace
    def build_dedupe_key(self, incident_id: str) -> str:
        self.logger.debug("building dedupe key incident=%s", incident_id)
        if self.spec.variant_id == "dedupe_key_collision":
            return incident_id[:12]
        return incident_id

    @trace
    def sync_warehouse_snapshot(
        self,
        warehouse_id: str,
        expected_version: str,
        stale_version: str,
    ) -> str:
        self.logger.info(
            "sync worker fetched snapshot warehouse=%s expected=%s",
            warehouse_id,
            expected_version,
        )
        self.logger.warning("snapshot worker observed cache churn on standby replica")
        if self.spec.variant_id == "snapshot_version_leak":
            return stale_version
        return expected_version

    @trace
    def reconcile_delta(self, dedupe_key: str, snapshot_version: str) -> dict[str, str]:
        self.logger.info(
            "reconciling delta dedupe_key=%s snapshot_version=%s",
            dedupe_key,
            snapshot_version,
        )
        if self.spec.variant_id == "dedupe_key_collision":
            self.logger.warning("duplicate replay lane engaged due to dedupe collision")
        return {"snapshot_version": snapshot_version}

    @trace
    def reserve_bin_stock(self, snapshot_version: str, expected_version: str) -> None:
        for attempt in range(1, 4):
            self.logger.info(
                "reservation attempt=%d snapshot_version=%s expected=%s",
                attempt,
                snapshot_version,
                expected_version,
            )
        self.publish_dead_letter("reservation_timeout")
        if (
            snapshot_version != expected_version
            or self.spec.variant_id == "dedupe_key_collision"
        ):
            raise TimeoutError("reservation timed out waiting for snapshot quorum")

    @trace
    def publish_dead_letter(self, reason: str) -> None:
        self.logger.warning("dead-letter publish queued reason=%s", reason)


class ApiGatewayAuditScenario:
    def __init__(self, logger: logging.Logger, spec: IncidentSpec):
        self.logger = logger
        self.spec = spec

    @trace
    def handle_request(self) -> None:
        params = self.spec.parameters
        self.logger.info(
            "request received path=%s requested_tenant=%s",
            params["path"],
            params["requested_tenant"],
        )
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="audit") as pool:
            audit_future = pool.submit(
                _propagate_to_worker,
                self.audit_worker_consume,
                {"path": params["path"], "tenant": params["requested_tenant"]},
            )
            token_context = self.verify_token(
                params["requested_tenant"], params["stale_tenant"]
            )
            profile = self.load_profile(
                params["requested_tenant"],
                token_context["tenant"],
            )
            self.push_audit_event(params["path"])
            self.execute_business_action(params["path"], profile)
            audit_future.result()

    @trace
    def verify_token(self, requested_tenant: str, stale_tenant: str) -> dict[str, str]:
        self.logger.info("verifying token requested_tenant=%s", requested_tenant)
        self.logger.warning("auth cache served stale refresh metadata")
        if self.spec.variant_id == "tenant_refresh_ordering":
            return {"tenant": stale_tenant, "token_state": "refreshed"}
        return {"tenant": requested_tenant, "token_state": "refreshed"}

    @trace
    def load_profile(
        self,
        requested_tenant: str,
        profile_tenant: str,
    ) -> dict[str, str]:
        self.logger.info(
            "loading profile requested_tenant=%s profile_tenant=%s",
            requested_tenant,
            profile_tenant,
        )
        if self.spec.variant_id == "tenant_cache_reuse":
            self.logger.warning("profile cache hit from previous tenant partition")
            profile_tenant = "tenant-shadow"
        return {"tenant": profile_tenant, "role": "inventory_writer"}

    @trace
    def push_audit_event(self, path: str) -> None:
        self.logger.debug("audit event buffered path=%s", path)
        self.logger.warning("audit queue depth exceeded soft watermark")

    @trace
    def execute_business_action(self, path: str, profile: dict[str, str]) -> None:
        required_tenant = self.spec.parameters["requested_tenant"]
        self.logger.info(
            "executing action path=%s profile_tenant=%s",
            path,
            profile["tenant"],
        )
        if profile["tenant"] != required_tenant:
            raise PermissionError("policy denied write_inventory")

    @trace
    def audit_worker_consume(self, event: dict[str, str]) -> None:
        self.logger.info(
            "audit worker consumed path=%s tenant=%s",
            event["path"],
            event["tenant"],
        )
        self.logger.debug("audit worker rotated shard cursor")


def run_incident(mode: str, spec: IncidentSpec, output_path: Path) -> None:
    """Runs one incident and writes either standard logs or TraceLog dumps."""

    _reset_trace_context()
    logger = _configure_logger(
        logger_name=f"tracelog.eval.{spec.incident_id}.{mode}",
        mode=mode,
        output_path=output_path,
    )

    try:
        if spec.scenario_family == "ecommerce_bulk_checkout":
            scenario = ECommerceBulkCheckoutScenario(logger, spec)
            scenario.process_bulk_checkout()
        elif spec.scenario_family == "warehouse_sync_reservation":
            scenario = WarehouseSyncScenario(logger, spec)
            scenario.consume_order_event()
        elif spec.scenario_family == "api_gateway_audit":
            scenario = ApiGatewayAuditScenario(logger, spec)
            scenario.handle_request()
        else:
            raise ValueError(f"Unknown scenario family: {spec.scenario_family}")
    except Exception:
        logger.exception("incident execution failed incident_id=%s", spec.incident_id)
    finally:
        for handler in list(logger.handlers):
            handler.flush()
            handler.close()
            logger.removeHandler(handler)


__all__ = ["IncidentSpec", "incident_specs", "run_incident"]

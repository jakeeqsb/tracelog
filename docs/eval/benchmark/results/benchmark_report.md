# TraceLog Real RAG Benchmark Report

Primary benchmark: `Standard Log + RAG + Code` vs `TraceLog + RAG + Code`

Ablation benchmark: `Standard Log + RAG` vs `TraceLog + RAG`

## Scenario Inventory
| incident_id | family | split | root_cause_function | surface_error_function | error_type |
| --- | --- | --- | --- | --- | --- |
| checkout_coupon_flip_h1 | ecommerce_bulk_checkout | historical | normalize_coupon | charge_payment | ValueError |
| checkout_coupon_flip_h2 | ecommerce_bulk_checkout | historical | normalize_coupon | charge_payment | ValueError |
| checkout_coupon_flip_q1 | ecommerce_bulk_checkout | query | normalize_coupon | charge_payment | ValueError |
| warehouse_snapshot_leak_h1 | warehouse_sync_reservation | historical | sync_warehouse_snapshot | reserve_bin_stock | TimeoutError |
| warehouse_dedupe_collision_h1 | warehouse_sync_reservation | historical | build_dedupe_key | reserve_bin_stock | TimeoutError |
| warehouse_snapshot_leak_q1 | warehouse_sync_reservation | query | sync_warehouse_snapshot | reserve_bin_stock | TimeoutError |
| gateway_refresh_order_h1 | api_gateway_audit | historical | verify_token | execute_business_action | PermissionError |
| gateway_refresh_order_h2 | api_gateway_audit | historical | verify_token | execute_business_action | PermissionError |
| gateway_tenant_cache_h1 | api_gateway_audit | historical | load_profile | execute_business_action | PermissionError |
| gateway_refresh_order_q1 | api_gateway_audit | query | verify_token | execute_business_action | PermissionError |

## Dataset Generation Status
| incident_id | standard_log | tracelog_dump | aggregated_trace | truth |
| --- | --- | --- | --- | --- |
| checkout_coupon_flip_h1 | True | True | True | True |
| checkout_coupon_flip_h2 | True | True | True | True |
| checkout_coupon_flip_q1 | True | True | True | True |
| warehouse_snapshot_leak_h1 | True | True | True | True |
| warehouse_dedupe_collision_h1 | True | True | True | True |
| warehouse_snapshot_leak_q1 | True | True | True | True |
| gateway_refresh_order_h1 | True | True | True | True |
| gateway_refresh_order_h2 | True | True | True | True |
| gateway_tenant_cache_h1 | True | True | True | True |
| gateway_refresh_order_q1 | True | True | True | True |

## Historical / Query Split
| split | count | families |
| --- | --- | --- |
| historical | 7 | api_gateway_audit, ecommerce_bulk_checkout, warehouse_sync_reservation |
| query | 3 | api_gateway_audit, ecommerce_bulk_checkout, warehouse_sync_reservation |

## Retrieval Evaluation (Ablation Lens)
| condition | SameRootCauseHit@1 | SameRootCauseHit@3 | MRR | nDCG@3 |
| --- | --- | --- | --- | --- |
| Standard Log + RAG | 1.0 | 1.0 | 1.0 | 1.0 |
| TraceLog + RAG | 1.0 | 1.0 | 1.0 | 0.9732 |

## Diagnosis Evaluation (Primary First)
| condition | root_cause_accuracy | surface_accuracy | evidence_match | actionability |
| --- | --- | --- | --- | --- |
| Standard Log + RAG + Code | 0.3333 | 1.0 | 0.65 | 0.5333 |
| TraceLog + RAG + Code | 0.6667 | 1.0 | 0.6 | 0.7333 |
| Standard Log + RAG | 0.0 | 0.0 | 0.5 | 0.3667 |
| TraceLog + RAG | 0.0 | 1.0 | 0.5667 | 0.6667 |

## Failure Case Review
| incident_id | condition | predicted_root_cause | expected_root_cause | judge_reason |
| --- | --- | --- | --- | --- |
| checkout_coupon_flip_q1 | Standard Log + RAG | charge_payment | normalize_coupon | The analyst incorrectly identified 'charge_payment' as the root cause function instead of 'normalize_coupon'. The surface error function is also misidentified as 'run_incident' rather than 'charge_payment'. While there is some grounding in the evidence provided, it does not fully align with the expected evidence markers from the sealed truth, leading to a lower actionability score. |
| checkout_coupon_flip_q1 | TraceLog + RAG | ECommerceBulkCheckoutScenario.price_cart | normalize_coupon | The analyst incorrectly identified the root cause function as 'price_cart' instead of 'normalize_coupon', which is the actual function responsible for the error. However, the surface error function 'charge_payment' is correctly identified. The evidence grounding is moderate as some evidence markers align, but not all. Actionability is relatively high since the analyst provides a clear expected fix region. |
| checkout_coupon_flip_q1 | Standard Log + RAG + Code | price_cart | normalize_coupon | The analyst incorrectly identified the root cause function as 'price_cart' instead of 'normalize_coupon', which is the actual function responsible for the error. However, the surface error function 'charge_payment' is correctly identified. The evidence grounding is moderate as some evidence markers relate to the error but do not fully align with the expected evidence markers from the sealed truth. Actionability is low due to the misidentification of the root cause function, which affects the ability to implement a fix. |
| checkout_coupon_flip_q1 | TraceLog + RAG + Code | ECommerceBulkCheckoutScenario.price_cart | normalize_coupon | The analyst incorrectly identified the root cause function as 'price_cart' instead of 'normalize_coupon', which is the actual function responsible for the error. However, the surface error function 'charge_payment' is correctly identified. The evidence grounding is moderate as some evidence markers align, but not all. Actionability is relatively high since the analyst's diagnosis points to a specific function that can be fixed. |
| warehouse_snapshot_leak_q1 | Standard Log + RAG | reserve_bin_stock | sync_warehouse_snapshot | The analyst incorrectly identified 'reserve_bin_stock' as the root cause function instead of 'sync_warehouse_snapshot', which is responsible for the snapshot version leak. The surface error function is also misidentified; the expected error surface chain indicates that 'reserve_bin_stock' is not the initial function causing the timeout. The evidence provided does not fully align with the expected evidence markers, and the expected fix region differs from the sealed truth. |
| warehouse_snapshot_leak_q1 | TraceLog + RAG | WarehouseSyncScenario.reconcile_delta | sync_warehouse_snapshot | The analyst incorrectly identified the root cause function as 'reconcile_delta' instead of the correct 'sync_warehouse_snapshot'. However, the surface error function 'reserve_bin_stock' is correctly identified. The evidence grounding is moderate as some evidence markers align with the expected ones, but not all. Actionability is relatively high since the analyst's diagnosis provides a clear path to address the timeout error. |
| gateway_refresh_order_q1 | Standard Log + RAG | tracelog.eval.gateway_refresh_order_q1.standard | verify_token | The analyst's diagnosis identifies a PermissionError but attributes it to incorrect tenant profile handling rather than the expected root cause function 'verify_token'. The evidence markers provided do not align closely with the expected evidence markers from the sealed truth, leading to a lower grounding score. The actionability score is also reduced due to the mismatch in the expected fix region. |
| gateway_refresh_order_q1 | TraceLog + RAG | ApiGatewayAuditScenario.load_profile | verify_token | The analyst incorrectly identified the root cause function as 'ApiGatewayAuditScenario.load_profile' instead of 'verify_token'. However, the surface error function 'execute_business_action' is correctly identified. The evidence grounding is moderate as some evidence markers align with the expected ones, but not all. Actionability is somewhat low due to the misidentification of the root cause function, which may lead to ineffective fixes. |
| gateway_refresh_order_q1 | Standard Log + RAG + Code | load_profile | verify_token | The analyst incorrectly identified the root cause function as 'load_profile' instead of the correct 'verify_token'. However, the surface error function 'execute_business_action' is correctly identified. The evidence markers provided by the analyst align with the expected evidence markers, but the root cause identification is flawed, affecting the overall accuracy. |

## Token / Latency Summary
| condition | input_tokens | output_tokens | total_tokens | retrieval_latency | diagnosis_latency | time_to_verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Standard Log + RAG + Code | 3861.67 | 184.0 | 4045.67 | 0.0663 | 4.6404 | 4.7067 |
| TraceLog + RAG + Code | 4773.67 | 178.33 | 4952.0 | 0.0652 | 4.242 | 4.3072 |
| Standard Log + RAG | 2850.33 | 181.33 | 3031.67 | 0.0574 | 4.9269 | 4.9843 |
| TraceLog + RAG | 3762.33 | 201.33 | 3963.67 | 0.0569 | 4.6645 | 4.7214 |

## Final Verdict

### Primary Benchmark
- Primary condition: `Standard Log + RAG + Code` vs `TraceLog + RAG + Code`
- Primary benchmark pass: `False`
- TraceLog root cause accuracy delta: `0.333`
- TraceLog surface accuracy delta: `0.000`
- Primary improved families: `api_gateway_audit`

### Ablation
- Ablation condition: `Standard Log + RAG` vs `TraceLog + RAG`
- Logs-only ablation pass: `False`
- TraceLog root cause accuracy delta: `0.000`
- TraceLog SameRootCauseHit@3 delta: `0.000`
- Ablation improved families: `none`

The primary benchmark is now the code-aware comparison, because that better matches the product goal of diagnosing live incidents with historical context and relevant code. The logs-only comparison remains valuable, but only as an ablation on formatting and retrieval behavior.

This notebook now treats the code-aware path as the primary product benchmark.
The logs-only comparison remains as an ablation to isolate formatting effects.
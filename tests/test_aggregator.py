import pytest

from tracelog.ingestion import TraceDump, aggregate_dumps, aggregate_traces


class TestAggregateDumps:
    def test_aggregate_dumps_returns_empty_string_for_empty_input(self):
        assert aggregate_dumps([]) == ""

    def test_aggregate_dumps_renders_single_dump(self):
        dump = TraceDump(
            trace_id="TRACE123",
            span_id="SPAN_A",
            parent_span_id=None,
            timestamp="2026-03-08T10:00:00Z",
            dsl_lines=[
                ">> process_payment(order_id='ORD-1')",
                "  .. [INFO] Validating payment",
                "<< 'Payment complete'",
            ],
        )

        rendered = aggregate_dumps([dump])

        assert rendered == "\n".join(
            [
                "=== [TraceLog] Unified Trace (trace_id: TRACE123) ===",
                ">> process_payment(order_id='ORD-1')",
                "  .. [INFO] Validating payment",
                "<< 'Payment complete'",
            ]
        )

    def test_aggregate_dumps_stitches_child_before_parent_terminator(self):
        root = TraceDump(
            trace_id="TRACE123",
            span_id="SPAN_A",
            parent_span_id=None,
            timestamp="2026-03-08T10:00:00Z",
            dsl_lines=[
                ">> process_payment()",
                "  .. [INFO] Spawning email worker",
                "<< 'Payment complete'",
            ],
        )
        child = TraceDump(
            trace_id="TRACE123",
            span_id="SPAN_B",
            parent_span_id="SPAN_A",
            timestamp="2026-03-08T10:00:01Z",
            dsl_lines=[
                ">> send_email()",
                "  !! ConnectionError: SMTP server unreachable",
            ],
        )

        rendered = aggregate_dumps([child, root])

        assert rendered == "\n".join(
            [
                "=== [TraceLog] Unified Trace (trace_id: TRACE123) ===",
                ">> process_payment()",
                "  .. [INFO] Spawning email worker",
                "  >> send_email()",
                "    !! ConnectionError: SMTP server unreachable",
                "<< 'Payment complete'",
            ]
        )

    def test_aggregate_dumps_renders_deeply_nested_spans_with_spaces(self):
        dumps = [
            {
                "trace_id": "TRACE123",
                "span_id": "SPAN_A",
                "parent_span_id": None,
                "timestamp": "2026-03-08T10:00:00Z",
                "dsl_lines": [">> a()", "<< 'done'"],
            },
            {
                "trace_id": "TRACE123",
                "span_id": "SPAN_B",
                "parent_span_id": "SPAN_A",
                "timestamp": "2026-03-08T10:00:01Z",
                "dsl_lines": [">> b()", "<< 'middle'"],
            },
            {
                "trace_id": "TRACE123",
                "span_id": "SPAN_C",
                "parent_span_id": "SPAN_B",
                "timestamp": "2026-03-08T10:00:02Z",
                "dsl_lines": [">> c()", "!! ValueError: boom"],
            },
        ]

        rendered = aggregate_dumps(dumps)

        assert rendered == "\n".join(
            [
                "=== [TraceLog] Unified Trace (trace_id: TRACE123) ===",
                ">> a()",
                "  >> b()",
                "    >> c()",
                "    !! ValueError: boom",
                "  << 'middle'",
                "<< 'done'",
            ]
        )

    def test_aggregate_dumps_rejects_mixed_trace_ids(self):
        dumps = [
            {
                "trace_id": "TRACE123",
                "span_id": "SPAN_A",
                "parent_span_id": None,
                "dsl_lines": [">> a()"],
            },
            {
                "trace_id": "TRACE999",
                "span_id": "SPAN_B",
                "parent_span_id": None,
                "dsl_lines": [">> b()"],
            },
        ]

        with pytest.raises(ValueError, match="aggregate_dumps\\(\\) expects dumps"):
            aggregate_dumps(dumps)


class TestAggregateTraces:
    def test_aggregate_traces_groups_multiple_trace_ids(self):
        dumps = [
            {
                "trace_id": "TRACE123",
                "span_id": "SPAN_A",
                "parent_span_id": None,
                "timestamp": "2026-03-08T10:00:00Z",
                "dsl_lines": [">> a()"],
            },
            {
                "trace_id": "TRACE999",
                "span_id": "SPAN_B",
                "parent_span_id": None,
                "timestamp": "2026-03-08T10:00:01Z",
                "dsl_lines": [">> b()"],
            },
        ]

        aggregated = aggregate_traces(dumps)

        assert set(aggregated) == {"TRACE123", "TRACE999"}
        assert aggregated["TRACE123"].endswith(">> a()")
        assert aggregated["TRACE999"].endswith(">> b()")

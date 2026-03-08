"""Aggregate fragmented TraceLog JSON dumps into unified Trace-DSL text."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TraceDump:
    """Represents one JSON dump emitted by a ``TraceExporter``.

    Attributes:
        trace_id: Stable identifier for one logical execution flow.
        span_id: Identifier for the active span that emitted the dump.
        parent_span_id: Identifier of the parent span, if one exists.
        timestamp: Optional ISO-8601 timestamp emitted by the exporter.
        dsl_lines: Original Trace-DSL lines captured in the dump.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    timestamp: str | None = None
    dsl_lines: list[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "TraceDump":
        """Builds a ``TraceDump`` from a JSON-compatible mapping.

        Args:
            data: Mapping that contains dump fields such as ``trace_id``,
                ``span_id``, ``parent_span_id``, ``timestamp``, and ``dsl_lines``.

        Returns:
            A normalized ``TraceDump`` instance.

        Raises:
            KeyError: If required keys such as ``trace_id`` or ``span_id`` are
                missing from ``data``.
            TypeError: If ``dsl_lines`` is not a list.
        """
        trace_id = str(data["trace_id"])
        span_id = str(data["span_id"])

        parent_span_id = data.get("parent_span_id")
        if parent_span_id in ("", None):
            parent_span_id = None
        else:
            parent_span_id = str(parent_span_id)

        timestamp = data.get("timestamp")
        if timestamp is not None:
            timestamp = str(timestamp)

        dsl_lines = data.get("dsl_lines", [])
        if not isinstance(dsl_lines, list):
            raise TypeError("dsl_lines must be a list of strings")

        return cls(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            timestamp=timestamp,
            dsl_lines=[str(line) for line in dsl_lines],
        )


def aggregate_traces(
    dumps: Iterable[TraceDump | Mapping[str, Any]],
) -> dict[str, str]:
    """Aggregates mixed dumps into unified traces grouped by ``trace_id``.

    Args:
        dumps: Iterable of ``TraceDump`` objects or JSON-compatible mappings.

    Returns:
        A mapping from ``trace_id`` to one unified Trace-DSL string per trace.
    """
    normalized = [_coerce_dump(dump) for dump in dumps]
    grouped: dict[str, list[TraceDump]] = defaultdict(list)
    for dump in normalized:
        grouped[dump.trace_id].append(dump)

    return {
        trace_id: aggregate_dumps(trace_dumps)
        for trace_id, trace_dumps in sorted(grouped.items())
    }


def aggregate_dumps(dumps: Iterable[TraceDump | Mapping[str, Any]]) -> str:
    """Aggregates dumps from one trace into one unified Trace-DSL string.

    Args:
        dumps: Iterable of ``TraceDump`` objects or JSON-compatible mappings
            that all belong to the same ``trace_id``.

    Returns:
        One unified Trace-DSL string. Returns an empty string when ``dumps`` is
        empty.

    Raises:
        ValueError: If the input contains dumps from more than one ``trace_id``.
    """
    normalized = [_coerce_dump(dump) for dump in dumps]
    if not normalized:
        return ""

    trace_ids = {dump.trace_id for dump in normalized}
    if len(trace_ids) != 1:
        raise ValueError(
            "aggregate_dumps() expects dumps from exactly one trace_id. "
            "Use aggregate_traces() for mixed inputs."
        )

    trace_id = normalized[0].trace_id
    by_span = {dump.span_id: dump for dump in normalized}
    children: dict[str, list[TraceDump]] = defaultdict(list)
    roots: list[TraceDump] = []

    for dump in _sorted_dumps(normalized):
        parent_span_id = dump.parent_span_id
        if parent_span_id and parent_span_id in by_span:
            children[parent_span_id].append(dump)
        else:
            roots.append(dump)

    rendered_lines = [f"=== [TraceLog] Unified Trace (trace_id: {trace_id}) ==="]
    for root in _sorted_dumps(roots):
        rendered_lines.extend(_render_span(root, children, depth=0))

    return "\n".join(rendered_lines)


def _coerce_dump(dump: TraceDump | Mapping[str, Any]) -> TraceDump:
    """Normalizes one dump input into a ``TraceDump`` instance.

    Args:
        dump: ``TraceDump`` object or JSON-compatible mapping.

    Returns:
        A normalized ``TraceDump`` instance.
    """
    if isinstance(dump, TraceDump):
        return dump
    return TraceDump.from_mapping(dump)


def _sorted_dumps(dumps: Iterable[TraceDump]) -> list[TraceDump]:
    """Sorts dumps deterministically for stable aggregation output.

    Args:
        dumps: Iterable of ``TraceDump`` objects.

    Returns:
        A list sorted by timestamp and then by ``span_id``.
    """
    return sorted(
        dumps,
        key=lambda dump: (
            dump.timestamp is None,
            dump.timestamp or "",
            dump.span_id,
        ),
    )


def _render_span(
    dump: TraceDump,
    children: Mapping[str, list[TraceDump]],
    depth: int,
) -> list[str]:
    """Renders one span subtree into indented Trace-DSL lines.

    Args:
        dump: Span dump to render.
        children: Mapping from parent ``span_id`` to child dumps.
        depth: Current render depth. Each level adds two leading spaces.

    Returns:
        A list of rendered Trace-DSL lines for the span subtree.
    """
    prefix = "  " * depth
    local_lines = [f"{prefix}{line}" if line else prefix for line in dump.dsl_lines]

    child_lines: list[str] = []
    for child in _sorted_dumps(children.get(dump.span_id, [])):
        child_lines.extend(_render_span(child, children, depth + 1))

    if not child_lines:
        return local_lines

    split_at = _find_insertion_index(dump.dsl_lines)
    return local_lines[:split_at] + child_lines + local_lines[split_at:]


def _find_insertion_index(lines: list[str]) -> int:
    """Finds where child spans should be inserted in a parent span body.

    Child spans are inserted before trailing top-level terminators such as
    ``<<`` or ``!!`` so that nested work appears before the parent closes.

    Args:
        lines: Trace-DSL lines that belong to one span.

    Returns:
        The insertion index for rendered child spans.
    """
    if not lines:
        return 0

    first_line = lines[0]
    base_indent = len(first_line) - len(first_line.lstrip(" "))
    index = len(lines)

    while index > 0:
        current = lines[index - 1]
        stripped = current.lstrip(" ")
        indent = len(current) - len(stripped)
        if indent == base_indent and (
            stripped.startswith("<< ") or stripped.startswith("!! ")
        ):
            index -= 1
            continue
        break

    return index

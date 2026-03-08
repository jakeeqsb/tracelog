import io
import json

import pytest

from tracelog.buffer import LogEntry
from tracelog.context import ContextManager
from tracelog.exporter import FileExporter, StreamExporter


def _entries() -> list[LogEntry]:
    return [
        LogEntry(1.0, ".. [INFO] step one", level=20),
        LogEntry(2.0, "!! boom", level=40),
    ]


@pytest.fixture(autouse=True)
def reset_context():
    ContextManager._trace_id.set("")
    ContextManager._span_id.set("")
    ContextManager._parent_span_id.set("")
    yield
    ContextManager._trace_id.set("")
    ContextManager._span_id.set("")
    ContextManager._parent_span_id.set("")


class TestStreamExporter:
    def test_stream_exporter_writes_json_dump(self):
        stream = io.StringIO()
        exporter = StreamExporter(stream=stream, show_timestamp=False)
        ctx = ContextManager()
        ctx._trace_id.set("trace123")
        ctx._span_id.set("span1234")
        ctx._parent_span_id.set("root5678")

        exporter.export(_entries())

        payload = json.loads(stream.getvalue().strip())
        assert payload["trace_id"] == "trace123"
        assert payload["span_id"] == "span1234"
        assert payload["parent_span_id"] == "root5678"
        assert payload["dsl_lines"] == [".. [INFO] step one", "!! boom"]
        assert payload["timestamp"]


class TestFileExporter:
    def test_file_exporter_appends_json_lines(self, tmp_path):
        path = tmp_path / "trace.log"
        exporter = FileExporter(str(path))
        ctx = ContextManager()
        ctx._trace_id.set("trace123")
        ctx._span_id.set("span1234")
        ctx._parent_span_id.set("")

        exporter.export(_entries())

        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["trace_id"] == "trace123"
        assert payload["span_id"] == "span1234"
        assert payload["parent_span_id"] is None
        assert payload["dsl_lines"] == [".. [INFO] step one", "!! boom"]

    def test_file_exporter_rotates_when_max_bytes_exceeded(self, tmp_path):
        path = tmp_path / "trace.log"
        path.write_text("x" * 100, encoding="utf-8")
        exporter = FileExporter(str(path), max_bytes=50)
        ctx = ContextManager()
        ctx._trace_id.set("trace123")
        ctx._span_id.set("span1234")
        ctx._parent_span_id.set("")

        exporter.export(_entries())

        backup = path.with_name(path.name + ".bak")
        assert backup.exists()
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["dsl_lines"] == [".. [INFO] step one", "!! boom"]

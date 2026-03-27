"""Tests for TraceTreeSplitter — tiered break point thresholds (Option B).

Covers:
    - Primary tier: indent<=2 >> splits at >= 1.0x chunk_size
    - Secondary tier: indent<=4 >> splits at >= 1.5x chunk_size
    - Hard cap: any >> splits at >= 2.0x chunk_size
    - No split below primary threshold
    - Context injection preserved after tiered split
"""

from tracelog.chunking.splitter import TraceTreeSplitter


def _splitter(chunk_size: int = 100) -> TraceTreeSplitter:
    return TraceTreeSplitter(chunk_size=chunk_size, chunk_overlap=0)


def _info(n_chars: int = 50) -> str:
    """Returns a `.. [INFO] ...` line of exactly n_chars total length."""
    prefix = ".. [INFO] "
    return prefix + "a" * max(0, n_chars - len(prefix))


class TestPrimaryTier:
    """indent<=2 >> splits at >= 1.0x (existing behavior regression)."""

    def test_top_level_call_triggers_split_after_threshold(self):
        # chunk_size=100. Two padding lines (50 each) fill past 100 chars,
        # then a top-level >> (indent=0) should start a new chunk.
        padding = _info(50)
        text = "\n".join([
            ">> func_a()",   # 11 chars
            padding,          # → ~62
            padding,          # → ~113 (exceeds 100)
            ">> func_b()",   # indent=0 → primary split
            "  .. [INFO] done",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert ">> func_a()" in chunks[0]
        assert ">> func_b()" in chunks[1]

    def test_indent2_call_triggers_split(self):
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,          # → ~62
            padding,          # → ~113
            "  >> sibling()",  # indent=2, still primary tier
            "    .. [INFO] ok",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert "  >> sibling()" in chunks[1]

    def test_no_split_below_threshold(self):
        text = "\n".join([
            ">> func_a()",
            "  .. [INFO] short",
            ">> func_b()",
            "  .. [INFO] also short",
        ])
        chunks = _splitter(500).split_text(text)
        assert len(chunks) == 1


class TestSecondaryTier:
    """indent<=4 >> does NOT split between 1.0x–1.5x, but DOES split at >=1.5x."""

    def test_deep_call_not_split_between_1x_and_1_5x(self):
        # chunk_size=100. After ~113 chars (>100), deep_1 at indent=4 should NOT split
        # because current_size < 150 (1.5x).
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,            # → ~62
            padding,            # → ~113 (exceeds 100)
            "    >> deep_1()",  # indent=4; current_size ~113 < 150 → NO split
            "      .. [INFO] still in first chunk",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 1
        assert ">> deep_1()" in chunks[0]

    def test_deep_call_splits_at_1_5x(self):
        # After ~180 chars (>=150), deep_2 at indent=4 SHOULD split.
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,            # → ~62
            padding,            # → ~113
            "    >> deep_1()",  # indent=4; ~113 < 150 → no split; adds to chunk; → ~129
            padding,            # → ~180 (exceeds 150)
            "    >> deep_2()",  # indent=4; ~180 >= 150 → SPLIT
            "      .. [INFO] in second chunk",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert ">> deep_1()" in chunks[0]
        assert ">> deep_2()" in chunks[1]

    def test_indent3_also_qualifies_for_secondary(self):
        # indent=3 is within <=4, should also trigger secondary split.
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,
            padding,            # → ~113
            "    >> deep()",    # indent=4; ~113 < 150 → no split
            padding,            # → ~179
            "   >> indent3()",  # indent=3; ~179 >= 150 → SPLIT
            "     .. [INFO] in second chunk",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert "   >> indent3()" in chunks[1]


class TestHardCap:
    """Any >> triggers split at >= 2.0x chunk_size."""

    def test_very_deep_call_not_split_between_1_5x_and_2x(self):
        # chunk_size=100. After ~198 chars (>=150 but <200), very_deep at indent=6
        # should NOT split (max_indent=4, indent=6 not <=4).
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,                    # → ~62
            padding,                    # → ~113
            "    >> mid()",             # indent=4; ~113 < 150 → no split; → ~126
            padding,                    # → ~177
            "      >> very_deep()",    # indent=6; ~177 < 200 → max_indent=4; NO split
            "        .. [INFO] still in chunk",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 1
        assert ">> very_deep()" in chunks[0]

    def test_very_deep_call_splits_at_2x(self):
        # After ~249 chars (>=200), very_deep_2 at indent=6 SHOULD split (max_indent=999).
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,                      # → ~62
            padding,                      # → ~113
            "    >> mid()",               # indent=4; ~113 < 150 → no split; → ~126
            padding,                      # → ~177
            "      >> very_deep()",      # indent=6; ~177 < 200 → NO split; → ~198
            padding,                      # → ~249 (exceeds 200)
            "      >> very_deep_2()",    # indent=6; ~249 >= 200 → any >> → SPLIT
            "        .. [INFO] in second chunk",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert ">> very_deep()" in chunks[0]
        assert ">> very_deep_2()" in chunks[1]

    def test_indent5_qualifies_for_hard_cap_only(self):
        # indent=5 does NOT qualify for secondary (<=4), but does for hard cap (<=999).
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,
            padding,                    # → ~113
            "     >> indent5_1()",      # indent=5; ~113 < 150 → NO split
            padding,                    # → ~179
            "     >> indent5_2()",      # indent=5; ~179 < 200 → max_indent=4; NO split
            padding,                    # → ~250
            "     >> indent5_3()",      # indent=5; ~250 >= 200 → max_indent=999 → SPLIT
            "       .. [INFO] ok",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert ">> indent5_1()" in chunks[0]
        assert ">> indent5_2()" in chunks[0]
        assert ">> indent5_3()" in chunks[1]


class TestContextInjection:
    """Context injection still works correctly after tiered splits."""

    def test_error_path_injected_after_secondary_split(self):
        # Split triggered at secondary tier (indent=4).
        # The chunk containing !! should have context injection markers.
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,
            padding,            # → ~113
            "    >> deep_1()",  # no split (~113 < 150)
            padding,            # → ~179
            "    >> deep_2()",  # SPLIT (~179 >= 150)
            "      !! ValueError: test error",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        last_chunk = chunks[-1]
        assert "!! ValueError: test error" in last_chunk
        assert "# [TraceTree] Context Injected" in last_chunk

    def test_error_path_injected_after_hard_cap_split(self):
        # Split triggered at hard cap (indent=6).
        padding = _info(50)
        text = "\n".join([
            ">> outer()",
            padding,
            padding,
            "    >> mid()",
            padding,
            "      >> very_deep()",
            padding,                        # → past 200
            "      >> very_deep_2()",       # SPLIT (hard cap)
            "        !! RuntimeError: boom",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        last_chunk = chunks[-1]
        assert "!! RuntimeError: boom" in last_chunk
        assert "# [TraceTree] Context Injected" in last_chunk

    def test_no_injection_when_error_already_passed(self):
        # Error is in the FIRST chunk — second chunk should have no injection.
        padding = _info(50)
        text = "\n".join([
            ">> erroring_func()",
            "  !! ValueError: early error",
            padding,
            padding,            # → past 100
            ">> clean_func()",  # split here (primary)
            "  .. [INFO] all good",
        ])
        chunks = _splitter(100).split_text(text)
        assert len(chunks) == 2
        assert "# [TraceTree] Context Injected" not in chunks[1]

"""TraceLog tree-aware text splitter.

Provides TraceTreeSplitter, a structure-aware chunker designed specifically
for Trace-DSL log format. Unlike character-based splitters, it preserves
the parent call context (function call hierarchy) when splitting long traces.
"""

from typing import List

from langchain_text_splitters import TextSplitter


class TraceTreeSplitter(TextSplitter):
    """A TextSplitter designed specifically for Trace-DSL format.

    Chunks Trace-DSL text based on logical tree boundaries (>> and <<).
    Guarantees that the chunk containing the error line (!!) also contains
    its parent call context (>> parent_func(...)) to preserve call hierarchy.

    Args:
        chunk_size: Maximum character size per chunk. Alias: max_chunk_size.
        chunk_overlap: Unused (kept for LangChain interface compatibility).

    Example:
        splitter = TraceTreeSplitter(chunk_size=4000)
        chunks = splitter.split_text(dump_text)
        error_chunks = [c for c in chunks if "!!" in c]
    """

    def __init__(self, chunk_size: int = 4000, chunk_overlap: int = 0, **kwargs):
        """Initializes the splitter.

        Args:
            chunk_size: Max characters per chunk.
            chunk_overlap: Kept for interface compatibility (not used).
            **kwargs: Passed to LangChain TextSplitter base class.
        """
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap, **kwargs)
        self.max_chunk_size = chunk_size

    def split_text(self, text: str) -> List[str]:
        """Splits Trace-DSL text into context-preserving chunks.

        Performs two passes:
          1. Identify the error line (!! marker) and record the active call
             stack leading to it (error_path).
          2. Split into chunks at top-level >> boundaries, injecting the
             error_path context at the start of each new chunk when the
             error is upcoming.

        Args:
            text: The full Trace-DSL dump text.

        Returns:
            List of chunk strings, each self-contained with parent context.
        """
        lines = text.split("\n")
        chunks = []

        # Pass 1: find error line and snapshot its active call stack
        error_path: list[tuple[int, str]] = []
        current_path: list[tuple[int, str]] = []
        error_line_idx = -1

        for i, line in enumerate(lines):
            stripped = line.lstrip()
            indent_level = len(line) - len(stripped)

            if stripped.startswith(">> "):
                while current_path and current_path[-1][0] >= indent_level:
                    current_path.pop()
                current_path.append((indent_level, line))

            elif stripped.startswith("<< "):
                if current_path and current_path[-1][0] >= indent_level:
                    current_path.pop()

            elif stripped.startswith("!! "):
                error_line_idx = i
                error_path = list(current_path)
                break

        # Pass 2: chunk the text
        current_chunk_lines: list[str] = []
        current_size = 0
        header_lines: list[str] = []

        # Preserve the DUMP header line
        if lines and lines[0].startswith("==="):
            header_lines.append(lines[0])

        for i, line in enumerate(lines):
            line_size = len(line) + 1
            stripped = line.lstrip()
            indent = len(line) - len(stripped)

            # Good break point: top-level >> call (indent <= 2)
            is_good_break_point = stripped.startswith(">> ") and indent <= 2

            if (
                current_size + line_size > self.max_chunk_size
                and is_good_break_point
                and current_chunk_lines
            ):
                chunks.append("\n".join(current_chunk_lines))
                current_chunk_lines = list(header_lines)
                current_size = sum(len(h) + 1 for h in header_lines)

                # Inject parent call stack if error is upcoming in the next chunk
                if error_line_idx != -1 and i <= error_line_idx:
                    for _ind, p_line in error_path:
                        if p_line not in current_chunk_lines:
                            current_chunk_lines.append(
                                p_line + "  # [TraceTree] Context Injected"
                            )
                            current_size += len(p_line) + 33

            current_chunk_lines.append(line)
            current_size += line_size

        if current_chunk_lines:
            chunks.append("\n".join(current_chunk_lines))

        return chunks

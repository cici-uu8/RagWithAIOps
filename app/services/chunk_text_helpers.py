"""Shared helpers for building heading-enriched search text.

The output of `build_search_text` is used as input to dense embedding, BM25
sparse scoring and lexical rerank. It is a retrieval-time concept and must
NOT be written back into ChunkRecord.content or any user-facing display
field — citation / answer context must always carry the original chunk
content.
"""

from __future__ import annotations

from typing import Any, Iterable


def build_search_text(heading_path: Any, content: str) -> str:
    """Concatenate heading path with chunk content for retrieval scoring.

    Args:
        heading_path: ordered breadcrumb of headings the chunk belongs to.
            Accepts ``None``, a bare string, or any iterable of segments.
            Non-string segments are coerced via ``str()``; empty segments
            are dropped.
        content: chunk content used as both display text and base of the
            search text.

    Returns:
        ``"{heading_a} {heading_b}\\n{content}"`` when there is at least one
        non-empty heading, otherwise the unchanged ``content``.
    """
    segments = _normalize_heading_path(heading_path)
    if not segments:
        return content
    headings = " ".join(segments)
    return f"{headings}\n{content}"


def _normalize_heading_path(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable):
        return [str(part) for part in value if part]
    coerced = str(value)
    return [coerced] if coerced else []


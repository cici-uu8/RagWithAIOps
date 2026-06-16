"""ChunkPolicy 原子类型 hard cap 单测.

约定 (与 docs/chunk_policy_atomic_hardcap_design.md §2 / §3 一致):
- 新增常量 ATOMIC_HARD_CAP_DEFAULT_BYTES = 6000, ATOMIC_SPLIT_QUALITY_FLAG = "atomic_split_by_size".
- _atomic_hardcap_pass 在 _resplit_pass 之后, _finalize 之前.
- atomic_hard_cap_bytes 单位是 UTF-8 字节, 与 Milvus content varchar(8000) schema 同单位
  (避免中文 UTF-8 多字节膨胀撞穿 schema 上限的根因).
- 切分 codepoint-safe (不在 UTF-8 多字节序列中间断开), 优先 line 边界 greedy pack,
  单行超 cap 时按 codepoint-aware 字节硬切兜底.
- content_type 保留, heading / pages / 其他 metadata 继承,
  quality_flags 加入 atomic_split_by_size 后取并集排序.
- 切片在 _finalize 时 boundary_changed=True, 获得 :cp{index:05d} 新 id.
- 本测试用 chunk_max_size=50 (chars), atomic_hard_cap_bytes=200 (bytes) 让两条路径都好观察.
"""

import unittest
from typing import Any, List, Optional

from app.models import ChunkRecord, ParserEngine, SourceRef
from app.services.chunk_policy_service import (
    ATOMIC_HARD_CAP_DEFAULT_BYTES,
    ATOMIC_SPLIT_QUALITY_FLAG,
    ChunkPolicyService,
)


def _build_chunk(
    *,
    doc_id: str = "doc_a",
    kb_id: str = "default",
    chunk_id: Optional[str] = None,
    content: str = "正文",
    chunk_index: int = 0,
    heading_path: Optional[List[str]] = None,
    content_type: str = "text",
    page_start: Optional[int] = None,
    page_end: Optional[int] = None,
    quality_flags: Optional[List[str]] = None,
    extra_metadata: Optional[dict[str, Any]] = None,
    source_file: str = "manual.pdf",
    parser_engine: ParserEngine = ParserEngine.MINERU,
) -> ChunkRecord:
    heading_path = heading_path or []
    quality_flags = quality_flags or []
    chunk_id = chunk_id or f"{doc_id}:c{chunk_index:05d}"
    source_ref = SourceRef(
        kb_id=kb_id,
        doc_id=doc_id,
        chunk_id=chunk_id,
        source_file=source_file,
        page_start=page_start,
        page_end=page_end,
        heading_path=heading_path,
        content_type=content_type,
        parser_engine=parser_engine,
    )
    metadata = {
        "kb_id": kb_id,
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "content_type": content_type,
        "heading_path": heading_path,
        "page_start": page_start,
        "page_end": page_end,
        "quality_flags": quality_flags,
        "source_ref": source_ref.model_dump(mode="json"),
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ChunkRecord(
        chunk_id=chunk_id,
        doc_id=doc_id,
        kb_id=kb_id,
        content=content,
        chunk_index=chunk_index,
        start_index=0,
        end_index=len(content),
        heading_path=heading_path,
        page_start=page_start,
        page_end=page_end,
        content_type=content_type,
        source_ref=source_ref,
        quality_flags=quality_flags,
        metadata=metadata,
    )


class ChunkPolicyAtomicHardcapTests(unittest.TestCase):
    """13 cases per docs/chunk_policy_atomic_hardcap_design.md §3."""

    def setUp(self) -> None:
        self.policy = ChunkPolicyService(chunk_max_size=50, atomic_hard_cap_bytes=200)

    def test_default_constant_is_6000_bytes(self):
        # Sanity: default constant matches design §2.1.
        self.assertEqual(ATOMIC_HARD_CAP_DEFAULT_BYTES, 6000)
        default_policy = ChunkPolicyService()
        self.assertEqual(default_policy.atomic_hard_cap_bytes, ATOMIC_HARD_CAP_DEFAULT_BYTES)

    def test_atomic_under_hardcap_passes_through(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 100,  # 100 bytes (ASCII)
            content_type="manual_table",
            heading_path=["S"],
        )
        out = self.policy.apply([chunk])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].chunk_id, "doc_a:t00001")
        self.assertEqual(out[0].content, "A" * 100)
        self.assertEqual(out[0].content_type, "manual_table")
        self.assertNotIn(ATOMIC_SPLIT_QUALITY_FLAG, out[0].quality_flags)

    def test_atomic_at_hardcap_passes_through(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 200,  # exactly 200 bytes (ASCII)
            content_type="manual_table",
        )
        out = self.policy.apply([chunk])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].chunk_id, "doc_a:t00001")
        self.assertEqual(len(out[0].content.encode("utf-8")), 200)
        self.assertNotIn(ATOMIC_SPLIT_QUALITY_FLAG, out[0].quality_flags)

    def test_atomic_over_hardcap_splits_into_pieces_of_at_most_hardcap_bytes(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 500,  # 500 bytes (ASCII), no newlines
            content_type="manual_table",
            heading_path=["S"],
            page_start=10,
            page_end=12,
        )
        out = self.policy.apply([chunk])
        self.assertEqual(len(out), 3)
        for piece in out:
            self.assertLessEqual(len(piece.content.encode("utf-8")), 200)
        # No data loss
        self.assertEqual("".join(p.content for p in out), "A" * 500)

    def test_atomic_split_preserves_content_type(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 500,
            content_type="manual_table",
        )
        out = self.policy.apply([chunk])
        for piece in out:
            self.assertEqual(piece.content_type, "manual_table")
            self.assertEqual(piece.metadata["content_type"], "manual_table")
            self.assertEqual(piece.source_ref.content_type, "manual_table")

    def test_atomic_split_marks_quality_flag(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 500,
            content_type="manual_table",
            quality_flags=["existing_flag"],
        )
        out = self.policy.apply([chunk])
        for piece in out:
            self.assertIn(ATOMIC_SPLIT_QUALITY_FLAG, piece.quality_flags)
            self.assertIn("existing_flag", piece.quality_flags)
            self.assertEqual(piece.quality_flags, sorted(set(piece.quality_flags)))
            self.assertEqual(piece.metadata["quality_flags"], piece.quality_flags)

    def test_atomic_split_assigns_sequential_cp_chunk_ids(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 500,
            content_type="manual_table",
        )
        out = self.policy.apply([chunk])
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0].chunk_id, "doc_a:cp00000")
        self.assertEqual(out[1].chunk_id, "doc_a:cp00001")
        self.assertEqual(out[2].chunk_id, "doc_a:cp00002")
        self.assertEqual([p.chunk_index for p in out], [0, 1, 2])
        for piece in out:
            self.assertEqual(piece.source_ref.chunk_id, piece.chunk_id)
            self.assertEqual(piece.metadata["chunk_id"], piece.chunk_id)
            self.assertEqual(piece.metadata["source_ref"]["chunk_id"], piece.chunk_id)

    def test_atomic_split_preserves_heading_and_pages(self):
        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 500,
            content_type="manual_table",
            heading_path=["第一章", "1.1 网络"],
            page_start=10,
            page_end=12,
        )
        out = self.policy.apply([chunk])
        for piece in out:
            self.assertEqual(list(piece.heading_path), ["第一章", "1.1 网络"])
            self.assertEqual(piece.page_start, 10)
            self.assertEqual(piece.page_end, 12)
            self.assertEqual(piece.metadata["heading_path"], ["第一章", "1.1 网络"])

    def test_text_oversized_uses_resplit_not_hardcap(self):
        chunk = _build_chunk(
            chunk_id="doc_a:c00001",
            content="句子。" * 1000,
            content_type="text",
        )
        out = self.policy.apply([chunk])
        self.assertGreater(len(out), 1)
        for piece in out:
            # _resplit_pass uses char-based chunk_max_size=50, runs first.
            self.assertLessEqual(len(piece.content), 50)
            # _atomic_hardcap_pass runs after; resplit pieces ≤ 50 chars × 3 bytes/char
            # = ≤ 150 bytes ≤ 200 bytes cap, so no further split.
            self.assertLessEqual(len(piece.content.encode("utf-8")), 200)
            self.assertNotIn(ATOMIC_SPLIT_QUALITY_FLAG, piece.quality_flags)

    def test_short_text_unchanged_no_atomic_flag(self):
        chunk = _build_chunk(
            chunk_id="doc_a:c00001",
            content="短文本。",
            content_type="text",
        )
        out = self.policy.apply([chunk])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].chunk_id, "doc_a:c00001")
        self.assertNotIn(ATOMIC_SPLIT_QUALITY_FLAG, out[0].quality_flags)

    def test_section_parents_unaffected_by_atomic_hardcap(self):
        # text1 + text2 each 30 chars × 3 bytes = 90 bytes; combined 62 chars > chunk_max_size 50
        # so _merge_pass doesn't fold them into 1; need ≥ 2 same-heading text chunks for parent.
        text1 = _build_chunk(
            chunk_id="doc_a:c00001",
            content="正" * 30,
            content_type="text",
            heading_path=["S"],
            chunk_index=0,
        )
        text2 = _build_chunk(
            chunk_id="doc_a:c00002",
            content="文" * 30,
            content_type="text",
            heading_path=["S"],
            chunk_index=1,
        )
        atomic_big = _build_chunk(
            chunk_id="doc_a:t00001",
            content="A" * 500,
            content_type="manual_table",
            heading_path=["S"],
            chunk_index=2,
        )
        result = self.policy.apply_with_parents([text1, text2, atomic_big])

        self.assertEqual(len(result.parents), 1)
        parent = result.parents[0]
        atomic_split_chunks = [c for c in result.chunks if c.content_type == "manual_table"]
        self.assertEqual(len(atomic_split_chunks), 3)

        child_ids = parent.metadata["child_chunk_ids"]
        for piece in atomic_split_chunks:
            self.assertNotIn(piece.chunk_id, child_ids)
            self.assertIsNone(piece.parent_chunk_id)

    def test_atomic_chinese_locks_byte_unit_not_char_unit(self):
        """Chinese-content boundary case: 100 chars but 300 bytes must split under
        a 200-byte cap. Locks the design §2.1 unit choice (bytes, not chars) and
        codepoint-safe split (no UTF-8 corruption)."""
        chinese_content = "中" * 100  # 100 chars, 300 bytes (3 bytes/char)
        self.assertEqual(len(chinese_content), 100)
        self.assertEqual(len(chinese_content.encode("utf-8")), 300)

        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content=chinese_content,
            content_type="manual_table",
        )
        out = self.policy.apply([chunk])

        # MUST split (would NOT have under old char-based cap=200 since 100 chars ≤ 200)
        self.assertGreater(len(out), 1)
        # Each piece ≤ 200 bytes
        for piece in out:
            self.assertLessEqual(len(piece.content.encode("utf-8")), 200)
        # No data loss + codepoint-safe (full string round-trips, every piece is valid UTF-8)
        self.assertEqual("".join(p.content for p in out), chinese_content)
        for piece in out:
            # Round-trip must succeed; raises UnicodeDecodeError if a multibyte
            # sequence was split mid-codepoint.
            piece.content.encode("utf-8").decode("utf-8")
        # Every piece carries the split flag
        for piece in out:
            self.assertIn(ATOMIC_SPLIT_QUALITY_FLAG, piece.quality_flags)

    def test_atomic_split_prefers_line_boundaries(self):
        """Multi-line atomic content prefers line-boundary packing; rows stay
        intact when possible (table / equation row preservation)."""
        # 5 lines of "A" * 60 + "\n" = 61 bytes each, total 305 bytes.
        # Greedy pack with cap=200: lines 1-3 = 183 bytes (next line would push to
        # 244 > 200), flush. lines 4-5 = 122 bytes.
        line = "A" * 60 + "\n"
        content = line * 5
        self.assertEqual(len(content.encode("utf-8")), 305)

        chunk = _build_chunk(
            chunk_id="doc_a:t00001",
            content=content,
            content_type="manual_table",
        )
        out = self.policy.apply([chunk])

        self.assertEqual(len(out), 2)
        # Each piece composed of whole lines (no mid-line break)
        self.assertEqual(out[0].content, line * 3)
        self.assertEqual(out[1].content, line * 2)
        for piece in out:
            self.assertLessEqual(len(piece.content.encode("utf-8")), 200)


if __name__ == "__main__":
    unittest.main()

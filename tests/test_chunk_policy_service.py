"""P2: ChunkPolicyService 单元测试。

约定:
- TEXT_TYPES = {"text", "markdown_section"}
- 其他 content_type 视为 atomic，不参与合并 / 再拆。
- 边界未变化的 chunk 保留原 chunk_id（pass-through）。
- 边界变化（合并或再拆）后，chunk_id 重新生成为 `{doc_id}:c{new_index:05d}`，
  source_ref.chunk_id / metadata.chunk_id / metadata.source_ref.chunk_id 同步刷新。
- chunk_index 始终重新编号为 0..N-1。
"""

import unittest
from typing import Any, List, Optional

from app.models import ChunkRecord, ParserEngine, SourceRef
from app.services.chunk_policy_service import ChunkPolicyService


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
    source_file: str = "manual.md",
    parser_engine: ParserEngine = ParserEngine.PLAIN_TEXT,
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


class ChunkPolicyServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # chunk_max_size=100 让超长再拆和合并阈值都好观察
        self.policy = ChunkPolicyService(chunk_max_size=100)

    def test_passes_through_when_no_change_needed(self):
        chunk = _build_chunk(content="短小段落。", heading_path=["A", "A1"])
        out = self.policy.apply([chunk])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].chunk_id, chunk.chunk_id)
        self.assertEqual(out[0].content, chunk.content)
        self.assertEqual(out[0].chunk_index, 0)
        self.assertEqual(out[0].metadata["chunk_id"], chunk.chunk_id)
        self.assertEqual(out[0].source_ref.chunk_id, chunk.chunk_id)

    def test_merges_short_siblings_under_same_heading(self):
        a = _build_chunk(
            chunk_index=0, content="段落甲。", heading_path=["A", "A1"], page_start=1, page_end=1
        )
        b = _build_chunk(
            chunk_index=1, content="段落乙。", heading_path=["A", "A1"], page_start=1, page_end=2
        )
        out = self.policy.apply([a, b])
        self.assertEqual(len(out), 1)
        merged = out[0]
        self.assertIn("段落甲。", merged.content)
        self.assertIn("段落乙。", merged.content)
        self.assertEqual(merged.heading_path, ["A", "A1"])
        self.assertEqual(merged.page_start, 1)
        self.assertEqual(merged.page_end, 2)
        # 合并后 chunk_id 必须重生且与 source_ref / metadata 同步
        self.assertNotEqual(merged.chunk_id, a.chunk_id)
        self.assertNotEqual(merged.chunk_id, b.chunk_id)
        self.assertTrue(merged.chunk_id.startswith("doc_a:c"))
        self.assertEqual(merged.source_ref.chunk_id, merged.chunk_id)
        self.assertEqual(merged.metadata["chunk_id"], merged.chunk_id)
        self.assertEqual(merged.metadata["source_ref"]["chunk_id"], merged.chunk_id)

    def test_does_not_merge_across_heading_path(self):
        a = _build_chunk(chunk_index=0, content="A 节短段。", heading_path=["A", "A1"])
        b = _build_chunk(chunk_index=1, content="B 节短段。", heading_path=["A", "A2"])
        out = self.policy.apply([a, b])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].chunk_id, a.chunk_id)
        self.assertEqual(out[1].chunk_id, b.chunk_id)
        self.assertEqual(out[0].chunk_index, 0)
        self.assertEqual(out[1].chunk_index, 1)

    def test_does_not_merge_atomic_with_text(self):
        text = _build_chunk(chunk_index=0, content="正文段。", heading_path=["A", "A1"])
        table = _build_chunk(
            chunk_index=1,
            chunk_id="doc_a:table:t00001",
            content="| 名称 | 值 |",
            heading_path=["A", "A1"],
            content_type="manual_table",
        )
        out = self.policy.apply([text, table])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].chunk_id, text.chunk_id)
        self.assertEqual(out[1].chunk_id, "doc_a:table:t00001")
        self.assertEqual(out[1].content_type, "manual_table")

    def test_atomic_equation_keeps_original_id(self):
        eq = _build_chunk(
            chunk_index=0,
            chunk_id="doc_a:eq:0001",
            content="$E=mc^2$",
            heading_path=["A"],
            content_type="equation_interline",
        )
        out = self.policy.apply([eq])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].chunk_id, "doc_a:eq:0001")
        self.assertEqual(out[0].content_type, "equation_interline")

    def test_resplits_oversized_text_chunk_at_sentence_boundary(self):
        # 30 句，每句 7 cp，总 210 cp > chunk_max_size * 2 = 200
        sentences = ["这是第一句话。", "这是第二句话！", "这是第三句话？"] * 10
        big = "".join(sentences)
        self.assertGreater(len(big), self.policy.chunk_max_size * 2)
        chunk = _build_chunk(content=big, heading_path=["A", "A1"])
        out = self.policy.apply([chunk])
        self.assertGreater(len(out), 1)
        # 每片都不超过阈值上限（容许等于 chunk_max_size，最多+一个句号边界）
        for piece in out:
            self.assertLessEqual(len(piece.content), self.policy.chunk_max_size)
        # 每片都以句号/问号/感叹号收尾，证明按句界拆
        for piece in out[:-1]:
            self.assertTrue(
                piece.content.rstrip().endswith(("。", "！", "？")),
                f"片段未在句界处拆分: {piece.content!r}",
            )
        # 拼回去内容总和 = 原文（句号边界不丢字）
        self.assertEqual("".join(p.content for p in out), big)
        # 边界变化 → chunk_id 全部重生
        for idx, piece in enumerate(out):
            self.assertNotEqual(piece.chunk_id, chunk.chunk_id)
            self.assertEqual(piece.chunk_index, idx)
            self.assertEqual(piece.source_ref.chunk_id, piece.chunk_id)
            self.assertEqual(piece.metadata["chunk_id"], piece.chunk_id)

    def test_resplit_falls_back_to_hard_cut_when_no_sentence_boundary(self):
        # 单句无句末标点，只能按长度兜底
        big = "x" * 250
        chunk = _build_chunk(content=big, heading_path=["A"])
        out = self.policy.apply([chunk])
        self.assertGreaterEqual(len(out), 3)
        for piece in out:
            self.assertLessEqual(len(piece.content), self.policy.chunk_max_size)
        self.assertEqual("".join(p.content for p in out), big)

    def test_chunk_index_is_sequential(self):
        chunks = [
            _build_chunk(chunk_index=0, content="A 节段。", heading_path=["A"]),
            _build_chunk(chunk_index=1, content="B 节段。", heading_path=["B"]),
            _build_chunk(
                chunk_index=2,
                chunk_id="doc_a:table:t1",
                content="| x |",
                content_type="manual_table",
                heading_path=["B"],
            ),
        ]
        out = self.policy.apply(chunks)
        for idx, piece in enumerate(out):
            self.assertEqual(piece.chunk_index, idx)

    def test_preserves_quality_flags_union_on_merge(self):
        a = _build_chunk(chunk_index=0, content="段甲。", heading_path=["A"], quality_flags=["short"])
        b = _build_chunk(
            chunk_index=1, content="段乙。", heading_path=["A"], quality_flags=["short", "ocr_low"]
        )
        out = self.policy.apply([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(out[0].quality_flags), ["ocr_low", "short"])

    def test_does_not_merge_when_combined_exceeds_max(self):
        # 两段相加超过 chunk_max_size，不合并
        a = _build_chunk(chunk_index=0, content="x" * 70, heading_path=["A"])
        b = _build_chunk(chunk_index=1, content="y" * 70, heading_path=["A"])
        out = self.policy.apply([a, b])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0].chunk_id, a.chunk_id)
        self.assertEqual(out[1].chunk_id, b.chunk_id)

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.policy.apply([]), [])

    def test_metadata_block_specific_fields_preserved_on_passthrough(self):
        chunk = _build_chunk(
            content="表内容",
            content_type="manual_table",
            chunk_id="doc_a:table:t00001",
            heading_path=["A"],
            extra_metadata={
                "structured_payload": {"rows": [["a", "b"]]},
                "table_id": "t00001",
            },
        )
        out = self.policy.apply([chunk])
        self.assertEqual(out[0].metadata["structured_payload"], {"rows": [["a", "b"]]})
        self.assertEqual(out[0].metadata["table_id"], "t00001")


class ChunkPolicyParentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = ChunkPolicyService(chunk_max_size=100)

    def test_no_parent_for_single_child_in_section(self):
        chunk = _build_chunk(content="独段。", heading_path=["A", "A1"])
        result = self.policy.apply_with_parents([chunk])
        self.assertEqual(len(result.chunks), 1)
        self.assertEqual(result.parents, [])
        self.assertIsNone(result.chunks[0].parent_chunk_id)

    def test_section_parent_groups_consecutive_text_children(self):
        a = _build_chunk(chunk_index=0, content="x" * 70, heading_path=["A", "A1"])
        b = _build_chunk(chunk_index=1, content="y" * 70, heading_path=["A", "A1"])
        result = self.policy.apply_with_parents([a, b])
        self.assertEqual(len(result.chunks), 2)
        self.assertEqual(len(result.parents), 1)
        parent = result.parents[0]
        self.assertEqual(parent.heading_path, ["A", "A1"])
        self.assertIn("x" * 70, parent.content)
        self.assertIn("y" * 70, parent.content)
        self.assertTrue(parent.chunk_id.startswith("doc_a:parent:"))
        self.assertEqual(parent.metadata.get("chunk_role"), "parent")
        self.assertEqual(parent.content_type, "section_parent")
        self.assertIsNone(parent.parent_chunk_id)
        for child in result.chunks:
            self.assertEqual(child.parent_chunk_id, parent.chunk_id)
            self.assertEqual(child.metadata["parent_chunk_id"], parent.chunk_id)

    def test_table_excluded_from_text_section_parent(self):
        t1 = _build_chunk(chunk_index=0, content="x" * 70, heading_path=["A", "A1"])
        t2 = _build_chunk(chunk_index=1, content="y" * 70, heading_path=["A", "A1"])
        tab = _build_chunk(
            chunk_index=2,
            chunk_id="doc_a:table:t1",
            content="| a |",
            heading_path=["A", "A1"],
            content_type="manual_table",
        )
        result = self.policy.apply_with_parents([t1, t2, tab])
        self.assertEqual(len(result.chunks), 3)
        self.assertEqual(len(result.parents), 1)
        parent = result.parents[0]
        self.assertNotIn("| a |", parent.content)
        text_chunks = [c for c in result.chunks if c.content_type == "text"]
        table_chunks = [c for c in result.chunks if c.content_type == "manual_table"]
        for c in text_chunks:
            self.assertEqual(c.parent_chunk_id, parent.chunk_id)
        for c in table_chunks:
            self.assertIsNone(c.parent_chunk_id)

    def test_resplit_pieces_share_one_parent(self):
        sentences = ["这是第一句话。", "这是第二句话！", "这是第三句话？"] * 10
        big = "".join(sentences)
        chunk = _build_chunk(content=big, heading_path=["A", "A1"])
        result = self.policy.apply_with_parents([chunk])
        self.assertGreater(len(result.chunks), 1)
        self.assertEqual(len(result.parents), 1)
        parent = result.parents[0]
        for c in result.chunks:
            self.assertEqual(c.parent_chunk_id, parent.chunk_id)
            self.assertIn(c.content, parent.content)

    def test_parent_aggregates_pages_and_quality_flags(self):
        a = _build_chunk(
            chunk_index=0,
            content="x" * 70,
            heading_path=["A"],
            page_start=1,
            page_end=2,
            quality_flags=["short"],
        )
        b = _build_chunk(
            chunk_index=1,
            content="y" * 70,
            heading_path=["A"],
            page_start=3,
            page_end=4,
            quality_flags=["short", "ocr_low"],
        )
        result = self.policy.apply_with_parents([a, b])
        parent = result.parents[0]
        self.assertEqual(parent.page_start, 1)
        self.assertEqual(parent.page_end, 4)
        self.assertEqual(sorted(parent.quality_flags), ["ocr_low", "short"])

    def test_parents_are_separate_for_different_heading_paths(self):
        a1 = _build_chunk(chunk_index=0, content="x" * 70, heading_path=["A", "A1"])
        a2 = _build_chunk(chunk_index=1, content="y" * 70, heading_path=["A", "A1"])
        b1 = _build_chunk(chunk_index=2, content="x" * 70, heading_path=["B", "B1"])
        b2 = _build_chunk(chunk_index=3, content="y" * 70, heading_path=["B", "B1"])
        result = self.policy.apply_with_parents([a1, a2, b1, b2])
        self.assertEqual(len(result.parents), 2)
        parent_ids = {p.chunk_id for p in result.parents}
        self.assertEqual(len(parent_ids), 2)
        heading_to_parent = {tuple(p.heading_path): p.chunk_id for p in result.parents}
        self.assertIn(("A", "A1"), heading_to_parent)
        self.assertIn(("B", "B1"), heading_to_parent)

    def test_no_parent_when_heading_path_is_empty(self):
        a = _build_chunk(chunk_index=0, content="x" * 70, heading_path=[])
        b = _build_chunk(chunk_index=1, content="y" * 70, heading_path=[])
        result = self.policy.apply_with_parents([a, b])
        self.assertEqual(result.parents, [])
        for c in result.chunks:
            self.assertIsNone(c.parent_chunk_id)

    def test_legacy_apply_skips_parent_generation(self):
        a = _build_chunk(chunk_index=0, content="x" * 70, heading_path=["A"])
        b = _build_chunk(chunk_index=1, content="y" * 70, heading_path=["A"])
        chunks = self.policy.apply([a, b])
        self.assertEqual(len(chunks), 2)
        for c in chunks:
            self.assertIsNone(c.parent_chunk_id)
            self.assertNotIn("parent_chunk_id", c.metadata)


if __name__ == "__main__":
    unittest.main()

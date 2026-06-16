"""P1: DocumentSplitterService._merge_small_chunks 标题边界回归测试。"""

import unittest

from langchain_core.documents import Document

from app.services.document_splitter_service import DocumentSplitterService


class MergeSmallChunksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = DocumentSplitterService()

    def _make(self, content: str, h1: str = "", h2: str = "", h3: str = "") -> Document:
        metadata = {}
        if h1:
            metadata["h1"] = h1
        if h2:
            metadata["h2"] = h2
        if h3:
            metadata["h3"] = h3
        return Document(page_content=content, metadata=metadata)

    def test_merges_short_siblings_within_same_section(self):
        docs = [
            self._make("短段A。", h1="一级", h2="现象"),
            self._make("短段B。", h1="一级", h2="现象"),
        ]
        merged = self.service._merge_small_chunks(docs, min_size=300)
        self.assertEqual(len(merged), 1)
        self.assertIn("短段A。", merged[0].page_content)
        self.assertIn("短段B。", merged[0].page_content)
        self.assertEqual(merged[0].metadata.get("h2"), "现象")

    def test_does_not_merge_across_h2_boundary(self):
        docs = [
            self._make("现象段落。", h1="CPU 告警", h2="现象"),
            self._make("处理段落。", h1="CPU 告警", h2="处理"),
        ]
        merged = self.service._merge_small_chunks(docs, min_size=300)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].metadata.get("h2"), "现象")
        self.assertEqual(merged[1].metadata.get("h2"), "处理")

    def test_does_not_merge_across_h1_boundary(self):
        docs = [
            self._make("CPU 告警的简介。", h1="CPU 告警"),
            self._make("内存告警的简介。", h1="内存告警"),
        ]
        merged = self.service._merge_small_chunks(docs, min_size=300)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].metadata.get("h1"), "CPU 告警")
        self.assertEqual(merged[1].metadata.get("h1"), "内存告警")

    def test_does_not_merge_when_next_chunk_is_large(self):
        big = "X" * 500
        docs = [
            self._make("短段。", h1="A", h2="A1"),
            self._make(big, h1="A", h2="A1"),
        ]
        merged = self.service._merge_small_chunks(docs, min_size=300)
        self.assertEqual(len(merged), 2)

    def test_respects_secondary_size_cap(self):
        large_first = "Y" * (self.service.chunk_size * 2)
        docs = [
            self._make(large_first, h1="A", h2="A1"),
            self._make("短段。", h1="A", h2="A1"),
        ]
        merged = self.service._merge_small_chunks(docs, min_size=300)
        self.assertEqual(len(merged), 2)

    def test_empty_input_returns_empty(self):
        self.assertEqual(self.service._merge_small_chunks([], min_size=300), [])


if __name__ == "__main__":
    unittest.main()

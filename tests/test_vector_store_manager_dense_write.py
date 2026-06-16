"""P3: vector_store_manager.add_documents dense 写入路径单测。

锁定:
- Milvus content 字段写入的是 chunk 原文（不含 heading 前缀）。
- 喂给 embedding 模型的是 heading_path + content 的拼接文本。
- metadata 原样透传，ids 与 documents 数量一致。
"""

import unittest
from unittest.mock import MagicMock

from langchain_core.documents import Document

import app.services.vector_store_manager as vsm_module


class FakeVectorStore:
    def __init__(self):
        self.calls: list[dict] = []

    def add_embeddings(self, *, texts, embeddings, metadatas, ids, **kwargs):
        self.calls.append(
            {
                "texts": list(texts),
                "embeddings": list(embeddings),
                "metadatas": [dict(m) for m in metadatas],
                "ids": list(ids),
                "kwargs": kwargs,
            }
        )
        return list(ids)


class AddDocumentsDenseWriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_store = FakeVectorStore()
        self.manager = vsm_module.VectorStoreManager()
        self.manager.vector_store = self.fake_store

        self.embed_mock = MagicMock()
        self.embed_mock.embed_documents.side_effect = lambda texts: [
            [float(idx)] for idx, _ in enumerate(texts)
        ]
        self._original_embed = vsm_module.vector_embedding_service
        vsm_module.vector_embedding_service = self.embed_mock

    def tearDown(self) -> None:
        vsm_module.vector_embedding_service = self._original_embed

    def test_dense_write_uses_heading_enriched_text_for_embedding(self):
        documents = [
            Document(
                page_content="第一段正文",
                metadata={"heading_path": ["第一章", "概述"], "chunk_id": "c1"},
            ),
            Document(
                page_content="第二段正文",
                metadata={"heading_path": [], "chunk_id": "c2"},
            ),
        ]

        result_ids = self.manager.add_documents(documents)

        self.embed_mock.embed_documents.assert_called_once()
        embed_args = self.embed_mock.embed_documents.call_args.args[0]
        self.assertEqual(embed_args, ["第一章 概述\n第一段正文", "第二段正文"])

        self.assertEqual(len(self.fake_store.calls), 1)
        call = self.fake_store.calls[0]
        # display 文本保持原文，无 heading 前缀污染
        self.assertEqual(call["texts"], ["第一段正文", "第二段正文"])
        # 向量与文档 1:1 对齐
        self.assertEqual(call["embeddings"], [[0.0], [1.0]])
        # metadata 原样透传
        self.assertEqual(call["metadatas"][0]["chunk_id"], "c1")
        self.assertEqual(call["metadatas"][0]["heading_path"], ["第一章", "概述"])
        self.assertEqual(call["metadatas"][1]["chunk_id"], "c2")
        # 返回 id 列表与生成 id 一致
        self.assertEqual(result_ids, call["ids"])
        self.assertEqual(len(result_ids), len(documents))

    def test_empty_documents_short_circuits(self):
        result = self.manager.add_documents([])
        self.assertEqual(result, [])
        self.embed_mock.embed_documents.assert_not_called()
        self.assertEqual(self.fake_store.calls, [])


if __name__ == "__main__":
    unittest.main()

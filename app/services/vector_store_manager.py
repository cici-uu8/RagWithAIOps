"""向量存储管理器 - 封装 Milvus VectorStore 操作"""

from dataclasses import dataclass
import json
from typing import Any, List

from langchain_core.documents import Document
from langchain_milvus import Milvus
from loguru import logger

from app.config import config
from app.core.milvus_client import milvus_manager
from app.services.chunk_text_helpers import build_search_text
from app.services.vector_embedding_service import vector_embedding_service


# 统一使用 biz collection
COLLECTION_NAME = "biz"


@dataclass(frozen=True)
class PreparedVectorDocuments:
    """Vector rows with embeddings already computed before destructive cleanup."""

    ids: List[str]
    display_texts: List[str]
    embeddings: List[List[float]]
    metadatas: List[dict[str, Any]]

    @property
    def document_count(self) -> int:
        return len(self.ids)


class VectorStoreManager:
    """向量存储管理器"""

    def __init__(self):
        """初始化向量存储管理器"""
        self.vector_store = None
        self.collection_name = COLLECTION_NAME

    def _ensure_vector_store(self) -> Milvus:
        if self.vector_store is None:
            self._initialize_vector_store()
        if self.vector_store is None:
            raise RuntimeError("VectorStore 初始化失败")
        return self.vector_store

    def _initialize_vector_store(self):
        """初始化 Milvus VectorStore"""
        if self.vector_store is not None:
            return
        try:
            # 必须在 PyMilvus / langchain_milvus 访问 Collection 之前建立连接，
            # 否则会出现 ConnectionNotExistException: should create connection first.
            # （模块导入时就会执行此处，早于 FastAPI lifespan 中的 milvus_manager.connect）
            _ = milvus_manager.connect()

            if config.milvus_uri:
                connection_args = {"uri": config.milvus_uri}
            else:
                connection_args = {
                    "host": config.milvus_host,
                    "port": config.milvus_port,
                }

            # 创建 LangChain Milvus VectorStore
            # 使用 biz collection，字段映射：text_field -> content, vector_field -> vector
            self.vector_store = Milvus(
                embedding_function=vector_embedding_service,
                collection_name=self.collection_name,
                connection_args=connection_args,
                auto_id=False,  # 使用自定义 id
                drop_old=False,
                text_field="content",  # 文本内容存储到 content 字段
                vector_field="vector",  # 向量存储到 vector 字段
                primary_field="id",  # 主键字段
                metadata_field="metadata",  # 元数据字段
            )

            logger.info(
                f"VectorStore 初始化成功: {config.milvus_host}:{config.milvus_port}, "
                f"collection: {self.collection_name}"
            )

        except Exception as e:
            logger.error(f"VectorStore 初始化失败: {e}")
            raise

    def prepare_documents(self, documents: List[Document]) -> PreparedVectorDocuments:
        """Prepare embeddings before callers delete the previous vector rows."""
        if not documents:
            return PreparedVectorDocuments(ids=[], display_texts=[], embeddings=[], metadatas=[])

        import uuid

        ids = [str(uuid.uuid4()) for _ in documents]
        display_texts = [doc.page_content for doc in documents]
        search_texts = [
            build_search_text(doc.metadata.get("heading_path") or [], doc.page_content)
            for doc in documents
        ]
        metadatas = [doc.metadata for doc in documents]
        embeddings = vector_embedding_service.embed_documents(search_texts)
        return PreparedVectorDocuments(
            ids=ids,
            display_texts=display_texts,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def add_prepared_documents(self, prepared: PreparedVectorDocuments) -> List[str]:
        """Write pre-embedded vector rows to Milvus."""
        if prepared.document_count == 0:
            return []

        vector_store = self._ensure_vector_store()
        return vector_store.add_embeddings(
            texts=prepared.display_texts,
            embeddings=prepared.embeddings,
            metadatas=prepared.metadatas,
            ids=prepared.ids,
        )

    def add_documents(self, documents: List[Document]) -> List[str]:
        """
        批量添加文档到向量存储。

        Display 文本（写入 Milvus content 字段）保持 chunk 原文不变，确保
        retrieval / citation 拿到的是原始正文；用于计算 dense embedding 的
        文本由 build_search_text 拼出 heading_path + content，让标题路径
        参与向量召回，与 sparse / rerank 口径一致。
        """
        if not documents:
            return []

        try:
            import time
            start_time = time.time()

            prepared = self.prepare_documents(documents)
            result_ids = self.add_prepared_documents(prepared)

            elapsed = time.time() - start_time
            logger.info(
                f"批量添加 {len(documents)} 个文档到 VectorStore 完成, "
                f"耗时: {elapsed:.2f}秒, 平均: {elapsed/len(documents):.2f}秒/个"
            )
            return result_ids
        except Exception as e:
            logger.error(f"添加文档失败: {e}")
            raise

    def _delete_by_metadata_field(self, field_name: str, value: str, label: str) -> int:
        try:
            _ = milvus_manager.connect()
            collection = milvus_manager.get_collection()

            expr = f'metadata["{field_name}"] == {json.dumps(value)}'
            result = collection.delete(expr)
            deleted_count = result.delete_count if hasattr(result, "delete_count") else 0

            logger.info(f"删除{label}: {value}, 删除数量: {deleted_count}")
            return deleted_count
        except Exception as e:
            logger.warning(f"删除{label}失败 (可能是首次索引): {e}")
            return 0

    def delete_by_doc_id(self, doc_id: str) -> int:
        """Delete all vector rows for a document id."""
        return self._delete_by_metadata_field("doc_id", doc_id, "文档旧索引")

    def delete_by_source(self, file_path: str) -> int:
        """
        删除指定文件的所有文档

        Args:
            file_path: 文件路径

        Returns:
            int: 删除的文档数量
        """
        return self._delete_by_metadata_field("_source", file_path, "文件旧数据")

    def get_vector_store(self) -> Milvus:
        """
        获取 VectorStore 实例

        Returns:
            Milvus: VectorStore 实例
        """
        return self._ensure_vector_store()

    def similarity_search(self, query: str, k: int = 3) -> List[Document]:
        """
        相似度搜索

        Args:
            query: 查询文本
            k: 返回结果数量

        Returns:
            List[Document]: 相关文档列表
        """
        try:
            vector_store = self._ensure_vector_store()
            docs = vector_store.similarity_search(query, k=k)
            logger.debug(f"相似度搜索完成: query='{query}', 结果数={len(docs)}")
            return docs
        except Exception as e:
            logger.error(f"相似度搜索失败: {e}")
            return []


# 全局单例
vector_store_manager = VectorStoreManager()

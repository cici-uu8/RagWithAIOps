"""向量嵌入服务模块 - 基于 LangChain Embeddings 标准接口"""

import time
from typing import Any, Callable, List

from langchain_core.embeddings import Embeddings
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)
from loguru import logger

from app.config import config
from app.services.token_estimator import chars_for_token_limit, detect_language


# 服务层 batch retry: 把 transient 错误从 eval 脚本边界往下推一层。
# OpenAI SDK 自身的 max_retries 默认 2 次内置在每次 .create() 调用里；
# 这里再叠 1 + 2 次外层尝试，覆盖 SDK 内部 retry 已用尽后的更大时间窗口。
# 详见 docs/vector_embedding_retry_design notes / task #8。
_MAX_RETRY_ATTEMPTS = 3  # 1 initial + 2 retries
_RETRYABLE_EXCEPTIONS = (
    APITimeoutError,
    APIConnectionError,
    InternalServerError,
    RateLimitError,
)


# DashScope text-embedding-v4 的输入上限是 8192 tokens/文本（OpenAI 兼容模式）。
# 超过会返回 400 / "Range of input length should be ..."，整个 batch 失败。
# 这里在客户端做防御性预截断：用 token_estimator 按语言估算字符预算
# (8192 * chars_per_token * 0.9 安全因子)，超出就按 codepoint 边界截断。
# 上游 chunk_policy_service 已经把生产路径切到 6000 bytes，所以这里仅兜底。
EMBEDDER_MAX_TOKENS = 8192


def _truncate_for_embedder(text: str) -> str:
    """按检测语言把 text 预截断到 EMBEDDER_MAX_TOKENS 对应的字符预算内。

    短于预算的文本原样返回；超出的发 WARNING 并按 codepoint 边界截断。
    """
    if not text:
        return text
    lang = detect_language(text)
    char_budget = chars_for_token_limit(EMBEDDER_MAX_TOKENS, lang)
    if len(text) <= char_budget:
        return text
    truncated = text[:char_budget]
    logger.warning(
        f"嵌入输入超过 {EMBEDDER_MAX_TOKENS} tokens 预算 (lang={lang}, "
        f"原长 {len(text)} chars > 截断后 {len(truncated)} chars)，已 truncate。"
    )
    return truncated


def _call_with_retry(fn: Callable[[], Any], *, label: str) -> Any:
    """以 2s/4s 指数退避调用 fn()，仅 transient 错误触发重试。

    Permanent (AuthenticationError / BadRequestError / 等) 不重试，第一次失败就抛，
    交给上层 try/except 包成 RuntimeError。
    """
    last_exc: BaseException | None = None
    for attempt in range(1, _MAX_RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except _RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            if attempt < _MAX_RETRY_ATTEMPTS:
                wait = 2 ** attempt  # 2s, 4s
                logger.warning(
                    f"{label} 第 {attempt}/{_MAX_RETRY_ATTEMPTS} 次尝试 transient 失败 "
                    f"({type(e).__name__}: {e})，{wait}s 后重试"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"{label} 已用尽 {_MAX_RETRY_ATTEMPTS} 次尝试，最终失败: {e}"
                )
    assert last_exc is not None  # unreachable: loop either returns or saves exc
    raise last_exc


class DashScopeEmbeddings(Embeddings):
    """阿里云 DashScope Text Embedding (OpenAI 兼容模式)
    
    实现 LangChain 标准 Embeddings 接口:
    - embed_documents(texts: List[str]) → List[List[float]]: 批量嵌入文档
    - embed_query(text: str) → List[float]: 嵌入单个查询
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-v4",
        dimensions: int = 1024,
    ):
        """
        初始化 DashScope Embeddings
        
        Args:
            api_key: DashScope API Key
            model: 嵌入模型名称
            dimensions: 向量维度
        """
        if not api_key or api_key == "your-api-key-here":
            raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        self.model = model
        self.dimensions = dimensions
        
        # 打印初始化信息
        masked_key = self._mask_api_key(api_key)
        logger.info(
            f"DashScope Embeddings 初始化完成 - "
            f"模型: {model}, 维度: {dimensions}, API Key: {masked_key}"
        )

    @staticmethod
    def _mask_api_key(api_key: str) -> str:
        """掩码 API Key 用于日志"""
        if len(api_key) > 8:
            return f"{api_key[:8]}...{api_key[-4:]}"
        return "***"

    # DashScope text-embedding-v4 单次请求 ≤ 10 条，超出会返回 InvalidParameter。
    _MAX_BATCH_SIZE = 10

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        批量嵌入文档列表 (LangChain 标准接口)

        Args:
            texts: 文本列表

        Returns:
            List[List[float]]: 嵌入向量列表
        """
        if not texts:
            return []

        try:
            logger.info(f"批量嵌入 {len(texts)} 个文档")

            # 每条文本按各自的语言预算独立截断（不同语种 batch 内可混用）。
            texts = [_truncate_for_embedder(t) for t in texts]

            embeddings: List[List[float]] = []
            for start in range(0, len(texts), self._MAX_BATCH_SIZE):
                batch = texts[start : start + self._MAX_BATCH_SIZE]
                response = _call_with_retry(
                    lambda batch=batch: self.client.embeddings.create(
                        model=self.model,
                        input=batch,
                        dimensions=self.dimensions,
                        encoding_format="float",
                    ),
                    label=f"批量嵌入 batch[{start}:{start + len(batch)}]",
                )
                embeddings.extend(item.embedding for item in response.data)

            logger.debug(f"批量嵌入完成, 维度: {len(embeddings[0])}")

            return embeddings

        except Exception as e:
            logger.error(f"批量嵌入失败: {e}")
            raise RuntimeError(f"批量嵌入失败: {e}") from e

    def embed_query(self, text: str) -> List[float]:
        """
        嵌入单个查询文本 (LangChain 标准接口)
        
        Args:
            text: 查询文本
            
        Returns:
            List[float]: 嵌入向量
        """
        if not text or not text.strip():
            raise ValueError("查询文本不能为空")

        try:
            logger.debug(f"嵌入查询, 长度: {len(text)} 字符")

            text = _truncate_for_embedder(text)

            response = _call_with_retry(
                lambda: self.client.embeddings.create(
                    model=self.model,
                    input=text,
                    dimensions=self.dimensions,
                    encoding_format="float",
                ),
                label="查询嵌入",
            )

            embedding = response.data[0].embedding
            logger.debug(f"查询嵌入完成, 维度: {len(embedding)}")

            return embedding

        except Exception as e:
            logger.error(f"查询嵌入失败: {e}")
            raise RuntimeError(f"查询嵌入失败: {e}") from e


class LazyDashScopeEmbeddings(Embeddings):
    """Delay embedding client creation until the first real embedding call."""

    def __init__(self, model: str, dimensions: int = 1024):
        self.model = model
        self.dimensions = dimensions
        self._delegate: DashScopeEmbeddings | None = None

    def _get_delegate(self) -> DashScopeEmbeddings:
        if self._delegate is None:
            self._delegate = DashScopeEmbeddings(
                api_key=config.dashscope_api_key,
                model=self.model,
                dimensions=self.dimensions,
            )
        return self._delegate

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return self._get_delegate().embed_documents(texts)

    def embed_query(self, text: str) -> List[float]:
        return self._get_delegate().embed_query(text)


# 全局单例
vector_embedding_service = LazyDashScopeEmbeddings(
    model=config.dashscope_embedding_model,
    dimensions=1024,
)

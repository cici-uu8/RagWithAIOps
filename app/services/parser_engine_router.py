"""文档格式与解析引擎路由分发器"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List

from app.models import ChunkingConfig, ParserEngine, ParserEngineInfo, ParserEngineRule


class ParserEngineRouter:
    """根据文件后缀匹配对应解析引擎"""

    def __init__(self, default_rules: List[ParserEngineRule] | None = None):
        self._default_rules = default_rules or [
            ParserEngineRule(file_types=["md", "txt"], engine=ParserEngine.PLAIN_TEXT),
            ParserEngineRule(file_types=["pdf", "docx", "xlsx"], engine=ParserEngine.MINERU),
        ]
        self._engine_info = {
            ParserEngine.PLAIN_TEXT: ParserEngineInfo(
                name=ParserEngine.PLAIN_TEXT.value,
                description="传统 md/txt 纯文本兼容解析通道",
                file_types=["md", "txt"],
                available=True,
                unavailable_reason="",
            ),
            ParserEngine.MINERU: ParserEngineInfo(
                name=ParserEngine.MINERU.value,
                description="面向复杂文档格式的 MinerU 优先解析通道",
                file_types=["pdf", "docx", "xlsx"],
                available=None,
                unavailable_reason="",
            ),
        }

    def resolve(self, file_type: str, chunking_config: ChunkingConfig | None = None) -> ParserEngine:
        """根据文件后缀名，确定对应的解析引擎"""
        normalized = self._normalize_file_type(file_type)
        candidate_rules = self._iter_rules(chunking_config) # 切块配置

        for rule in candidate_rules:
            normalized_file_types = {self._normalize_file_type(item) for item in rule.file_types}
            if normalized in normalized_file_types:
                return rule.engine

        raise ValueError(f"不支持该文件类型: {file_type}")

    def resolve_path(self, file_path: str | Path, chunking_config: ChunkingConfig | None = None) -> ParserEngine:
        """从文件路径获取对应的解析引擎"""
        suffix = Path(file_path).suffix.lower().lstrip(".") # suffix:后缀
        return self.resolve(suffix, chunking_config=chunking_config)

    def supports_file_type(self, file_type: str, chunking_config: ChunkingConfig | None = None) -> bool:
        """判断文件类型是否有可用解析引擎，不把异常泄漏给目录扫描调用方。"""
        try:
            self.resolve(file_type, chunking_config=chunking_config)
            return True
        except ValueError:
            return False

    def supports_path(self, file_path: str | Path, chunking_config: ChunkingConfig | None = None) -> bool:
        """判断文件路径是否命中当前解析规则。"""
        suffix = Path(file_path).suffix
        return self.supports_file_type(suffix, chunking_config=chunking_config)

    def list_engine_info(self) -> List[ParserEngineInfo]:
        """返回所有解析引擎的描述信息，用于后续可用性检查"""
        return [info.model_copy(deep=True) for info in self._engine_info.values()]

    def supported_file_types(self) -> List[str]:
        """按固定顺序返回所有支持的文件类型"""
        ordered: list[str] = []
        for info in self.list_engine_info():
            for file_type in info.file_types:
                if file_type not in ordered:
                    ordered.append(file_type)
        return ordered

    def _iter_rules(self, chunking_config: ChunkingConfig | None) -> Iterable[ParserEngineRule]:
        """获取最终要使用的解析规则。"""
        if chunking_config and chunking_config.parser_engine_rules:
            yield from chunking_config.parser_engine_rules
        yield from self._default_rules

    def _normalize_file_type(self, file_type: str) -> str:
        normalized = file_type.lower().strip().lstrip(".")
        if not normalized:
            raise ValueError("文件类型不能为空")
        return normalized


parser_engine_router = ParserEngineRouter()

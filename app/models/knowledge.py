"""知识库领域模型。"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ParserEngine(StrEnum):
    """本地文档入库流程所支持的解析引擎"""

    PLAIN_TEXT = "plain_text"
    MINERU = "mineru"


class RetrievalMode(StrEnum):
    """检索执行方式"""

    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"


class ContextGranularity(StrEnum):
    """作答阶段的上下文拼装粒度。

    只影响检索响应中上下文文本的组合方式，不改变结果身份字段。
    """

    CHUNK = "chunk"
    PARENT_CHUNK = "parent_chunk"
    FULL_DOC = "full_doc"


class ResultAggregation(StrEnum):
    """文档级检索结果聚合策略。

    ``DOC_LEVEL`` 表示可选启用的文档级结果规整策略，会按文档 ID 对命中内容分组，
    每份文档最多保留指定数量的高分片结果。
    """

    NONE = "none"
    DOC_LEVEL = "doc_level"


class DocumentStatus(StrEnum):
    """文档生命周期状态。"""

    UPLOADED = "uploaded"
    UPLOAD_FAILED = "upload_failed"
    PARSE_PENDING = "parse_pending"
    ENQUEUE_FAILED = "enqueue_failed"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"
    INDEX_PENDING = "index_pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    INDEX_FAILED = "index_failed"


class KnowledgeBaseType(StrEnum):
    """仅文档业务场景下的最简知识库类型集合。"""

    DOCUMENT = "document"


class ParserEngineRule(BaseModel):
    """解析引擎路由规则。"""

    file_types: List[str] = Field(default_factory=list, description="小写文件扩展名列表")
    engine: ParserEngine = Field(..., description="这些文件类型对应的解析引擎")


class ParserEngineInfo(BaseModel):
    """解析引擎元数据。"""

    name: str = Field(..., description="引擎名称")
    description: str = Field(default="", description="引擎说明")
    file_types: List[str] = Field(default_factory=list, description="支持的小写文件扩展名列表")
    available: Optional[bool] = Field(
        None,
        description="预留给后续环境检查的可用性标记",
    )
    unavailable_reason: str = Field(
        default="",
        description="预留给后续环境检查的不可用原因提示",
    )


class ArtifactManifest(BaseModel):
    """已解析文档的解析产物清单。"""

    schema_version: str = Field(..., description="产物清单 schema 版本")
    kb_id: str = Field(..., description="知识库标识")
    doc_id: str = Field(..., description="文档标识")
    source_file: str = Field(..., description="原始源文件路径")
    artifact_dir: str = Field(..., description="产物根目录")
    parser_engine: ParserEngine = Field(..., description="生成产物所使用的解析引擎")
    parser_version: str = Field(..., description="解析器版本字符串")
    postprocess_version: str = Field(..., description="后处理流水线版本")
    status: str = Field(..., description="清单状态")
    required_files: Dict[str, str] = Field(
        default_factory=dict,
        description="相对于 artifact_dir 的必需产物文件映射",
    )
    created_at: datetime = Field(..., description="清单创建时间")


class ChunkingConfig(BaseModel):
    """切块配置"""

    chunk_size: int = Field(512, description="目标切块大小")
    chunk_overlap: int = Field(80, description="相邻切块之间的重叠长度")
    separators: List[str] = Field(
        default_factory=lambda: ["\n\n", "\n", "。", "！", "？", ";", "；"],
        description="按优先级排序的分隔符列表",
    )
    strategy: Optional[str] = Field(None, description="预留的切块策略名称")
    parser_engine_rules: List[ParserEngineRule] = Field(
        default_factory=list,
        description="可选的文件类型到解析引擎覆盖规则",
    )

    def resolve_parser_engine(self, file_type: str) -> Optional[ParserEngine]:
        """首次匹配规则解析所用引擎"""
        normalized = file_type.lower().lstrip(".")
        for rule in self.parser_engine_rules:
            if normalized in {item.lower().lstrip(".") for item in rule.file_types}:
                return rule.engine
        return None


class KnowledgeBase(BaseModel):
    """知识库对象"""

    kb_id: str = Field(..., description="稳定的知识库标识")
    name: str = Field(..., description="知识库名称")
    type: KnowledgeBaseType = Field(
        default=KnowledgeBaseType.DOCUMENT,
        description="仅支持文档型知识库",
    )
    description: str = Field(default="", description="知识库说明")
    chunking_config: ChunkingConfig = Field(
        default_factory=ChunkingConfig,
        description="切块与解析器路由配置",
    )
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="最后更新时间")


class SourceRef(BaseModel):
    """从产物(chunk)一路传递到检索结果中的稳定来源引用"""

    kb_id: str = Field(..., description="知识库标识")
    doc_id: str = Field(..., description="文档标识")
    chunk_id: str = Field(..., description="切块标识")
    source_file: str = Field(..., description="原始文件名或路径")
    page_start: Optional[int] = Field(None, description="起始页码")
    page_end: Optional[int] = Field(None, description="结束页码")
    heading_path: List[str] = Field(default_factory=list, description="标题层级路径")
    content_type: str = Field("text", description="语义内容类型")
    parser_engine: ParserEngine = Field(..., description="生成该切块所使用的解析引擎")


class DocumentRecord(BaseModel):
    """文档记录"""

    doc_id: str = Field(..., description="稳定的文档标识")
    kb_id: str = Field(..., description="知识库标识")
    file_name: str = Field(..., description="原始文件名")
    file_ext: str = Field(..., description="不带点号的小写文件扩展名")
    original_path: str = Field(..., description="存储后的原始文件路径")
    artifact_dir: str = Field(..., description="产物根目录")
    parser_engine: ParserEngine = Field(..., description="选定的解析引擎")
    status: DocumentStatus = Field(..., description="文档生命周期状态")
    status_detail: str = Field(default="", description="当前状态成立的业务说明")
    status_source: str = Field(default="", description="确认当前状态的代码入口或责任方")
    status_evidence: Dict[str, Any] = Field(default_factory=dict, description="当前状态成立的结构化证据")
    status_confirmed_at: Optional[datetime] = Field(None, description="当前状态被确认的时间")
    parser_version: Optional[str] = Field(None, description="解析器版本字符串")
    error_message: str = Field(default="", description="最近一次错误信息")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="文档级元数据")
    created_at: Optional[datetime] = Field(None, description="创建时间")
    updated_at: Optional[datetime] = Field(None, description="最后更新时间")


class ChunkRecord(BaseModel):
    """切块记录"""

    chunk_id: str = Field(..., description="稳定的切块标识")
    doc_id: str = Field(..., description="文档标识")
    kb_id: str = Field(..., description="知识库标识")
    content: str = Field(..., description="切块文本内容")
    chunk_index: int = Field(..., description="切块在文档内的顺序")
    start_index: int = Field(..., description="在源文本中的起始index")
    end_index: int = Field(..., description="在源文本中的结束index")
    heading_path: List[str] = Field(default_factory=list, description="标题层级路径")
    page_start: Optional[int] = Field(None, description="起始页码")
    page_end: Optional[int] = Field(None, description="结束页码")
    content_type: str = Field("text", description="语义切块类型")
    source_ref: SourceRef = Field(..., description="稳定来源引用")
    quality_flags: List[str] = Field(default_factory=list, description="切块质量标记")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="切块级元数据")
    parent_chunk_id: Optional[str] = Field(None, description="预留的父切块标识")


class RetrievalQuery(BaseModel):
    """面向带引用检索的结构化输入"""

    query: str = Field(..., description="自然语言检索问题")
    top_k: int = Field(3, description="返回的检索命中数量")
    retrieval_mode: RetrievalMode = Field(
        RetrievalMode.DENSE_ONLY,
        description="拼装引用证据前使用的召回模式",
    )
    knowledge_base_ids: List[str] = Field(
        default_factory=list,
        description="可选的知识库范围过滤条件",
    )
    document_ids: list[str] = Field(
        default_factory=list,
        description="可选的文档 ID 范围过滤条件，用于文件名/doc_id 精确限定检索。",
    )
    context_granularity: ContextGranularity = Field(
        default=ContextGranularity.CHUNK,
        description=(
            "回答时的上下文拼装粒度，切块级（chunk）、父切块级（parent_chunk）或全文档级（full_doc）。"
        ),
    )
    result_aggregation: ResultAggregation = Field(
        default=ResultAggregation.NONE,
        description=(
            "按文档聚合结果的开关"
            "``doc_level`` 会显式开启按 ``doc_id`` 分组"
        ),
    )
    top_chunks_per_doc: int = Field(
        default=1,
        description=(
            "按文档聚合时：每个 ``doc_id`` 最多保留的切块数。"
        ),
    )
    doc_oversample_factor: int = Field(
        default=4,
        description=(
            "按文档聚合时的候选池放大倍数（高级参数，仅用于实验调参)"
        ),
    )


class RetrievalResult(BaseModel):
    """带稳定引用元数据的结构化检索命中结果"""

    kb_id: str = Field(..., description="知识库标识")
    doc_id: str = Field(..., description="文档标识")
    chunk_id: str = Field(..., description="切块标识")
    content: str = Field(..., description="召回到的切块内容")
    score: Optional[float] = Field(None, description="相似度分数或距离值")
    source_ref: SourceRef = Field(..., description="稳定来源引用")
    citation_text: str = Field(..., description="可直接展示的引用文本")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="原始元数据快照")


class RetrievalResponse(BaseModel):
    """工具边界返回的结构化检索响应。"""

    query: RetrievalQuery = Field(..., description="原始检索请求")
    results: List[RetrievalResult] = Field(default_factory=list, description="结构化命中结果")
    context_text: str = Field(default="", description="面向模型的上下文文本")
    empty_message: str = Field(default="没有找到相关信息。", description="无命中时返回的提示语")

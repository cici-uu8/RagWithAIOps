# SuperBizAgent 增强版 RAG 源码精读

日期: 2026-05-21

## 0. 阅读说明

这份文档按“源码精读”标准解释增强后的 RAG 项目，不是只概括文件职责。

每个文件都按下面结构展开:

1. 整体架构与核心依赖。
2. 核心类、函数、字段的作用。
3. 关键执行流程。
4. 设计亮点、边界和风险。
5. 典型调用链。
6. 面试或项目复盘时怎么讲。

建议先读主教程:

- [docs/oncall_agent_rag_enhanced_tutorial.md](./oncall_agent_rag_enhanced_tutorial.md)

再按本文档逐文件看源码。

如果你是按当前 release 来读，这份深读版仍然以核心 10-file 主线为主；
`ChunkPolicyService`、`context_granularity` / `result_aggregation`、P6 关闭与当前阅读口径，已在主教程的第 8 / 11 章补充说明。

---

## 1. [app/models/knowledge.py](../app/models/knowledge.py)

这个文件实现了增强版 RAG 的**领域模型层**，定义了文档、chunk、parser、artifact、retrieval、citation 的核心数据结构。它是后续所有 service 的共同语言。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`knowledge.py` 是 P1/P2/P3 的模型中心。

它解决的问题是:

- 文档不再只是一个文件路径，而是 `DocumentRecord`。
- chunk 不再只是一个字符串，而是 `ChunkRecord`。
- 来源引用不再临时拼接，而是 `SourceRef`。
- 检索请求和结果不再是裸字符串，而是 `RetrievalQuery`、`RetrievalResult`、`RetrievalResponse`。
- parser 类型、文档状态、检索模式都有受控枚举，避免各层随便写字符串。

如果没有这个文件，后面的 parser、indexer、retriever、reranker 很容易各自定义一套字段，系统会变成“能跑但不可维护”的 RAG 脚本。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `datetime` | 记录知识库、文档、manifest 的创建和更新时间 |
| `StrEnum` | 定义字符串枚举，方便 JSON 序列化和配置读取 |
| `Any/Dict/List/Optional` | Pydantic 模型字段类型 |
| `BaseModel` | 所有领域模型的 Pydantic 基类 |
| `Field` | 给字段添加默认值、描述和约束语义 |

---

### 二、核心枚举

#### 1. `ParserEngine`

```python
class ParserEngine(StrEnum):
    PLAIN_TEXT = "plain_text"
    MINERU = "mineru"
```

这个枚举固定当前项目支持的 parser 类型:

- `plain_text`: 旧的 `md/txt` 兼容路径。
- `mineru`: `pdf/docx/xlsx` 的 MinerU-first 解析路径。

设计意义:

- API、router、ingestion、indexer 不再用散落字符串判断 parser。
- 后续如果新增 parser，例如 `docling`，应该先扩展这个枚举，再扩展 router 和 adapter。
- `ArtifactManifest.parser_engine`、`SourceRef.parser_engine`、`DocumentRecord.parser_engine` 都引用同一个枚举。

#### 2. `RetrievalMode`

```python
class RetrievalMode(StrEnum):
    DENSE_ONLY = "dense_only"
    SPARSE_ONLY = "sparse_only"
    HYBRID = "hybrid"
    HYBRID_RERANK = "hybrid_rerank"
```

这个枚举是 P3 检索质量层的开关。

各模式含义:

| 模式 | 含义 | 当前定位 |
|---|---|---|
| `dense_only` | 只走向量检索 | 默认主链路 |
| `sparse_only` | 只走 BM25 稀疏检索 | 评估和门禁使用 |
| `hybrid` | dense + sparse 后 RRF 融合 | 显式启用 |
| `hybrid_rerank` | hybrid 后再 rerank | 显式启用 |

设计意义:

- 让检索模式成为请求参数，而不是散落的函数入口。
- `RetrievalService` 可以根据 mode 决定走 dense 还是 hybrid。
- 离线评估脚本能用同一套 query 对多种模式做对比。

#### 3. `DocumentStatus`

```python
class DocumentStatus(StrEnum):
    UPLOADED = "uploaded"
    UPLOAD_FAILED = "upload_failed"
    PARSE_PENDING = "parse_pending"
    PARSING = "parsing"
    PARSED = "parsed"
    PARSE_FAILED = "parse_failed"
    INDEX_PENDING = "index_pending"
    INDEXING = "indexing"
    INDEXED = "indexed"
    INDEX_FAILED = "index_failed"
```

这是文档生命周期状态机。

典型成功流程:

```text
uploaded
-> parse_pending
-> parsing
-> parsed
-> index_pending
-> indexing
-> indexed
```

失败状态:

```text
upload_failed
parse_failed
index_failed
```

设计意义:

- 可以区分上传失败、解析失败、索引失败。
- `DocumentIngestionService` 能根据状态判断是否允许进入索引。
- `KnowledgeMetadataStore` 能持久化文档状态，方便重试和排查。

#### 4. `KnowledgeBaseType`

```python
class KnowledgeBaseType(StrEnum):
    DOCUMENT = "document"
```

当前只支持文档型知识库。

它看起来简单，但有两个作用:

- 保留和 WeKnora 知识库模型的对齐空间。
- 后续如果扩展 FAQ、网页、工单等知识库类型，有明确扩展位置。

---

### 三、配置与描述模型

#### 1. `ParserEngineRule`

```python
class ParserEngineRule(BaseModel):
    file_types: List[str]
    engine: ParserEngine
```

这个模型表示“文件扩展名 -> parser engine”的规则。

例如:

```text
["md", "txt"] -> plain_text
["pdf", "docx", "xlsx"] -> mineru
```

它被 `ParserEngineRouter` 使用。

#### 2. `ParserEngineInfo`

```python
class ParserEngineInfo(BaseModel):
    name: str
    description: str
    file_types: List[str]
    available: Optional[bool]
    unavailable_reason: str
```

这个模型用于描述 parser 能力。

字段解释:

| 字段 | 含义 |
|---|---|
| `name` | parser 名称 |
| `description` | 人类可读描述 |
| `file_types` | 支持的扩展名 |
| `available` | parser 当前是否可用 |
| `unavailable_reason` | 不可用原因 |

当前 `MinerU` 的 `available` 是预留项，因为实际可用性和本地 CLI、模型、环境有关。

#### 3. `ChunkingConfig`

```python
class ChunkingConfig(BaseModel):
    chunk_size: int = 512
    chunk_overlap: int = 80
    separators: List[str]
    strategy: Optional[str]
    parser_engine_rules: List[ParserEngineRule]
```

这个模型从 WeKnora 的 chunking 配置思想裁剪而来。

重点方法:

```python
def resolve_parser_engine(self, file_type: str) -> Optional[ParserEngine]
```

它会在 `parser_engine_rules` 里查找匹配扩展名。如果找不到，则返回 `None`，由 router 使用默认规则。

设计意义:

- 当前默认规则固定。
- 未来可以按知识库配置覆盖 parser 路由。
- 不需要把配置逻辑写死在 API 或 indexer。

---

### 四、核心领域对象

#### 1. `KnowledgeBase`

```python
class KnowledgeBase(BaseModel):
    kb_id: str
    name: str
    type: KnowledgeBaseType
    description: str
    chunking_config: ChunkingConfig
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
```

它表示一个知识库。

当前项目主要使用默认知识库 `default`，但模型层已经保留 `kb_id`，这让后续多知识库检索可以通过 `knowledge_base_ids` 做过滤。

#### 2. `SourceRef`

```python
class SourceRef(BaseModel):
    kb_id: str
    doc_id: str
    chunk_id: str
    source_file: str
    page_start: Optional[int]
    page_end: Optional[int]
    heading_path: List[str]
    content_type: str
    parser_engine: ParserEngine
```

`SourceRef` 是 citation 的核心锚点。

它回答的问题是:

```text
这条检索结果到底来自哪个知识库、哪个文档、哪个 chunk、哪一页、哪个章节、哪种内容类型、哪个 parser?
```

它贯穿:

```text
ArtifactChunkBuilderService
-> ChunkRecord.metadata
-> Milvus metadata
-> RetrievalService
-> RetrievalResult
-> citation_text
```

设计亮点:

- citation 不在回答阶段临时拼。
- source identity 贯穿整个链路。
- hybrid/rerank 只能改变排序，不能改变 `SourceRef`。

#### 3. `DocumentRecord`

```python
class DocumentRecord(BaseModel):
    doc_id: str
    kb_id: str
    file_name: str
    file_ext: str
    original_path: str
    artifact_dir: str
    parser_engine: ParserEngine
    status: DocumentStatus
    parser_version: Optional[str]
    error_message: str
    metadata: Dict[str, Any]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
```

`DocumentRecord` 是文档生命周期对象。

重点字段:

| 字段 | 作用 |
|---|---|
| `doc_id` | 文档稳定 ID |
| `kb_id` | 所属知识库 |
| `original_path` | 原始文件路径 |
| `artifact_dir` | 解析产物目录 |
| `parser_engine` | 使用的 parser |
| `status` | 当前状态 |
| `error_message` | 失败原因 |

它让上传文件从“磁盘上的一个文件”变成“可追踪、可解析、可索引、可失败恢复”的系统对象。

#### 4. `ChunkRecord`

```python
class ChunkRecord(BaseModel):
    chunk_id: str
    doc_id: str
    kb_id: str
    content: str
    chunk_index: int
    start_index: int
    end_index: int
    heading_path: List[str]
    page_start: Optional[int]
    page_end: Optional[int]
    content_type: str
    source_ref: SourceRef
    quality_flags: List[str]
    metadata: Dict[str, Any]
    parent_chunk_id: Optional[str]
```

`ChunkRecord` 是检索单元对象。

它不只是文本内容，还包括:

- 在文档中的位置。
- 所属文档和知识库。
- 页码和章节。
- 来源引用。
- 质量标记。
- 可写入 Milvus 的 metadata。

设计意义:

- BM25 直接从 metadata store 读取 `ChunkRecord`。
- Milvus 写入和 citation 组装使用同一份身份字段。
- 表格 chunk 和正文 chunk 可以统一进入 retrieval。

---

### 五、检索模型

#### 1. `RetrievalQuery`

```python
class RetrievalQuery(BaseModel):
    query: str
    top_k: int = 3
    retrieval_mode: RetrievalMode = RetrievalMode.DENSE_ONLY
    knowledge_base_ids: List[str]
```

它是检索入口对象。

重点字段:

- `query`: 用户检索文本。
- `top_k`: 返回数量。
- `retrieval_mode`: dense/sparse/hybrid/rerank 模式。
- `knowledge_base_ids`: 可选知识库过滤。

#### 2. `RetrievalResult`

```python
class RetrievalResult(BaseModel):
    kb_id: str
    doc_id: str
    chunk_id: str
    content: str
    score: Optional[float]
    source_ref: SourceRef
    citation_text: str
    metadata: Dict[str, Any]
```

这是单条结构化检索结果。

它比普通 RAG hit 多了:

- `source_ref`
- `citation_text`
- 完整 metadata 快照

#### 3. `RetrievalResponse`

```python
class RetrievalResponse(BaseModel):
    query: RetrievalQuery
    results: List[RetrievalResult]
    context_text: str
    empty_message: str
```

这是 retrieval service 的统一返回对象。

它同时服务两类消费者:

- LLM 需要 `context_text`。
- 工具、评估、UI 需要 `results` 里的结构化 evidence。

---

### 六、典型调用流程

以一个 PDF 文档进入检索为例:

1. `DocumentIngestionService` 创建 `DocumentRecord`。
2. `ParserEngineRouter` 选择 `ParserEngine.MINERU`。
3. `MinerUParserAdapter` 解析并写 artifact。
4. `ArtifactChunkBuilderService` 构造 `ChunkRecord` 和 `SourceRef`。
5. `VectorIndexService` 写入 Milvus 和 metadata store。
6. `RetrievalService` 返回 `RetrievalResult`。
7. `citation_text` 从 `SourceRef` 生成。

---

### 七、关键设计亮点

1. **模型先行**: 后续 service 不是各自定义字段，而是围绕统一模型协作。
2. **状态明确**: 上传、解析、索引失败都有独立状态。
3. **来源可追溯**: `SourceRef` 是 citation 的稳定锚点。
4. **检索可扩展**: `RetrievalMode` 让 dense、sparse、hybrid、rerank 共用入口。
5. **兼容旧链路**: `metadata` 保留字典出口，便于旧字段兼容和新字段扩展。

---

### 八、边界与风险

当前仍有一些边界:

- `default` 知识库 ID 还存在硬编码点。`default` 现在是**单 KB 阶段约定**，后续再抽配置/registry。
- `metadata` 是自由 dict，后续如果字段继续增多，可以考虑更强 schema。`metadata`  先保留**兼容性出口**，真要扩字段时再收敛 schema。
- 当前 `KnowledgeBase` 没有完整多租户管理，只是为后续扩展保留对象。`KnowledgeBase` 目前只是**对象壳**，多租户是后续能力，不属于当前闭环。

---

### 九、面试里怎么讲

可以讲成:

> 我先把 RAG 的领域对象补齐，包括 DocumentRecord、ChunkRecord、SourceRef 和 RetrievalResult。这样后续 parser、index、retrieval、rerank 都围绕同一套身份契约工作，citation 不是回答阶段临时拼出来的，而是从 chunk metadata 一路传到 retrieval result。

---

## 2. [app/services/parser_engine_router.py](../app/services/parser_engine_router.py)

这个文件实现了**解析引擎路由服务（Parser Engine Router）**，负责把文件类型稳定映射到解析引擎。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`parser_engine_router.py` 是文档接入链路里的第一个决策点。

它解决的问题是:

- `.md/.txt` 应该继续走原 plain-text 兼容链路。
- `.pdf/.docx/.xlsx` 应该进入 MinerU-first 解析链路。
- 文件类型判断不能散落在 API、ingestion、indexer 里。
- 后续新增 parser 时，需要有一个统一扩展点。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `Path` | 从文件路径中解析扩展名 |
| `Iterable/List` | 给规则迭代和返回值做类型注解 |
| `ChunkingConfig` | 可选地从知识库配置覆盖 parser 规则 |
| `ParserEngine` | parser 枚举 |
| `ParserEngineInfo` | parser 能力描述 |
| `ParserEngineRule` | 文件类型到 parser 的路由规则 |

---

### 二、核心类: `ParserEngineRouter`

#### 1. 类作用

`ParserEngineRouter` 对外提供三个主要能力:

1. 根据扩展名解析 parser。
2. 根据文件路径解析 parser。
3. 返回当前支持的 parser 和文件类型列表。

它是“文件类型 -> parser_engine”的唯一真源。

#### 2. 初始化方法 `__init__`

```python
def __init__(self, default_rules: List[ParserEngineRule] | None = None):
    self._default_rules = default_rules or [
        ParserEngineRule(file_types=["md", "txt"], engine=ParserEngine.PLAIN_TEXT),
        ParserEngineRule(file_types=["pdf", "docx", "xlsx"], engine=ParserEngine.MINERU),
    ]
```

默认规则:

| 文件类型 | parser |
|---|---|
| `md/txt` | `plain_text` |
| `pdf/docx/xlsx` | `mineru` |

这段代码的重点是“默认规则可覆盖”。测试或未来配置可以传入 `default_rules`。

#### 3. `_engine_info`

```python
self._engine_info = {
    ParserEngine.PLAIN_TEXT: ParserEngineInfo(...),
    ParserEngine.MINERU: ParserEngineInfo(...),
}
```

`_engine_info` 保存 parser 描述信息:

- parser 名称。
- 文字说明。
- 支持的文件类型。
- 可用性标记。
- 不可用原因。

当前 `plain_text.available=True`，`mineru.available=None`。

这说明 plain_text 是无外部依赖的稳定路径，而 MinerU 是否可用取决于本地 CLI、模型和运行环境，后续可以做可用性检查。

---

### 三、核心方法

#### 1. `resolve`

```python
def resolve(self, file_type: str, chunking_config: ChunkingConfig | None = None) -> ParserEngine:
```

作用: 根据文件扩展名返回 parser。

核心流程:

1. `_normalize_file_type(file_type)` 规范化扩展名。
2. `_iter_rules(chunking_config)` 得到规则列表。
3. 遍历规则，看扩展名是否命中。
4. 命中则返回 `rule.engine`。
5. 没命中则抛 `ValueError`。

关键点:

```python
normalized_file_types = {self._normalize_file_type(item) for item in rule.file_types}
```

这里会统一处理:

- `".pdf"`
- `"PDF"`
- `" pdf "`

都归一为 `pdf`。

为什么抛异常而不是默认 plain_text?

因为 PDF/DOCX/XLSX 如果 parser 不明确，不能静默退回普通文本，否则会造成“看似入库成功，实际内容错误”的隐性问题。

#### 2. `resolve_path`

```python
def resolve_path(self, file_path: str | Path, chunking_config: ChunkingConfig | None = None) -> ParserEngine:
    suffix = Path(file_path).suffix.lower().lstrip(".")
    return self.resolve(suffix, chunking_config=chunking_config)
```

作用: 根据文件路径解析 parser。

典型调用方:

- `VectorIndexService.index_single_file()`

它让 legacy 单文件索引入口也能使用统一 parser 路由。

#### 3. `list_engine_info`

```python
def list_engine_info(self) -> List[ParserEngineInfo]:
    return [info.model_copy(deep=True) for info in self._engine_info.values()]
```

作用: 返回 parser 描述信息。

为什么要 `deep=True`?

因为返回的是模型副本，避免外部调用方修改内部 `_engine_info`。

#### 4. `supported_file_types`

```python
def supported_file_types(self) -> List[str]:
```

作用: 返回所有支持扩展名，顺序稳定。

典型调用方:

- `DocumentIngestionService.ingest_upload()`
- `DocumentIngestionService.ingest_directory()`

这样 API 层不需要自己维护扩展名列表，文件类型判断统一留在 ingestion / router 层。

#### 5. `_iter_rules`

```python
def _iter_rules(self, chunking_config: ChunkingConfig | None) -> Iterable[ParserEngineRule]:
    if chunking_config and chunking_config.parser_engine_rules:
        yield from chunking_config.parser_engine_rules
    yield from self._default_rules
```

作用: 先使用知识库配置里的覆盖规则，再使用默认规则。

设计意义:

- 当前阶段可以固定 `.md/.txt`、`.pdf/.docx/.xlsx`。
- 后续某个知识库需要特殊 parser 时，可以通过配置覆盖。

#### 6. `_normalize_file_type`

```python
def _normalize_file_type(self, file_type: str) -> str:
    normalized = file_type.lower().strip().lstrip(".")
    if not normalized:
        raise ValueError("File type cannot be empty")
    return normalized
```

作用: 规范化扩展名。

如果输入为空，直接失败，避免空扩展名误入默认分支。

---

### 四、全局单例

```python
parser_engine_router = ParserEngineRouter()
```

项目其他模块直接 import 这个单例使用。

好处:

- 不重复创建 router。
- 默认规则集中。
- API 和 service 使用同一份规则。

---

### 五、典型调用流程

以 PDF 上传为例:

1. `app/api/file.py` 读取上传文件名。
2. API 直接把 `file.filename`、`content` 和 `kb_id` 交给 `DocumentIngestionService.ingest_upload()`。
3. `DocumentIngestionService.ingest_upload()` 先清洗文件名，再调用 `parser_engine_router.resolve("pdf")`。
4. router 返回 `ParserEngine.MINERU`。
5. 文档进入 `parse_pending`，等待 MinerU 解析。

---

### 六、关键设计亮点

1. **路由集中**: 文件类型判断不散落。
2. **默认规则清楚**: md/txt 和 pdf/docx/xlsx 边界明确。
3. **支持覆盖**: `ChunkingConfig.parser_engine_rules` 预留扩展。
4. **错误显式**: 不支持类型直接抛异常，不静默降级。
5. **API 复用**: 允许扩展名列表来自同一 router。

---

### 七、边界与风险

- 当前只是按扩展名路由，没有做 MIME sniffing。当前路由策略基于文件扩展名，不做 MIME sniffing；这是当前受控上传场景下的有意简化。
- `MinerU.available` 还没有实时检查本地 CLI 和模型状态。MinerU.available 目前是预留可用性字段，尚未接入本地 CLI 与模型状态探测。
- 如果后续支持图片或 HTML，需要扩展 `ParserEngine`、router 默认规则和 adapter。图片与 HTML 暂未纳入当前解析闭环；若后续纳入，需要同步扩展 parser 枚举、默认路由规则与对应 adapter。

---

### 八、面试里怎么讲

可以讲成:

> 我把 parser 选择做成独立 router，而不是写在 upload 或 indexer 里。这样文件类型到解析引擎的映射有唯一真源，md/txt 保持旧链路，pdf/docx/xlsx 明确进入 MinerU。后续新增 parser 或做可用性检查，也只需要扩展 router 和对应 adapter。

---

## 3. [app/services/document_ingestion_service.py](../app/services/document_ingestion_service.py)

这个文件实现了**正式文档接入工作流（Document Ingestion Service）**，负责保存原件、创建文档记录、选择 parser、维护状态流，并把文档推进到解析或索引阶段。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`document_ingestion_service.py` 是上传 API 和后续 parser/indexer 之间的编排层。

它不直接做三件事:

- 不直接执行 MinerU CLI 的细节。
- 不直接写 Milvus 的底层逻辑。
- 不直接做 dense/hybrid/rerank 检索。

它负责:

- 生成稳定 `doc_id`。
- 保存上传原件。
- 建立 `DocumentRecord`。
- 根据 parser engine 决定 plain_text 同步索引或 mineru 延迟解析。
- 在索引前校验 artifacts。
- 在 artifact 准备失败时记录 `index_failed` 并重新抛异常。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `datetime` | 记录文档创建和更新时间 |
| `hashlib` | 生成内容 hash，参与稳定 doc_id |
| `Path` | 构建 original/artifact 路径 |
| `uuid5/NAMESPACE_URL` | 基于稳定 seed 生成确定性 doc_id |
| `logger` | 记录接入过程 |
| `DocumentRecord/DocumentStatus/ParserEngine` | 文档对象、状态和 parser 枚举 |
| `artifact_chunk_builder_service` | 把 artifact 转成可索引对象 |
| `artifact_manifest_service` | 校验 artifact manifest |
| `knowledge_metadata_store` | 保存文档状态 |
| `mineru_parser_adapter` | 执行 MinerU 解析 |
| `parser_engine_router` | 文件类型到 parser 的路由 |
| `vector_index_service` | plain_text 或 prepared artifact 入库 |

---

### 二、核心类: `DocumentIngestionService`

#### 1. 类作用

这个类是文档接入的主控器。

它把上传后的文件推进到:

```text
uploaded
-> parse_pending
-> parsing
-> parsed
-> index_pending
-> indexing
-> indexed
```

复杂文档会在 `parse_pending` 暂停，等待 `process_deferred_document()` 继续推进。

#### 2. 初始化方法

```python
def __init__(self, upload_root: str | Path = "./uploads"):
    self.upload_root = Path(upload_root)
```

字段说明:

- `upload_root`: 上传根目录。

注意: production upload 边界现在要求调用方显式传 `kb_id`，不再在 `DocumentIngestionService` 内部兜底成 `default`。eval 脚本里的 `default` 只属于隔离评测约定，不代表生产入口默认值。

---

### 三、核心方法 1: `ingest_upload`

```python
def ingest_upload(self, filename: str, content: bytes, kb_id: str) -> DocumentRecord:
```

这是上传文件进入正式接入链路的入口。

#### 输入参数

| 参数 | 含义 |
|---|---|
| `filename` | 上传文件名 |
| `content` | 文件二进制内容 |
| `kb_id` | 必填知识库 ID，production 调用方必须显式声明 |

#### 核心逻辑

##### 步骤 1: 基础规范化

```python
if kb_id is None or not str(kb_id).strip():
    raise ValueError("知识库 ID 为必填项，不能为空、空值或空白字符 ")
kb = kb_id
safe_filename = self._sanitize_filename(filename)
file_ext = self._get_file_extension(safe_filename)
parser_engine = parser_engine_router.resolve(file_ext)
```

这里完成:

- 知识库 ID 必填校验。
- 文件名清洗。
- 扩展名提取。
- parser 路由。

##### 步骤 2: 生成稳定身份

```python
doc_id = self._build_uploaded_doc_id(kb, safe_filename, content)
original_path = self._build_original_path(kb, doc_id, safe_filename)
artifact_dir = self._build_artifact_dir(kb, doc_id)
```

路径结构:

```text
uploads/documents/<kb_id>/<doc_id>/original/<safe_filename>
uploads/documents/<kb_id>/<doc_id>/artifacts/
```

这让每个文档都有独立 artifact 根目录。

##### 步骤 3: 构建 DocumentRecord

```python
document_record = self._build_document_record(...)
```

初始状态是:

```text
DocumentStatus.UPLOADED
```

metadata 会记录:

```text
legacy_path=False
upload_origin=api
file_size
```

##### 步骤 4: 保存原始文件

```python
original_path.parent.mkdir(parents=True, exist_ok=True)
artifact_dir.mkdir(parents=True, exist_ok=True)
original_path.write_bytes(content)
```

如果失败，请求直接抛错，DB 不创建 `DocumentRecord`。这保持了一个重要不变量: metadata store 里的文档必须至少已经完成原始文件落盘。

##### 步骤 5: 按 parser 分支

```python
if parser_engine == ParserEngine.PLAIN_TEXT:
    return self._ingest_plain_text_document(document_record)

processing_job = document_processing_queue.enqueue_deferred_document(doc_id)
queued_record = knowledge_metadata_store.transition_document_status(
    doc_id,
    DocumentStatus.PARSE_PENDING,
    status_evidence={
        "processing_job_id": processing_job.job_id,
        "processing_queue": processing_job.queue_name,
        "enqueued_at": datetime.now().isoformat(),
    },
)
return queued_record
```

分支含义:

- `plain_text`: 轻量文档，直接同步解析和索引。
- `mineru`: 复杂文档，先保存并入队，入队成功后才进入带队列证据的 `parse_pending`。

---

### 四、核心方法 2: `_ingest_plain_text_document`

```python
def _ingest_plain_text_document(self, document_record: DocumentRecord) -> DocumentRecord:
```

作用: 让 md/txt 也走正式生命周期。

核心状态流:

```text
parse_pending
-> vector_index_service.index_document_record(parse_pending_record)
```

这里不是因为 md/txt 真需要 heavy parser，而是为了把“已确认的阶段”写进状态，而不是提前写成 parsed。

如果发生异常:

```python
logger.error(...)
latest = knowledge_metadata_store.get_document(document_record.doc_id)
return latest or self._copy_document_record(..., status=PARSE_FAILED)
```

注意这里和 `prepare_artifacts_for_index()` 的异常策略不同:

- plain_text 接入失败会尽量返回当前状态。
- artifact 准备失败会明确 `raise` 给调用方。

---

### 五、核心方法 3: `process_deferred_document`

```python
def process_deferred_document(self, doc_id: str) -> DocumentRecord:
```

作用: 处理延迟解析文档。它本身仍是同步业务函数，真正的异步调度由 RQ worker 负责。

核心逻辑:

```python
document_record = knowledge_metadata_store.get_document(doc_id)
if document_record is None:
    raise ValueError(...)

if parser_engine == PLAIN_TEXT:
    return self._ingest_plain_text_document(document_record)

if parser_engine == MINERU:
    return mineru_parser_adapter.parse_document(document_record)
```

它不吞异常。

原因:

- parser adapter 负责记录 `parse_failed`。
- RQ worker / 调用方负责决定重试、报错还是停止。

这是项目里明确的异常边界:

```text
service 记录状态
任务系统决定重试或失败归档
```

---

### 六、异步入口: `document_processing_queue.py`

```python
enqueue_deferred_document(doc_id)
process_deferred_document_job(doc_id)
```

上传接口不会在请求线程里跑 MinerU。`ingest_upload()` 内部负责投递 RQ 任务，并在投递成功后返回带队列证据的 `parse_pending`:

```text
upload -> uploaded -> RQ enqueue -> parse_pending(with job evidence)
```

worker 处理逻辑:

```text
process_deferred_document_job(doc_id)
-> DocumentIngestionService.process_deferred_document(doc_id)
-> MinerUParserAdapter.parse_document()
-> status index_pending
-> VectorIndexService.index_document_record()
-> status indexed / index_failed
```

worker 启动命令:

```bash
python -m app.workers.document_processing_worker
```

这层没有引入 Celery 的 broker/result-backend 配置面，只用 RQ + Redis 做最小可靠队列。本地 `vector-database.yml` 已包含 Redis 服务；任务返回值只包含 `doc_id/status/parser_engine`，不把正文、chunk 或完整日志塞进任务结果。

---

### 七、核心方法 4: `validate_artifacts_for_index`

```python
def validate_artifacts_for_index(self, doc_id: str):
```

作用: 索引前校验 artifact。

步骤:

1. 从 metadata store 查 `DocumentRecord`。
2. 检查文档状态是否允许进入索引校验。
3. 调用 `artifact_manifest_service.validate_manifest(document_record.artifact_dir)`。

允许状态:

```text
parsed
index_pending
indexing
indexed
```

设计意义:

- 防止 `uploaded` 或 `parse_failed` 的文档直接进入索引。
- 防止缺 artifact 的文档被静默写入 Milvus。

---

### 八、核心方法 5: `prepare_artifacts_for_index`

```python
def prepare_artifacts_for_index(self, doc_id: str):
```

这是 P2-5 的关键入口。

核心流程:

```text
get DocumentRecord
-> validate_artifacts_for_index()
-> artifact_chunk_builder_service.prepare()
-> return PreparedIndexArtifacts
```

失败处理:

```python
knowledge_metadata_store.transition_document_status(
    doc_id,
    DocumentStatus.INDEX_FAILED,
    status_source="DocumentIngestionService.prepare_artifacts_for_index",
    status_detail="parsed artifact validation or chunk adaptation failed",
    status_evidence={"doc_id": doc_id, "error_type": type(exc).__name__},
    error_message=str(exc),
)
raise
```

这段代码体现了一个重要设计:

- 失败状态由 service 记录。
- 失败状态不是裸写入，必须带来源、说明和结构化证据。
- 异常继续向上传播。
- 上层可以决定是否重试或终止。

---

### 九、辅助方法

#### 1. `_build_uploaded_doc_id`

```python
content_hash = hashlib.sha1(content).hexdigest()
stable_seed = f"{kb_id}:{safe_filename}:{content_hash}"
return f"doc_{uuid5(NAMESPACE_URL, stable_seed)}"
```

作用: 生成稳定 doc_id。

同一 `kb_id + filename + content` 会得到同一个 `doc_id`。

#### 2. `_build_original_path`

```python
uploads/documents/<kb_id>/<doc_id>/original/<safe_filename>
```

作用: 固定原始文件路径。

#### 3. `_build_artifact_dir`

```python
uploads/documents/<kb_id>/<doc_id>/artifacts
```

作用: 固定 artifact 根目录。

#### 4. `_copy_document_record`

使用 Pydantic 的 `model_copy(update=...)` 复制记录并更新状态，避免原对象被隐式修改。

---

### 十、典型调用流程

#### 1. 上传 Markdown

```text
API /upload
-> ingest_upload()
-> router.resolve("md") = plain_text
-> save original
-> status uploaded
-> _ingest_plain_text_document()
-> status parse_pending
-> vector_index_service.index_document_record()
-> status indexed
```

#### 2. 上传 PDF

```text
API /upload
-> ingest_upload()
-> router.resolve("pdf") = mineru
-> save original
-> enqueue RQ process_deferred_document_job(doc_id)
-> status parse_pending with processing_job_id
-> return doc_id/artifact_dir/status/processing_job_id
```

worker 后续:

```text
python -m app.workers.document_processing_worker
-> process_deferred_document_job(doc_id)
-> process_deferred_document(doc_id)
-> mineru_parser_adapter.parse_document()
-> artifact manifest
-> index_pending
-> vector_index_service.index_document_record()
-> prepare_artifacts_for_index(doc_id)
-> ArtifactChunkBuilderService.prepare()
-> indexed / index_failed
```

---

### 十一、关键设计亮点

1. **接入编排清晰**: 上传、路由、状态、索引入口统一由一个 service 协调。
2. **复杂文档异步解析**: MinerU 文档上传后先入队，成功后只确认到带队列证据的 `parse_pending`，真正解析和索引由 RQ worker 推进。
3. **状态可追踪且有证据**: 每个阶段都落到 `DocumentStatus`，并通过 `status_source/status_detail/status_evidence/status_confirmed_at` 说明状态为什么成立。
4. **索引前严格校验**: 先 validate manifest，再 chunk builder。
5. **异常边界明确**: 记录失败状态后重新抛给调用方。

---

### 十二、边界与风险

- API 层现在不再维护扩展名白名单；文件名清洗、类型判断与 parser 路由统一收敛到 `DocumentIngestionService` / `parser_engine_router`。
- production upload 必须传 `kb_id`；如果旧脚本没跟上，会在 API 边界直接失败。
- RQ 版异步依赖 Redis 和独立 worker。Redis/RQ 投递失败时，`ingest_upload()` 会把已落盘文档更新为 `enqueue_failed` 并继续抛错，避免文档静默停在无人消费的 `parse_pending`；如果只是 worker 暂时没启动，任务通常会保留在 Redis 队列里，等 worker 启动后再消费。
- crash consistency 仍不是完整两阶段提交: 如果 RQ enqueue 已经返回、但 `parse_pending` job evidence 还没写库时进程崩溃，Redis 里可能已有任务而 DB 仍停在 `uploaded`。彻底解决需要 outbox / reconciliation，不属于当前最小修正。
- 当前选择 RQ 是最小可靠队列，不是 Celery 级编排；如果后续需要复杂 retry policy、任务编排、监控面板，再升级任务系统。

---

### 十三、面试里怎么讲

可以讲成:

> DocumentIngestionService 是文档接入编排层。它负责生成 doc_id、保存原件、创建 DocumentRecord、选择 parser、推进状态流。plain_text 会先进入 parse_pending，再直接交给索引服务推进到 INDEX_PENDING/INDEXING/INDEXED；MinerU 文档上传时由 ingest_upload 内部投递 RQ/Redis 任务，投递成功后才把 parse_pending 的证据补齐为 processing_job_id/processing_queue/enqueued_at，worker 调用 process_deferred_document_job，内部复用 process_deferred_document 做解析，解析到 index_pending 后再调用 vector_index_service 完成索引。每次状态写入都带状态证据，artifact 准备、入队或索引失败会落库为精确失败状态并继续抛异常，交给调用方和队列层处理失败与重试策略。

---

## 4. [app/services/artifact_manifest_service.py](../app/services/artifact_manifest_service.py)

这个文件实现了**解析产物清单服务（Artifact Manifest Service）**，负责创建和校验 MinerU 解析后的 artifact contract。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

P2 之后，复杂文档不会直接进入向量化，而是先由 MinerU 产出固定 artifact。

`artifact_manifest_service.py` 的作用是把 artifact 从“目录约定”变成“可校验 contract”。

它解决的问题:

- 下游不再猜 `chunks.json`、`tables.json` 在哪里。
- 缺少关键文件时不允许继续索引。
- parser 产物状态不是 `parsed` 时不允许继续。
- manifest 中记录 schema、parser、postprocess 版本，便于后续排查。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `json` | manifest JSON 读写 |
| `Path` | artifact 路径处理 |
| `ArtifactManifest` | manifest 的 Pydantic 模型 |
| `DocumentRecord` | 从文档记录构建 manifest |

---

### 二、核心类: `ArtifactManifestService`

#### 1. 类作用

这个类提供三类能力:

1. 根据 `DocumentRecord` 构建 manifest。
2. 写入 `artifact_manifest.json`。
3. 加载并校验 artifact 必需文件。

#### 2. 常量定义

```python
MANIFEST_FILENAME = "artifact_manifest.json"
SCHEMA_VERSION = "artifact_manifest_v1"
POSTPROCESS_VERSION = "pdf_eval_mineru_postprocess_v1"
```

这些常量让 manifest 有版本边界。

`REQUIRED_FILES`:

```python
REQUIRED_FILES = {
    "cleaned_md": "cleaned.md",
    "chunks_json": "chunks.json",
    "tables_json": "tables.json",
    "blocks_json": "blocks.json",
    "quality_report_json": "quality_report.json",
}
```

必需文件解释:

| key | 文件 | 作用 |
|---|---|---|
| `cleaned_md` | `cleaned.md` | 人类可读清洗稿 |
| `chunks_json` | `chunks.json` | 正文 chunk 入库主输入 |
| `tables_json` | `tables.json` | 表格 chunk 入库主输入 |
| `blocks_json` | `blocks.json` | 调试和 QA 参考 |
| `quality_report_json` | `quality_report.json` | 质量报告和 fatal errors |

---

### 三、核心方法 1: `build_manifest`

```python
def build_manifest(self, document_record: DocumentRecord) -> ArtifactManifest:
```

作用: 从 `DocumentRecord` 生成 `ArtifactManifest`。

核心字段:

```python
schema_version=self.SCHEMA_VERSION
kb_id=document_record.kb_id
doc_id=document_record.doc_id
source_file=document_record.original_path
artifact_dir=document_record.artifact_dir
parser_engine=document_record.parser_engine
parser_version=document_record.parser_version or ""
postprocess_version=self.POSTPROCESS_VERSION
status="parsed"
required_files=dict(self.REQUIRED_FILES)
created_at=document_record.updated_at or document_record.created_at
```

这里有几个重点:

- `source_file` 来自原始文件路径。
- `artifact_dir` 来自文档记录，不由 service 自己猜。
- `parser_engine` 和 `parser_version` 记录解析来源。
- `required_files` 明确下游必须看到哪些文件。
- `status` 固定为 `parsed`，校验时会检查。

---

### 四、核心方法 2: `write_manifest`

```python
def write_manifest(self, document_record: DocumentRecord) -> Path:
```

作用: 写入 `artifact_manifest.json`。

核心流程:

```text
artifact_dir.mkdir()
-> build_manifest()
-> path = artifact_dir / artifact_manifest.json
-> json.dumps(..., ensure_ascii=False, indent=2)
-> return path
```

为什么使用 `ensure_ascii=False`?

因为解析报告、文件名、错误信息可能包含中文，保持 JSON 可读。

---

### 五、核心方法 3: `load_manifest`

```python
def load_manifest(self, artifact_dir: str | Path) -> ArtifactManifest:
```

作用: 从 artifact 目录读取 manifest。

逻辑:

1. 拼出 `artifact_manifest.json` 路径。
2. 如果不存在，抛 `FileNotFoundError`。
3. 读取 JSON。
4. 用 `ArtifactManifest.model_validate(payload)` 做模型校验。

设计意义:

- manifest 不是随便 dict，而是 Pydantic 模型。
- 字段缺失或类型错误会在模型校验时暴露。

---

### 六、核心方法 4: `validate_manifest`

```python
def validate_manifest(self, artifact_dir: str | Path) -> ArtifactManifest:
```

作用: 校验 artifact 是否满足索引前置条件。

核心逻辑:

```python
manifest = self.load_manifest(base)
if manifest.status != "parsed":
    raise ValueError(...)

for key, relative_path in manifest.required_files.items():
    target = base / relative_path
    if not target.exists():
        raise FileNotFoundError(...)

return manifest
```

校验分两层:

1. manifest 状态必须是 `parsed`。
2. `required_files` 中每个文件都必须存在。

---

### 七、典型调用流程

#### 1. MinerU 解析完成后

```text
MinerUParserAdapter.parse_document()
-> artifact_manifest_service.write_manifest(parsed_record)
-> artifact_manifest_service.validate_manifest(parsed_record.artifact_dir)
```

#### 2. 索引前校验

```text
DocumentIngestionService.validate_artifacts_for_index(doc_id)
-> artifact_manifest_service.validate_manifest(artifact_dir)
```

#### 3. ChunkBuilder 准备

```text
prepare_artifacts_for_index()
-> validate_manifest()
-> artifact_chunk_builder_service.prepare(document_record, manifest)
```

---

### 八、关键设计亮点

1. **显式 contract**: artifact 文件不靠口头约定。
2. **失败前置**: 缺文件时在索引前失败。
3. **版本可追踪**: schema、parser、postprocess 都有版本字段。
4. **下游解耦**: ChunkBuilder 通过 manifest 找文件，不硬编码临时路径。
5. **状态门禁**: `status != parsed` 不能继续。

---

### 九、边界与风险

- 当前只检查文件是否存在，没有检查每个 JSON 文件的 schema 内容，这部分由 `ArtifactChunkBuilderService` 继续校验。
- manifest 的 `status` 当前固定写 `parsed`，如果后续 parser 有 partial success，需要扩展状态语义。
- `cleaned.md` 是必需文件，但不是索引主输入，读者不要误解它的职责。
- 真正值得后续做的是一个独立小阶段：artifact schema hardening，到时候再统一定义 chunks/tables/quality_report/blocks 的严格 schema 和测试。

---

### 十、面试里怎么讲

可以讲成:

> 我把 MinerU 解析产物做成 artifact manifest contract。Parser 解析完成后必须声明 cleaned.md、chunks.json、tables.json、blocks.json、quality_report.json。索引前先校验 manifest 状态和必需文件，缺件直接失败，避免 indexer 猜路径或把不完整产物写进向量库。

---

## 5. [app/services/artifact_chunk_builder_service.py](../app/services/artifact_chunk_builder_service.py)

这个文件实现了**Artifact 到索引输入的适配器（Artifact Chunk Builder Service）**，把 MinerU 产出的 `chunks.json` 和 `tables.json` 转换成可写入 Milvus 和 metadata store 的结构化对象。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`artifact_chunk_builder_service.py` 是 P2-5 的核心。

它处在:

```text
ArtifactManifestService
-> ArtifactChunkBuilderService
-> VectorIndexService
```

之间。

它解决的问题:

- Parser 产出的 JSON 格式不能直接写 Milvus。
- 正文 chunk 和表格 chunk 要统一成 `ChunkRecord`。
- 每个 chunk 必须补齐 `SourceRef`，否则后续 citation 断掉。
- `cleaned.md` 不能误用为索引主输入。
- `quality_report.fatal_errors` 必须阻止入库。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `json` | 读取 artifact JSON |
| `dataclass` | 定义轻量返回对象 `PreparedIndexArtifacts` |
| `Path` | 拼接 artifact 文件路径 |
| `Any` | 处理 JSON payload |
| `Document` | LangChain 文档对象，用于向量库写入 |
| `ArtifactManifest` | manifest 声明 |
| `ChunkRecord` | 结构化 chunk |
| `DocumentRecord` | 文档身份 |
| `SourceRef` | citation 来源身份 |

---

### 二、核心数据类: `PreparedIndexArtifacts`

```python
@dataclass
class PreparedIndexArtifacts:
    document_record: DocumentRecord
    manifest: ArtifactManifest
    documents: list[Document]
    chunk_records: list[ChunkRecord]
    quality_report: dict[str, Any]
```

这个对象是 `prepare()` 的返回值。

字段解释:

| 字段 | 用途 |
|---|---|
| `document_record` | 原始文档身份 |
| `manifest` | 解析产物声明 |
| `documents` | 写入 Milvus 的 LangChain Document |
| `chunk_records` | 写入 metadata store 的结构化 ChunkRecord |
| `quality_report` | 质量报告，用于审计或后续判断 |

设计重点:

- 一次准备同时产出向量库输入和 metadata store 输入。
- Milvus 和 metadata store 使用同一批 chunk 身份。

---

### 三、核心类: `ArtifactChunkBuilderService`

#### 1. 类作用

这个类只做一件事:

```text
把已经校验过 manifest 的 parsed artifacts 转成 index-ready chunks。
```

它不执行 parser，不写 Milvus，也不生成最终答案。

---

### 四、核心方法 1: `prepare`

```python
def prepare(
    self,
    document_record: DocumentRecord,
    manifest: ArtifactManifest,
) -> PreparedIndexArtifacts:
```

#### 输入参数

| 参数 | 含义 |
|---|---|
| `document_record` | 当前文档记录 |
| `manifest` | 已校验的 artifact manifest |

#### 核心逻辑

##### 步骤 1: 从 manifest 找文件

```python
artifact_dir = Path(document_record.artifact_dir)
chunks_payload = self._load_json_list(artifact_dir / manifest.required_files["chunks_json"])
tables_payload = self._load_json_list(artifact_dir / manifest.required_files["tables_json"])
quality_report = self._load_json_object(
    artifact_dir / manifest.required_files["quality_report_json"]
)
```

注意: 路径来自 manifest，不是硬编码临时目录。

##### 步骤 2: fatal errors 拦截

```python
self._raise_for_fatal_quality_errors(quality_report)
```

如果 `quality_report.fatal_errors` 非空，直接拒绝入库。

##### 步骤 3: 构建正文 chunk

```python
for raw_chunk in chunks_payload:
    chunk_record = self._build_text_chunk_record(...)
    documents.append(Document(page_content=chunk_record.content, metadata=dict(chunk_record.metadata)))
```

每条正文 chunk 同时生成:

- `ChunkRecord`
- LangChain `Document`

##### 步骤 4: 构建表格 chunk

```python
for raw_table in tables_payload:
    chunk_record = self._build_table_chunk_record(...)
```

表格和正文走同一套 `ChunkRecord` 模型，但 `content_type` 和 chunk_id 规则不同。

##### 步骤 5: 返回准备结果

```python
return PreparedIndexArtifacts(...)
```

---

### 五、核心方法 2: `_build_text_chunk_record`

```python
def _build_text_chunk_record(...)
```

作用: 把 `chunks.json` 的单条记录转成 `ChunkRecord`。

#### 关键字段读取

```python
local_id = self._required_str(raw_chunk, ["chunk_id", "id"], "chunk_id")
content = self._required_str(raw_chunk, ["content", "text"], "content")
```

兼容两种字段名:

- `chunk_id` 或 `id`
- `content` 或 `text`

这样能适配不同 postprocess 输出形态。

#### chunk_id 规范化

```python
chunk_id = self._normalize_chunk_id(document_record.doc_id, local_id)
```

如果 local id 是 `c00001`，最终变成:

```text
doc_id:c00001
```

#### 页码和标题

```python
pages = raw_chunk.get("pages") if isinstance(raw_chunk.get("pages"), list) else []
page_start = raw_chunk.get("page_start", min(pages) if pages else None)
page_end = raw_chunk.get("page_end", max(pages) if pages else None)
heading_path = self._list_or_empty(raw_chunk.get("heading_path"))
```

页码来源优先级:

1. 显式 `page_start/page_end`。
2. `pages` 数组的最小值和最大值。
3. 没有页码则为 `None`。

#### source_ref 构建

```python
source_ref = self._build_source_ref(...)
```

这是后续 citation 的核心。

#### metadata 构建

```python
metadata = self._base_metadata(...)
metadata.update({
    "artifact_source": "chunks_json",
    "raw_chunk_id": local_id,
    "block_ids": ...,
    "block_types": ...,
})
```

`artifact_source="chunks_json"` 说明这条 chunk 来自正文 artifact。

---

### 六、核心方法 3: `_build_table_chunk_record`

```python
def _build_table_chunk_record(...)
```

作用: 把 `tables.json` 的单条表格记录转成 `ChunkRecord`。

#### 表格 ID

```python
table_id = self._required_str(raw_table, ["table_id", "id"], "table_id")
chunk_id = self._normalize_table_chunk_id(document_record.doc_id, table_id)
```

表格 chunk_id 规范:

```text
doc_id:table:table_id
```

这样可以避免正文 chunk `doc_id:c00001` 和表格 chunk 冲突。

#### 表格内容

```python
content = self._required_str(raw_table, ["display_text", "markdown"], "markdown")
```

优先用 `display_text`，否则用 `markdown`。

#### 表格 metadata

```python
metadata.update({
    "artifact_source": "tables_json",
    "table_id": table_id,
    "classification": raw_table.get("classification", ""),
    "structured_payload": {
        "rows": raw_table.get("rows", []),
        "caption": raw_table.get("caption", []),
        "quality_flags": quality_flags,
    },
})
```

表格额外保留:

- 表格 ID。
- 分类。
- 行列结构。
- caption。
- quality flags。

这让后续不只是能检索表格文本，还能追溯表格结构。

---

### 七、核心方法 4: `_base_metadata`

```python
def _base_metadata(...) -> dict[str, Any]:
```

这是全文件最关键的方法之一。

它写入:

```python
{
    "kb_id": document_record.kb_id,
    "doc_id": document_record.doc_id,
    "chunk_id": chunk_id,
    "_source": document_record.original_path,
    "_file_name": document_record.file_name,
    "_extension": f".{document_record.file_ext}",
    "content_type": content_type,
    "page_start": page_start,
    "page_end": page_end,
    "heading_path": heading_path,
    "parser_engine": document_record.parser_engine.value,
    "source_ref": source_ref.model_dump(mode="json"),
    "quality_flags": quality_flags,
}
```

这批字段会进入:

```text
LangChain Document.metadata
-> Milvus metadata
-> RetrievalService._build_source_ref()
-> RetrievalResult.citation_text
```

也就是说，citation 的基础是在这里写进去的。

---

### 八、核心方法 5: `_build_source_ref`

```python
def _build_source_ref(...) -> SourceRef:
```

它把当前 chunk 的身份统一成 `SourceRef`:

```python
SourceRef(
    kb_id=document_record.kb_id,
    doc_id=document_record.doc_id,
    chunk_id=chunk_id,
    source_file=document_record.file_name,
    page_start=page_start,
    page_end=page_end,
    heading_path=heading_path,
    content_type=content_type,
    parser_engine=document_record.parser_engine,
)
```

后面 retrieval 不再需要猜来源，只要从 metadata 里恢复 `source_ref`。

---

### 九、辅助校验方法

#### 1. `_load_json_list`

要求 JSON 顶层必须是 list，且每个元素必须是 object。

用于:

- `chunks.json`
- `tables.json`

#### 2. `_load_json_object`

要求 JSON 顶层必须是 object。

用于:

- `quality_report.json`

#### 3. `_raise_for_fatal_quality_errors`

```python
fatal_errors = quality_report.get("fatal_errors") or []
if fatal_errors:
    raise ValueError(...)
```

这防止严重解析错误继续入库。

#### 4. `_required_str`

从多个候选 key 中找一个非空字符串。

找不到就抛:

```text
<contract_name> is required
```

这是 contract adapter 的字段级校验。

---

### 十、典型调用流程

```text
DocumentIngestionService.prepare_artifacts_for_index(doc_id)
-> artifact_manifest_service.validate_manifest()
-> artifact_chunk_builder_service.prepare(document_record, manifest)
-> load chunks.json / tables.json / quality_report.json
-> build text ChunkRecord
-> build table ChunkRecord
-> return PreparedIndexArtifacts
-> VectorIndexService 写入 Milvus 和 metadata store
```

---

### 十一、关键设计亮点

1. **只消费契约文件**: 不读 `cleaned.md` 作为主输入。
2. **正文和表格统一建模**: 都变成 `ChunkRecord`。
3. **source_ref 在入库前生成**: citation 不依赖回答阶段临时拼。
4. **质量报告前置拦截**: fatal errors 不允许进入索引。
5. **兼容字段名差异**: 支持 `id/chunk_id`、`text/content`。
6. **metadata 完整**: 同时支持旧 `_source` 字段和新 `doc_id/chunk_id/source_ref`。

---

### 十二、边界与风险

- 当前表格内容主要用 markdown/display_text，复杂表格结构没有单独向量化策略。
- `quality_report.warnings` 不阻止入库，只拦截 `fatal_errors`。
- `start_index/end_index` 对 artifact chunk 是按 cursor 累积，不等价于原 PDF 字符 offset。

---

### 十三、面试里怎么讲

可以讲成:

> ArtifactChunkBuilderService 是 parser 和 indexer 之间的 contract adapter。它只读取 chunks.json 和 tables.json，不用 cleaned.md 做索引主输入。它把正文和表格都转成 ChunkRecord，并在入库前生成 source_ref 和 metadata，所以后续 retrieval 能稳定返回 doc_id、chunk_id、页码、章节和 citation。

---

## 6. [app/services/vector_index_service.py](../app/services/vector_index_service.py)

这个文件实现了**向量索引服务（Vector Index Service）**，负责把 plain-text 文档或 MinerU artifact 转成向量库记录和 metadata store 记录。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`vector_index_service.py` 是文档进入可检索状态的最后写入层。

它负责:

- 兼容旧目录索引入口，并委托给正式接入层。
- 单文件索引。
- `DocumentRecord` 索引。
- plain_text 文档切分。
- MinerU prepared artifacts 写入。
- `doc_id` 幂等清理。
- 写 Milvus。
- 写 `KnowledgeMetadataStore`。

它不负责:

- 选择 parser 的规则来源，交给 `ParserEngineRouter`。
- 执行 MinerU CLI，交给 `MinerUParserAdapter`。
- 组装 citation，交给 `RetrievalService`。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `datetime` | 记录索引开始/结束、更新 document 状态 |
| `hashlib` | legacy source hash |
| `Path` | 文件路径处理 |
| `uuid5/NAMESPACE_URL` | legacy 路径生成稳定 doc_id |
| `logger` | 记录索引过程 |
| `Document` | LangChain 文档对象 |
| `ChunkRecord/DocumentRecord/DocumentStatus/ParserEngine/SourceRef` | 知识库领域模型 |
| `document_splitter_service` | md/txt 切分 |
| `knowledge_metadata_store` | 保存 document/chunk 状态 |
| `parser_engine_router` | 单文件索引时选择 parser |
| `vector_store_manager` | 写入和清理 Milvus |

---

### 二、辅助模型: `DirectoryIngestionResult`

#### 1. 类作用

`DirectoryIngestionResult` 是目录批量接入的结果对象，定义在 `app/models/ingestion.py`。它归属 ingestion model，不再在 `VectorIndexService` 里保留额外兼容别名。

字段:

```text
success
directory_path
total_files
success_count
fail_count
start_time
end_time
error_message
failed_files
```

它主要服务 `DocumentIngestionService.ingest_directory()`，用于 worker / API 返回批量接入结果。

#### 2. 关键方法

| 方法 | 作用 |
|---|---|
| `increment_success_count()` | 成功计数 +1 |
| `increment_fail_count()` | 失败计数 +1 |
| `add_failed_file()` | 记录失败文件和错误 |
| `get_duration_ms()` | 计算耗时 |
| `to_dict()` | 转成 API 可返回 dict |

---

### 三、核心类: `VectorIndexService`

#### 1. 初始化方法

```python
def __init__(self):
    logger.info("向量索引服务初始化完成")
```

这里不再保存目录接入配置。知识库归属必须从入口显式传入 `kb_id`，不再由 `VectorIndexService` 内部硬编码 `default_kb_id`。

---

### 四、核心方法 1: `index_single_file`

```python
def index_single_file(self, file_path: str, kb_id: str):
```

作用: 索引单个文件，主要服务 eval helper 和少量便捷调用；调用方必须显式给出 `kb_id`。

核心流程:

```text
Path(file_path).resolve()
-> 文件存在校验
-> _build_doc_id(kb_id, path)
-> parser_engine_router.resolve_path(path)
-> _build_document_record(...)
-> index_document_record(document_record)
```

设计意义:

- 旧接口仍然可用。
- 旧接口也会进入 `DocumentRecord` 和 parser router。
- 不再完全绕过 P1/P2 的领域对象层。

失败时:

```python
knowledge_metadata_store.transition_document_status(
    doc_id,
    DocumentStatus.INDEX_FAILED,
    status_source="VectorIndexService.index_single_file",
    status_detail="legacy single-file indexing failed",
    status_evidence={"file_path": str(path), "error_type": type(e).__name__},
    error_message=str(e),
)
raise RuntimeError(...)
```

---

### 六、核心方法 3: `index_document_record`

```python
def index_document_record(self, document_record: DocumentRecord):
```

这是正式索引入口。

#### 步骤 1: 文件存在校验

```python
path = Path(document_record.original_path).resolve()
if not path.exists() or not path.is_file():
    raise ValueError(...)
```

#### 步骤 2: parser 分支

```python
if document_record.parser_engine == ParserEngine.MINERU:
    self._index_mineru_document_record(document_record)
    return

if document_record.parser_engine != ParserEngine.PLAIN_TEXT:
    raise ValueError(...)
```

这里体现两个路径:

- `mineru`: 读取已准备 artifact。
- `plain_text`: 读取原文本并切分。

#### 步骤 3: plain_text 索引

```python
content = path.read_text(encoding="utf-8")
documents = document_splitter_service.split_document(content, normalized_path)
chunk_records = self._build_chunk_records(...)
```

这一步把 md/txt 变成:

- LangChain `Document`。
- `ChunkRecord`。

#### 步骤 4: 清理旧数据

```python
self._transition_document_status(
    doc_id,
    DocumentStatus.INDEXING,
    status_source="VectorIndexService.index_document_record",
    status_detail="plain-text chunks were prepared and vector write is starting",
    status_evidence={"vector_document_count": len(documents)},
)
self._cleanup_existing_document_data(document_record)
```

写新数据前先清理，保证幂等。

#### 步骤 5: 写入 Milvus 和 metadata store

```python
vector_store_manager.add_documents(documents)
knowledge_metadata_store.replace_chunks(doc_id, chunk_records)
self._transition_document_status(..., DocumentStatus.INDEXED, status_evidence={...})
```

如果 documents 为空，也会把文档标成 `indexed`，并记录 warning。

#### 失败处理

```python
knowledge_metadata_store.transition_document_status(
    document_record.doc_id,
    DocumentStatus.INDEX_FAILED,
    status_source="VectorIndexService.index_document_record",
    status_detail="document indexing failed before completion",
    status_evidence={
        "parser_engine": document_record.parser_engine.value,
        "error_type": type(e).__name__,
    },
    error_message=str(e),
)
raise
```

---

### 七、核心方法 4: `_index_mineru_document_record`

```python
def _index_mineru_document_record(self, document_record: DocumentRecord) -> None:
```

作用: 从已校验 artifact 中索引 MinerU 文档。

核心流程:

```text
upsert document
-> status INDEXING
-> DocumentIngestionService().prepare_artifacts_for_index(doc_id)
-> get documents / chunk_records
-> cleanup old data
-> vector_store_manager.add_documents()
-> knowledge_metadata_store.replace_chunks()
-> status INDEXED
```

关键点:

- MinerU 索引不读 `cleaned.md`。
- 它消费的是 `ArtifactChunkBuilderService` 准备好的 `documents` 和 `chunk_records`。
- plain_text 和 mineru 最终都走同样的写入动作。

读源码时要注意:

```python
from app.services.document_ingestion_service import DocumentIngestionService
prepared = DocumentIngestionService().prepare_artifacts_for_index(doc_id)
```

这里临时实例化了 `DocumentIngestionService`。当前测试和流程可用，但如果未来做依赖注入，可以优化为显式注入或使用全局单例。

---

### 八、核心方法 5: `_cleanup_existing_document_data`

```python
def _cleanup_existing_document_data(self, document_record: DocumentRecord) -> None:
```

这是 P2-6 幂等清理的核心。

执行顺序:

```python
deleted_chunk_count = knowledge_metadata_store.delete_chunks_by_doc_id(doc_id)
_ = vector_store_manager.delete_by_doc_id(doc_id)
_ = vector_store_manager.delete_by_source(normalized_source)
```

它清理三类旧数据:

| 清理目标 | 作用 |
|---|---|
| metadata store old chunks | 删除同一 doc_id 的旧 ChunkRecord |
| Milvus rows by doc_id | 删除新链路写入的旧向量 |
| Milvus rows by `_source` | 删除 legacy 路径残留向量 |

这个方法解决的问题:

```text
同一文档重复索引时，不留下旧 chunk 和旧 vector row。
```

---

### 九、核心方法 6: `_build_chunk_records`

```python
def _build_chunk_records(...)
```

作用: 把 plain_text 切分结果转成 `ChunkRecord`。

核心逻辑:

1. `_locate_chunk_offsets()` 定位 chunk 在原文中的 offset。
2. `_extract_heading_path()` 从 metadata 中取 `h1/h2/h3`。
3. 构造稳定 chunk_id:

```text
<doc_id>:c00000
<doc_id>:c00001
```

4. 判断 content_type:

```python
content_type = "markdown_section" if file_ext == ".md" else "text"
```

5. 构造 `SourceRef`。
6. 把 citation 字段写入 `document.metadata`。
7. 构造 `ChunkRecord`。

关键 metadata:

```python
"kb_id": kb_id
"doc_id": doc_id
"chunk_id": chunk_id
"content_type": content_type
"parser_engine": parser_engine.value
"heading_path": heading_path
"page_start": None
"page_end": None
"quality_flags": []
"source_ref": source_ref.model_dump(mode="json")
```

这让 md/txt 旧链路也能获得 citation 所需字段。

---

### 十、典型调用流程

#### 1. legacy Markdown 文件索引

```text
index_single_file("cpu_high_usage.md", kb_id="default")
-> build doc_id
-> resolve_path() = plain_text
-> build DocumentRecord
-> index_document_record()
-> split_document()
-> _build_chunk_records()
-> _write_vector_documents()
-> prepare_documents()
-> _cleanup_existing_document_data()
-> add_prepared_documents()
-> knowledge_metadata_store.replace_chunks()
-> status indexed
```

#### 2. MinerU 文档索引

```text
index_document_record(mineru_doc)
-> _index_mineru_document_record()
-> prepare_artifacts_for_index()
-> ArtifactChunkBuilderService.prepare()
-> _write_vector_documents()
-> prepare_documents()
-> _cleanup_existing_document_data()
-> add_prepared_documents()
-> replace_chunks()
-> status indexed
```

---

### 十一、关键设计亮点

1. **统一索引入口**: plain_text 和 mineru 都进入 `index_document_record()`。
2. **保留单文件便捷入口**: `index_single_file()` 仍可用，但要求显式 `kb_id`。
3. **幂等清理**: 写入前清理 doc_id 和 legacy `_source`。
4. **metadata/citation 接线**: plain_text 也生成 `SourceRef`。
5. **失败状态落库**: 索引异常会更新 `index_failed`。

---

### 十二、边界与风险

- 目录接入不再属于 `VectorIndexService`；真实目录入口是 `DocumentIngestionService.ingest_directory()`，API worker 也直接走这个入口。进度百分比、暂停、取消仍是后续 batch job 能力。
- `_index_mineru_document_record()` 临时创建 `DocumentIngestionService()`，未来可以考虑依赖注入。
- 文档为空时仍会标记 indexed，这适合兼容当前行为，但后续如果要质量门禁，可以细化状态。

---

### 十三、面试里怎么讲

可以讲成:

> VectorIndexService 是最终入库层。plain_text 会先切分，mineru 会先消费 prepared artifacts，但最终都变成 LangChain Documents 和 ChunkRecords。写入前我会按 doc_id 清理 metadata 和 Milvus 旧数据，同时清理 legacy `_source` 残留，保证重复索引不会产生脏数据。

---

## 7. [app/services/retrieval_service.py](../app/services/retrieval_service.py)

这个文件实现了**带 citation 的检索证据组装服务（Citation-aware Retrieval Service）**，负责把底层检索 hit 转换成结构化 `RetrievalResult`。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`retrieval_service.py` 是 P2-7 的核心。

它解决的问题是:

- 向量检索返回的 raw hit 只是内容、分数、metadata。
- RAG 需要可追溯来源，不只是文本。
- dense、hybrid、rerank 最终都必须返回统一 evidence。
- 没有稳定 `doc_id/chunk_id/source_ref` 的结果不应进入 citation 结果。

它不负责:

- BM25 计算。
- RRF 融合。
- rerank 排序。
- LLM 生成最终回答。

它只负责:

```text
raw hits -> RetrievalResult / RetrievalResponse
```

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `json` | 解析 metadata 中的 JSON 字符串 |
| `Any/Dict/Iterable/List` | 类型注解 |
| `logger` | 记录检索与异常 hit |
| `ParserEngine` | 恢复 source_ref 中的 parser engine |
| `RetrievalMode` | 判断 dense 还是 hybrid 路径 |
| `RetrievalQuery` | 检索请求 |
| `RetrievalResponse` | 检索响应 |
| `RetrievalResult` | 单条结构化检索结果 |
| `SourceRef` | citation 来源对象 |
| `hybrid_search_service` | 非 dense-only 模式的召回 |
| `vector_search_service` | dense-only 召回 |
| `RawSearchResult` | 底层 SearchResult 类型别名 |

---

### 二、核心类: `RetrievalService`

#### 1. 类作用

`RetrievalService` 对外提供一个主要入口:

```python
retrieve(query: RetrievalQuery) -> RetrievalResponse
```

输入是结构化 query，输出是结构化 response。

#### 2. 空结果常量

```python
EMPTY_MESSAGE = "没有找到相关信息。"
```

统一空结果消息，避免每个调用方自己拼。

---

### 三、核心方法 1: `retrieve`

```python
def retrieve(self, query: RetrievalQuery) -> RetrievalResponse:
```

#### 输入参数

`RetrievalQuery` 包含:

- `query`: 查询文本。
- `top_k`: 返回数量。
- `retrieval_mode`: 检索模式。
- `knowledge_base_ids`: 可选知识库过滤。

#### 核心逻辑

##### 步骤 1: 根据 retrieval mode 选择召回路径

```python
if query.retrieval_mode == RetrievalMode.DENSE_ONLY:
    raw_hits = vector_search_service.search_similar_documents(query.query, top_k=query.top_k)
else:
    raw_hits = hybrid_search_service.search(query)
```

注意:

- dense-only 直接走向量检索。
- sparse-only、hybrid、hybrid-rerank 都走 `HybridSearchService`。

##### 步骤 2: raw hits 转结构化结果

```python
results = self._build_results(raw_hits, query)
```

##### 步骤 3: 构造模型上下文

```python
context_text = self._format_context(results)
if not results:
    context_text = self.EMPTY_MESSAGE
```

##### 步骤 4: 返回 RetrievalResponse

```python
return RetrievalResponse(
    query=query,
    results=results,
    context_text=context_text,
    empty_message=self.EMPTY_MESSAGE,
)
```

---

### 四、核心方法 2: `_build_results`

```python
def _build_results(
    self,
    raw_hits: Iterable[RawSearchResult],
    query: RetrievalQuery,
) -> List[RetrievalResult]:
```

作用: 把底层 `SearchResult` 转成 `RetrievalResult`。

#### 步骤 1: 知识库过滤准备

```python
allowed_kb_ids = set(query.knowledge_base_ids)
```

如果 query 指定了知识库，则只保留这些 KB 的命中。

#### 步骤 2: 规范化 metadata

```python
metadata = self._normalize_metadata(hit.metadata)
```

metadata 可能是 dict，也可能是 JSON 字符串。这里统一成 dict。

#### 步骤 3: 构造 SourceRef

```python
source_ref = self._build_source_ref(metadata)
kb_id = source_ref.kb_id or metadata.get("kb_id", "")
```

这里优先从 metadata 的 `source_ref` 恢复完整来源。

#### 步骤 4: 可选 KB 过滤

```python
if allowed_kb_ids and kb_id not in allowed_kb_ids:
    continue
```

#### 步骤 5: 稳定字段检查

```python
doc_id = metadata.get("doc_id", source_ref.doc_id)
chunk_id = metadata.get("chunk_id", hit.id)
content = hit.content or metadata.get("content", "")
if not kb_id or not doc_id or not chunk_id or not source_ref.source_file:
    logger.warning(...)
    continue
```

如果缺少稳定引用字段，直接跳过。

这保证 `RetrievalResult` 不是“有文本但无来源”的不完整证据。

#### 步骤 6: 分数处理

```python
score = float(hit.score) if hit.score is not None else None
if score is not None and "recall_score" not in metadata:
    metadata["recall_score"] = score
```

如果 metadata 中没有 recall_score，则用当前 hit.score 兜底。

#### 步骤 7: citation 文本

```python
citation_text = self._build_citation_text(source_ref, chunk_id)
```

#### 步骤 8: 构造 RetrievalResult

```python
RetrievalResult(
    kb_id=kb_id,
    doc_id=doc_id,
    chunk_id=chunk_id,
    content=content,
    score=score,
    source_ref=source_ref,
    citation_text=citation_text,
    metadata=metadata,
)
```

---

### 五、核心方法 3: `_normalize_metadata`

```python
def _normalize_metadata(self, metadata: Dict[str, Any] | Any) -> Dict[str, Any]:
```

作用: 把 metadata 统一成 dict。

支持:

- dict: 原样返回。
- str: 尝试 `json.loads`。
- 其他: 返回空 dict。

设计意义:

- 兼容不同 vector store 返回形式。
- 避免后续 `_build_source_ref()` 处理类型混乱。

---

### 六、核心方法 4: `_build_source_ref`

```python
def _build_source_ref(self, metadata: Dict[str, Any]) -> SourceRef:
```

作用: 从 metadata 恢复 `SourceRef`。

#### source_ref 优先

```python
source_ref_payload = metadata.get("source_ref")
```

如果是 dict，直接使用。

如果是 JSON 字符串，尝试解析。

如果没有，则从旧 metadata 字段补。

#### 兜底字段

```python
payload.setdefault("kb_id", metadata.get("kb_id", ""))
payload.setdefault("doc_id", metadata.get("doc_id", ""))
payload.setdefault("chunk_id", metadata.get("chunk_id", ""))
payload.setdefault("source_file", metadata.get("_file_name", metadata.get("source_file", "")))
payload.setdefault("page_start", metadata.get("page_start"))
payload.setdefault("page_end", metadata.get("page_end"))
payload.setdefault("heading_path", metadata.get("heading_path", []))
payload.setdefault("content_type", metadata.get("content_type", "text"))
```

这体现兼容策略:

- 新链路优先用 `source_ref`。
- 旧链路可以从 `_file_name`、`doc_id`、`chunk_id` 等字段恢复。

#### parser_engine 处理

```python
parser_engine_value = payload.get("parser_engine", metadata.get("parser_engine", "plain_text"))
try:
    payload["parser_engine"] = ParserEngine(parser_engine_value)
except Exception:
    payload["parser_engine"] = ParserEngine.PLAIN_TEXT
```

如果 parser_engine 不合法，兜底为 `plain_text`。

---

### 七、核心方法 5: `_build_citation_text`

```python
def _build_citation_text(self, source_ref: SourceRef, chunk_id: str) -> str:
```

作用: 生成展示用 citation。

拼接规则:

1. 如果有 `source_file`，加入来源。
2. 如果有页码，加入页码。
3. 如果有标题路径，加入章节。
4. 如果有 chunk_id，加入 chunk。

示例:

```text
[来源: manual.pdf, 页码: 2-3, 章节: 第一章 > 概述, chunk: doc_pdf:c00001]
```

注意: citation_text 是展示字段，真正可机器校验的是 `source_ref`。

---

### 八、核心方法 6: `_format_context`

```python
def _format_context(self, results: List[RetrievalResult]) -> str:
```

作用: 把结构化结果转成 LLM 可读上下文。

格式类似:

```text
【参考资料 1】
标题: ...
来源: ...
定位: ...
内容:
...
```

设计意义:

- LLM 拿到的是自然语言上下文。
- 工具和评估仍然保留 `RetrievalResult`。

---

### 九、典型调用流程

以 hybrid_rerank 为例:

```text
RetrievalService.retrieve(query)
-> query.retrieval_mode != dense_only
-> hybrid_search_service.search(query)
-> raw SearchResult list
-> _build_results()
-> _build_source_ref()
-> _build_citation_text()
-> _format_context()
-> RetrievalResponse
```

---

### 十、关键设计亮点

1. **召回和证据组装解耦**: 不在 RetrievalService 里写 BM25/RRF/rerank。
2. **强 citation 边界**: 缺稳定来源字段的 hit 会被跳过。
3. **兼容旧 metadata**: 可以从 `_file_name` 等旧字段恢复 source_ref。
4. **同时服务 LLM 和评估**: `context_text` 给 LLM，`results` 给工具/评估/UI。
5. **统一空结果行为**: `empty_message` 固定。

---

### 十一、边界与风险

- 当前 citation_text 是中文展示格式，如果 UI 需要结构化展示，应优先使用 `source_ref`。
- 对不完整 hit 的策略是跳过，极端情况下可能导致检索结果变少。
- parser_engine 兜底为 plain_text，后续如果需要更严格，可以把未知 parser 作为异常或 warning。

---

### 十二、面试里怎么讲

可以讲成:

> RetrievalService 不负责召回算法，而是负责 evidence assembly。无论上游是 dense、BM25、hybrid 还是 rerank，最后都必须变成 RetrievalResult，里面包含 doc_id、chunk_id、source_ref 和 citation_text。这样后续换召回策略时，不会破坏 citation contract。

---

## 8. [app/services/hybrid_search_service.py](../app/services/hybrid_search_service.py)

这个文件实现了**混合检索服务（Hybrid Search Service）**，结合稠密检索和稀疏检索，并通过 RRF 融合结果，还支持可选 rerank。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`hybrid_search_service.py` 是 P3 检索质量增强的核心协调层。

它整合三类能力:

- 稠密检索: 向量语义召回。
- 稀疏检索: BM25 关键词召回。
- RRF 融合: 合并不同召回来源的排名。
- 可选 rerank: 对融合候选进行精排。

它不负责 citation 组装。最终结果仍然交给 `RetrievalService` 转成 `RetrievalResult`。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `defaultdict` | 累加 RRF 分数和 rank metadata |
| `Iterable` | 类型注解 |
| `logger` | 检索日志 |
| `config` | 读取 `rerank_top_k` |
| `RetrievalMode` | 判断检索模式 |
| `RetrievalQuery` | 检索请求对象 |
| `rerank_service` | hybrid_rerank 模式的精排服务 |
| `sparse_search_service` | BM25 稀疏召回 |
| `vector_search_service` | 向量稠密召回 |
| `SearchResult` | 统一 raw hit 数据结构 |

---

### 二、核心类 1: `RrfFusionService`

#### 1. 类作用

`RrfFusionService` 对多个已排序的结果列表执行 Reciprocal Rank Fusion。

它输入:

```text
[("dense", dense_hits), ("sparse", sparse_hits)]
```

输出:

```text
按 fusion_score 排序的 SearchResult list
```

#### 2. 初始化方法

```python
def __init__(self, rank_constant: int = 60):
    self.rank_constant = rank_constant
```

RRF 公式:

```text
score += 1 / (rank_constant + rank)
```

`rank_constant=60` 是常见默认值，用来避免头部排名分数差距过大。

#### 3. 核心方法 `fuse`

```python
def fuse(
    self,
    ranked_lists: Iterable[tuple[str, list[SearchResult]]],
    top_k: int,
) -> list[SearchResult]:
```

##### 步骤 1: 初始化容器

```python
scores: dict[str, float] = defaultdict(float)
representatives: dict[str, SearchResult] = {}
rank_metadata: dict[str, dict[str, object]] = defaultdict(dict)
```

字段含义:

| 容器 | 作用 |
|---|---|
| `scores` | 每个 chunk 的融合分数 |
| `representatives` | 每个 chunk 的代表性 SearchResult |
| `rank_metadata` | 每个 chunk 在各召回源中的 rank 和 score |

##### 步骤 2: 遍历召回结果并累加 RRF 分数

```python
for source_name, results in ranked_lists:
    for rank, result in enumerate(results, start=1):
        chunk_id = result.id
        scores[chunk_id] += 1 / (self.rank_constant + rank)
        representatives.setdefault(chunk_id, result)
        rank_metadata[chunk_id][f"{source_name}_rank"] = rank
        rank_metadata[chunk_id][f"{source_name}_score"] = result.score
```

关键点:

- `chunk_id = result.id` 是融合去重的唯一键。
- 同一个 chunk 如果 dense 和 sparse 都命中，会累加分数。
- `representatives.setdefault()` 保留第一次出现的 hit 作为代表。
- rank/score metadata 被记录下来，方便后续分析来源贡献。

##### 步骤 3: 排序并截断 TopK

```python
for chunk_id, fusion_score in sorted(
    scores.items(),
    key=lambda item: (-item[1], item[0])
)[:top_k]:
```

排序规则:

1. `fusion_score` 降序。
2. `chunk_id` 升序。

第二个条件保证分数相同时排序稳定。

##### 步骤 4: 构造融合结果

```python
metadata = dict(representative.metadata)
metadata.update(rank_metadata[chunk_id])
metadata["retrieval_mode"] = "hybrid"
metadata.setdefault("recall_score", representative.score)
metadata["fusion_score"] = fusion_score
```

新增 metadata:

- `dense_rank`
- `dense_score`
- `sparse_rank`
- `sparse_score`
- `retrieval_mode=hybrid`
- `recall_score`
- `fusion_score`

返回的 `SearchResult.score` 使用融合分数。

---

### 三、核心类 2: `HybridSearchService`

#### 1. 类作用

`HybridSearchService` 是检索模式的协调器。

它负责:

- dense_only 直接走 vector search。
- sparse_only 直接走 BM25。
- hybrid 走 dense + sparse + RRF。
- hybrid_rerank 走 dense + sparse + RRF + rerank。

#### 2. 初始化方法

```python
def __init__(self):
    self.rrf_fusion_service = RrfFusionService()
    logger.info("混合检索服务初始化完成")
```

初始化时持有一个 RRF 服务实例。

---

### 四、核心方法: `search`

```python
def search(self, query: RetrievalQuery) -> list[SearchResult]:
```

#### 分支 1: dense_only

```python
if query.retrieval_mode == RetrievalMode.DENSE_ONLY:
    return vector_search_service.search_similar_documents(query.query, top_k=query.top_k)
```

直接走向量召回。

#### 分支 2: sparse_only

```python
if query.retrieval_mode == RetrievalMode.SPARSE_ONLY:
    return sparse_search_service.search(
        query.query,
        top_k=query.top_k,
        knowledge_base_ids=query.knowledge_base_ids,
    )
```

直接走 BM25 稀疏召回。

#### 分支 3: 非法模式校验

```python
if query.retrieval_mode != RetrievalMode.HYBRID:
    if query.retrieval_mode != RetrievalMode.HYBRID_RERANK:
        raise ValueError(...)
```

如果不是 hybrid，也不是 hybrid_rerank，就抛异常。

#### 分支 4: hybrid / hybrid_rerank

##### 步骤 1: 扩大候选集

```python
candidate_k = max(query.top_k * 4, query.top_k)
```

这样 dense 和 sparse 各自召回更多候选，给融合和 rerank 留空间。

##### 步骤 2: dense recall

```python
dense_hits = vector_search_service.search_similar_documents(query.query, top_k=candidate_k)
dense_hits = [self._annotate_recall(hit, source_name="dense") for hit in dense_hits]
```

先向量召回，再标注来源。

##### 步骤 3: sparse recall

```python
sparse_hits = sparse_search_service.search(
    query.query,
    top_k=candidate_k,
    knowledge_base_ids=query.knowledge_base_ids,
)
sparse_hits = [self._annotate_recall(hit, source_name="sparse") for hit in sparse_hits]
```

BM25 召回同样标注来源。

##### 步骤 4: RRF fusion

```python
fused = self.rrf_fusion_service.fuse(
    [("dense", dense_hits), ("sparse", sparse_hits)],
    top_k=max(query.top_k, config.rerank_top_k)
    if query.retrieval_mode == RetrievalMode.HYBRID_RERANK
    else query.top_k,
)
```

如果后面要 rerank，则融合结果至少保留 `rerank_top_k` 个候选。

##### 步骤 5: optional rerank

```python
if query.retrieval_mode == RetrievalMode.HYBRID_RERANK:
    return rerank_service.rerank(query, fused)
```

rerank 只在 `HYBRID_RERANK` 下启用。

##### 步骤 6: 返回 fused

```python
return fused
```

---

### 五、辅助方法: `_annotate_recall`

```python
def _annotate_recall(self, hit: SearchResult, source_name: str) -> SearchResult:
```

作用: 给 raw hit 标注召回来源和原始分数。

核心逻辑:

```python
metadata = dict(hit.metadata)
metadata["recall_score"] = hit.score
metadata[f"{source_name}_score"] = hit.score
metadata["retrieval_mode"] = source_name
return SearchResult(...)
```

例如 dense hit 会得到:

```text
recall_score=<dense_score>
dense_score=<dense_score>
retrieval_mode=dense
```

sparse hit 会得到:

```text
recall_score=<sparse_score>
sparse_score=<sparse_score>
retrieval_mode=sparse
```

它返回新 `SearchResult`，不直接修改原对象。

---

### 六、典型调用流程

以 `HYBRID_RERANK` 为例:

```text
RetrievalService.retrieve()
-> HybridSearchService.search(query)
-> candidate_k = top_k * 4
-> vector_search_service.search_similar_documents()
-> _annotate_recall(dense)
-> sparse_search_service.search()
-> _annotate_recall(sparse)
-> RrfFusionService.fuse()
-> rerank_service.rerank()
-> raw SearchResult list
-> RetrievalService._build_results()
```

---

### 七、关键设计亮点

1. **召回、融合、重排解耦**: RRF 是独立类，rerank 是独立 service。
2. **元数据可追踪**: dense/sparse rank、score、fusion_score 都保留。
3. **排序稳定**: fusion 分相同时按 chunk_id 排序。
4. **候选扩展**: hybrid 先召回更多候选，避免 top_k 太小影响融合。
5. **不破坏 citation**: 只改变排序和分数，不改 source_ref。

---

### 八、边界与风险

- `candidate_k = top_k * 4` 是经验值，后续可以变成配置。
- RRF 默认各召回源权重相同，没有 source-specific weight。
- dense 和 sparse 的 score 尺度不同，所以融合使用 rank 而不是原始 score。
- hybrid_rerank 是否优于 dense_only 需要评估报告证明，不能凭主观判断。

---

### 九、面试里怎么讲

可以讲成:

> HybridSearchService 是 P3 的召回协调层。它先分别跑 dense vector search 和 BM25 sparse search，再用 RRF 按排名融合，保留 dense/sparse 的 rank 和 score 作为 metadata。如果是 hybrid_rerank，再把 fused candidates 交给独立 rerank 层。它不做 citation 组装，最后仍交给 RetrievalService 输出 RetrievalResult。

---

## 9. [app/services/rerank_service.py](../app/services/rerank_service.py)

这个文件实现了**显式重排序服务（Rerank Service）**，用于在 hybrid recall 之后对候选结果重新排序，同时保证失败可回退、身份不被改写。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`rerank_service.py` 是 P3 检索质量增强中的精排边界。

它解决的问题:

- rerank 不应该混在 fusion 代码里。
- rerank 不应该调用 answer prompt。
- rerank 失败不应该打断检索主链路。
- rerank 只能改变排序和分数，不能改变 `doc_id/chunk_id/source_ref`。
- 后续替换外部 rerank 模型时，需要稳定接口。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `re` | 中英文 tokenization |
| `time` | 统计 rerank latency 和 timeout |
| `Counter` | 统计候选文本词频 |
| `Protocol` | 定义 scorer 接口 |
| `logger` | 记录 rerank 成功/失败 |
| `config` | 读取 rerank 开关、模型、超时、top_k、fallback |
| `RetrievalQuery` | 获取 query 文本和 top_k |
| `SearchResult` | rerank 的候选输入和输出 |

---

### 二、核心协议: `RerankScorer`

```python
class RerankScorer(Protocol):
    def score(self, query: str, candidates: list[SearchResult]) -> list[float]:
        ...
```

它定义了 scorer 最小接口:

```text
输入 query + candidates
输出每个 candidate 的 rerank score
```

设计意义:

- 当前用本地 lexical scorer。
- 后续可以替换成外部 rerank 模型。
- 只要输出 score list，主链路不用改。

---

### 三、核心类 1: `LexicalRerankScorer`

#### 1. 类作用

这是一个无外部依赖的本地 rerank baseline。

它不是最终理想 reranker，而是用来跑通 rerank 边界、fallback、score metadata 和测试。

#### 2. 核心方法 `score`

```python
def score(self, query: str, candidates: list[SearchResult]) -> list[float]:
```

步骤:

##### 步骤 1: query 分词

```python
query_terms = self._tokenize(query)
if not query_terms:
    return [0.0 for _ in candidates]
```

空 query 直接返回全 0。

##### 步骤 2: 遍历候选

```python
candidate_terms = self._tokenize(self._candidate_text(candidate))
```

候选文本包括:

- heading_path。
- candidate.content。

##### 步骤 3: 计算 overlap

```python
term_counts = Counter(candidate_terms)
overlap = sum(1 for term in query_term_set if term_counts.get(term, 0) > 0)
```

##### 步骤 4: 计算分数

```python
coverage = overlap / len(query_term_set)
density = overlap / len(set(candidate_terms))
phrase_bonus = 0.1 if query.lower() in candidate.content.lower() else 0.0
scores.append(coverage + density + phrase_bonus)
```

分数组成:

| 部分 | 含义 |
|---|---|
| `coverage` | query term 覆盖比例 |
| `density` | candidate 中命中词密度 |
| `phrase_bonus` | 完整短语命中奖励 |

#### 3. `_candidate_text`

```python
def _candidate_text(self, candidate: SearchResult) -> str:
```

把标题路径和正文拼成 rerank 文本:

```text
heading_path
content
```

这样标题命中也能影响 rerank。

#### 4. `_tokenize`

```python
for part in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", text.lower()):
```

支持:

- 英文、数字、下划线 token。
- 中文连续片段。

中文处理:

```python
tokens.extend(part)
tokens.extend(part[index : index + 2] ...)
```

它会生成单字和 bigram，提升中文短词匹配能力。

---

### 四、核心类 2: `RerankService`

#### 1. 类作用

`RerankService` 负责:

- 判断 rerank 是否启用。
- 控制最大候选数。
- 调用 scorer。
- 检查 timeout。
- 检查 score 数量。
- 排序候选。
- 写入 rerank metadata。
- 异常时 fallback。

#### 2. 初始化方法

```python
def __init__(
    self,
    enabled: bool | None = None,
    scorer: RerankScorer | None = None,
    timeout_ms: int | None = None,
    max_candidates: int | None = None,
    fallback_on_error: bool | None = None,
):
```

配置来源:

```python
self.enabled = config.rerank_enabled if enabled is None else enabled
self.scorer = scorer or LexicalRerankScorer()
self.timeout_ms = config.rerank_timeout_ms if timeout_ms is None else timeout_ms
self.max_candidates = config.rerank_top_k if max_candidates is None else max_candidates
self.fallback_on_error = config.rerank_fallback_on_error if fallback_on_error is None else fallback_on_error
self.model_id = config.rerank_model
```

设计意义:

- 支持全局 config。
- 测试可以注入 scorer、enabled、timeout。
- rerank 是可选增强，不是硬依赖。

---

### 五、核心方法: `rerank`

```python
def rerank(self, query: RetrievalQuery, candidates: list[SearchResult]) -> list[SearchResult]:
```

#### 步骤 1: 空候选处理

```python
if not candidates:
    return []
```

#### 步骤 2: 限制候选数量

```python
candidates = candidates[: max(query.top_k, self.max_candidates)]
```

保证至少有 `top_k`，但不超过 rerank 最大候选范围。

#### 步骤 3: disabled 分支

```python
if not self.enabled:
    return self._annotate(candidates, status="disabled")
```

rerank 关闭时，不改变排序，只写 metadata:

```text
rerank_status=disabled
```

#### 步骤 4: scorer 打分

```python
started_at = time.perf_counter()
scores = self.scorer.score(query.query, candidates)
duration_ms = int((time.perf_counter() - started_at) * 1000)
```

#### 步骤 5: timeout 和 score count 校验

```python
if duration_ms > self.timeout_ms:
    raise TimeoutError(...)
if len(scores) != len(candidates):
    raise ValueError(...)
```

这两个校验防止外部 scorer 行为不稳定。

#### 步骤 6: 排序

```python
ranked_pairs = sorted(
    enumerate(zip(candidates, scores, strict=True)),
    key=lambda item: (-item[1][1], item[0]),
)
```

排序规则:

1. rerank score 降序。
2. 原始顺序升序，保证稳定。

#### 步骤 7: 写入 rerank metadata

```python
self._copy_with_metadata(
    candidate,
    retrieval_mode="hybrid_rerank",
    rerank_score=score,
    rerank_status="applied",
    rerank_model=self.model_id,
    rerank_latency_ms=duration_ms,
)
```

metadata 记录:

- `retrieval_mode=hybrid_rerank`
- `rerank_score`
- `rerank_status=applied`
- `rerank_model`
- `rerank_latency_ms`

#### 步骤 8: fallback

```python
except Exception as exc:
    if not self.fallback_on_error:
        raise
    return self._annotate(candidates[: query.top_k], status="fallback", error=str(exc))
```

如果 scorer 失败，且允许 fallback:

- 返回原 fused candidates。
- 标记 `rerank_status=fallback`。
- 记录 `rerank_error`。

---

### 六、辅助方法

#### 1. `_annotate`

```python
def _annotate(self, candidates, status, error=""):
```

给候选结果统一写 rerank metadata。

用于:

- disabled。
- fallback。

#### 2. `_copy_with_metadata`

```python
def _copy_with_metadata(self, result: SearchResult, **metadata_updates: object) -> SearchResult:
```

它复制 `SearchResult`，只更新 metadata:

```python
return SearchResult(
    id=result.id,
    content=result.content,
    score=result.score,
    metadata=metadata,
)
```

注意:

- 不改 `id`。
- 不改 `content`。
- 不改原始 `score`。

这样可以保证 citation identity 不被 rerank 破坏。

---

### 七、典型调用流程

```text
HybridSearchService.search()
-> RrfFusionService.fuse()
-> rerank_service.rerank(query, fused)
-> scorer.score()
-> sort by rerank_score
-> write rerank metadata
-> return SearchResult list
-> RetrievalService._build_results()
```

---

### 八、关键设计亮点

1. **独立边界**: rerank 不混进 fusion 或 prompt。
2. **可替换 scorer**: `RerankScorer` 协议让外部模型容易接入。
3. **失败可回退**: timeout 或异常不打断主检索。
4. **identity 不变**: 只更新 metadata，不改 id/content/source_ref。
5. **可观测**: 记录 status、model、latency、error。

---

### 九、边界与风险

- 当前 scorer 是 lexical baseline，不是模型型 rerank。
- `rerank_enabled` 默认关闭，只有 hybrid_rerank 或评估脚本显式打开。
- timeout 是执行后检查，不是强制中断外部调用；如果未来接外部 API，需要在 API client 层设置超时。

---

### 十、面试里怎么讲

可以讲成:

> 我把 rerank 做成独立 service，而不是混在 fusion 或 prompt 里。它通过 RerankScorer 协议支持后续替换外部模型；失败时可以 fallback 到 fused candidates；rerank 只改变排序和 metadata，不改 doc_id、chunk_id、source_ref，所以不会破坏 citation。

---

## 10. [evals/rag_retrieval/run_retrieval_eval.py](../evals/rag_retrieval/run_retrieval_eval.py)

这个文件实现了**P3 检索离线评估脚本**，用于在同一固定查询集上比较 `dense_only`、`hybrid`、`hybrid_rerank`，并输出 JSON 和 Markdown 报告。

---

### 一、整体架构与核心依赖

#### 1. 代码定位与用途

`run_retrieval_eval.py` 是 P3-4 的核心交付物。

它解决的问题:

- hybrid/rerank 是否有收益不能靠感觉。
- 必须先有固定 golden queries。
- dense、hybrid、hybrid_rerank 必须在同一 corpus、同一 query set 上对比。
- 评估不能污染生产 collection。
- 评估必须同时看 recall、hit、MRR、citation correctness、latency。

#### 2. 核心依赖模块

| 导入模块 | 用途 |
|---|---|
| `argparse` | 支持命令行指定评估模式 |
| `json` | 写 JSON/JSONL 报告 |
| `statistics` | 计算 latency p50 |
| `sys` | 把 repo root 加入 import path |
| `tempfile` | 创建临时工作目录和 metadata store |
| `time` | 统计 query latency |
| `datetime` | 生成 run id 和报告时间 |
| `Path` | 路径处理 |
| `utility` | PyMilvus collection 管理 |
| `config` | 设置 Milvus host |
| `DocumentRecord/DocumentStatus/ParserEngine/RetrievalMode/RetrievalQuery` | 构造文档和检索请求 |
| `KnowledgeMetadataStore` | 临时 metadata store |
| `vector_store_manager` | 写入临时 Milvus collection |
| `retrieval_service` | 执行实际检索 |
| `rerank_service` | hybrid_rerank 评估时临时开启 |

---

### 二、全局配置

```python
EVAL_DIR = REPO_ROOT / "evals" / "rag_retrieval"
REPORT_DIR = EVAL_DIR / "reports"
RUN_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
EVAL_COLLECTION = f"p3_retrieval_eval_{RUN_ID}"
DEFAULT_MODES = [RetrievalMode.DENSE_ONLY, RetrievalMode.HYBRID, RetrievalMode.HYBRID_RERANK]
```

字段解释:

| 字段 | 含义 |
|---|---|
| `EVAL_DIR` | 评估目录 |
| `REPORT_DIR` | 报告输出目录 |
| `RUN_ID` | 本次运行时间戳 |
| `EVAL_COLLECTION` | 临时 Milvus collection |
| `DEFAULT_MODES` | 默认评估模式 |

关键点:

```python
config.milvus_host = "127.0.0.1"
```

这是本地环境经验: Docker Milvus 用 IPv4 连接更稳定。

---

### 三、工具函数

#### 1. `write_json`

```python
def write_json(path: Path, payload: Any) -> None:
```

作用: 写格式化 JSON。

特点:

- 自动创建父目录。
- `ensure_ascii=False` 保留中文。
- 末尾加换行。

#### 2. `write_jsonl`

```python
def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
```

作用: 写 golden queries。

每条 query 一行 JSON。

#### 3. `exact_source_ref_match`

```python
def exact_source_ref_match(result_ref, gold_ref: dict[str, Any]) -> bool:
```

作用: 判断检索结果的 `source_ref` 是否和 gold source ref 完全匹配。

比较字段:

```text
kb_id
doc_id
chunk_id
source_file
page_start
page_end
content_type
parser_engine
```

这就是 `citation_correctness@3` 的判断基础。

---

### 四、构造评估数据

#### 1. `build_mineru_fixture`

```python
def build_mineru_fixture(root: Path) -> DocumentRecord:
```

作用: 构造一个 synthetic MinerU 文档。

它会创建:

```text
manual.pdf
cleaned.md
chunks.json
tables.json
blocks.json
quality_report.json
artifact_manifest.json
```

正文 chunk:

```json
{
  "id": "c00001",
  "text": "第一段正文",
  "pages": [2, 3],
  "heading_path": ["第一章", "概述"]
}
```

表格 chunk:

```json
{
  "table_id": "t00001",
  "page": 4,
  "heading_path": ["第一章", "参数"],
  "content_type": "manual_table",
  "markdown": "| 名称 | 值 | ..."
}
```

设计意义:

- 评估不只覆盖 md/txt。
- 还覆盖 MinerU 正文和表格 citation。
- 不依赖真实 PDF 解析，评估可重复。

#### 2. `build_golden_queries`

```python
def build_golden_queries(cpu_path, memory_path, cpu_doc_id, memory_doc_id) -> list[dict[str, Any]]:
```

作用: 生成固定查询集。

当前 4 条:

| id | query | 覆盖内容 |
|---|---|---|
| `cpu_alarm` | `HighCPUUsage 告警怎么处理` | Markdown 运维文档 |
| `memory_alarm` | `HighMemoryUsage 告警怎么处理` | Markdown 运维文档 |
| `mineru_text` | `第一段正文` | MinerU 正文 chunk |
| `mineru_table` | `表1 参数` | MinerU 表格 chunk |

每条 query 包含:

```text
gold_doc_ids
gold_chunk_ids
gold_source_refs
expected_keywords
```

最关键的是 `gold_source_refs`，它让评估能检查 citation identity。

---

### 五、指标计算

#### 1. `compute_metrics`

```python
def compute_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
```

计算汇总指标:

| 指标 | 含义 |
|---|---|
| `doc_recall_at_1` | Top1 是否命中期望文档 |
| `doc_recall_at_3` | Top3 是否命中期望文档 |
| `hit_at_1` | Top1 是否命中 gold chunk |
| `hit_at_3` | Top3 是否命中 gold chunk |
| `citation_correctness_at_3` | Top3 是否存在 source_ref 正确命中 |
| `mrr_at_3` | 第一个正确命中的倒数排名 |
| `latency_ms` | min/p50/p95/max/avg |

#### 2. p95 计算

```python
sorted(row["latency_ms"] for row in rows)[max(0, int(len(rows) * 0.95) - 1)]
```

当前 query 数少，p95 只是轻量估计，不代表大样本统计结论。

---

### 六、核心方法: `evaluate_mode`

```python
def evaluate_mode(mode: RetrievalMode, golden_queries: list[dict[str, Any]]) -> dict[str, Any]:
```

作用: 对一种检索模式跑完整 golden query set。

#### 步骤 1: hybrid_rerank 临时启用 rerank

```python
if mode == RetrievalMode.HYBRID_RERANK:
    rerank_service.enabled = True
```

运行结束后在 `finally` 中恢复为 False。

#### 步骤 2: 构造 RetrievalQuery

```python
query = RetrievalQuery(
    query=item["query"],
    top_k=3,
    retrieval_mode=mode,
    knowledge_base_ids=["default"],
)
```

#### 步骤 3: 执行检索并统计 latency

```python
start = time.perf_counter()
response = retrieval_service_module.retrieval_service.retrieve(query)
latency_ms = int((time.perf_counter() - start) * 1000)
```

#### 步骤 4: 计算 recall/hit

```python
doc_recall_at_1 = 1 if results and top_doc_id in item["gold_doc_ids"] else 0
doc_recall_at_3 = 1 if any(r.doc_id in item["gold_doc_ids"] for r in results) else 0
hit_at_1 = 1 if results and top_chunk_id in item["gold_chunk_ids"] else 0
hit_at_3 = 1 if any(r.chunk_id in item["gold_chunk_ids"] for r in results) else 0
```

#### 步骤 5: 计算 citation correctness

```python
matched_gold = next(
    gold_ref
    for gold_ref in item["gold_source_refs"]
    if exact_source_ref_match(result.source_ref, gold_ref)
)
```

如果没有匹配，会记录 `citation_issues`:

```text
rank
chunk_id
missing_or_mismatch
```

#### 步骤 6: 计算 MRR

```python
mrr_at_3 = 1 / first_match_rank if first_match_rank else 0.0
```

#### 步骤 7: 保存逐 query 明细

每条 row 记录:

- gold doc/chunk。
- retrieved doc/chunk。
- top1。
- recall/hit/MRR/citation。
- latency。
- citation issues。
- 每个 result 的 source_ref、citation_text、metadata。

---

### 七、报告格式化

#### 1. `format_markdown`

```python
def format_markdown(report: dict[str, Any]) -> str:
```

作用: 把 JSON report 转成 Markdown。

报告结构:

```text
# P3 Retrieval Evaluation Report
generated_at
collection
modes
query_count

## dense_only
metrics
### cpu_alarm
query details
...
```

这样既有机器可读 JSON，又有人可读 Markdown。

---

### 八、核心运行方法: `run`

```python
def run() -> dict[str, Any]:
```

这是整份脚本的主流程。

#### 步骤 1: 备份全局状态

```python
original_collection_name = milvus_client_module.MilvusClientManager.COLLECTION_NAME
original_vector_collection_name = vector_store_manager.collection_name
original_vector_store = vector_store_manager.vector_store
original_metadata_store_module = vector_index_module.knowledge_metadata_store
original_ingestion_metadata_store = ingestion_module.knowledge_metadata_store
original_rerank_enabled = rerank_service.enabled
```

因为评估会临时替换 collection 和 metadata store，所以必须先备份。

#### 步骤 2: 创建临时环境

```python
with tempfile.TemporaryDirectory() as tmpdir:
    temp_store = KnowledgeMetadataStore(tmp_root / "knowledge_metadata_store.json")
```

#### 步骤 3: 切换临时 collection 和 store

```python
vector_index_module.knowledge_metadata_store = temp_store
ingestion_module.knowledge_metadata_store = temp_store
milvus_client_module.MilvusClientManager.COLLECTION_NAME = EVAL_COLLECTION
vector_store_manager.collection_name = EVAL_COLLECTION
vector_store_manager.vector_store = None
```

设计意义:

- 不污染真实 metadata store。
- 不污染生产 collection。

#### 步骤 4: 构建 corpus 和 golden queries

```python
cpu_path = REPO_ROOT / "aiops-docs" / "cpu_high_usage.md"
memory_path = REPO_ROOT / "aiops-docs" / "memory_high_usage.md"

golden_queries = build_golden_queries(...)
write_jsonl(EVAL_DIR / "golden_queries.jsonl", golden_queries)
```

#### 步骤 5: 索引测试语料

```python
index_service.index_single_file(cpu_path.as_posix(), kb_id="default")
index_service.index_single_file(memory_path.as_posix(), kb_id="default")

mineru_record = build_mineru_fixture(tmp_root)
temp_store.upsert_document(mineru_record)
index_service.index_document_record(mineru_record)
```

语料包含:

- 两个真实 markdown 运维文档。
- 一个 synthetic MinerU PDF fixture。

#### 步骤 6: 评估多模式

```python
mode_reports = {mode.value: evaluate_mode(mode, golden_queries) for mode in modes}
```

默认模式:

```text
dense_only
hybrid
hybrid_rerank
```

#### 步骤 7: 写报告

```python
write_json(report_json, report)
report_md.write_text(format_markdown(report), encoding="utf-8")
```

输出:

```text
evals/rag_retrieval/reports/retrieval_eval_<RUN_ID>.json
evals/rag_retrieval/reports/retrieval_eval_<RUN_ID>.md
```

#### 步骤 8: finally 清理和恢复

```python
rerank_service.enabled = original_rerank_enabled
vector_index_module.knowledge_metadata_store = original_metadata_store_module
ingestion_module.knowledge_metadata_store = original_ingestion_metadata_store
vector_store_manager.collection_name = original_vector_collection_name
milvus_client_module.MilvusClientManager.COLLECTION_NAME = original_collection_name
if utility.has_collection(EVAL_COLLECTION):
    utility.drop_collection(EVAL_COLLECTION)
```

这是评估脚本成熟度的关键:

- 不留下临时 collection。
- 不改变全局 rerank 开关。
- 不污染主 metadata store。

---

### 九、命令行入口

#### 1. `parse_args`

支持:

```bash
--modes dense_only hybrid hybrid_rerank
```

#### 2. `main`

```python
selected_modes = [RetrievalMode(mode) for mode in args.modes]
global DEFAULT_MODES
DEFAULT_MODES = selected_modes
run()
```

它通过临时重写 `DEFAULT_MODES` 来控制本次评估模式，最后恢复。

---

### 十、典型调用流程

```bash
MILVUS_HOST=127.0.0.1 .venv/bin/python evals/rag_retrieval/run_retrieval_eval.py
```

流程:

```text
创建临时 collection
-> 创建临时 metadata store
-> 索引 CPU/Memory markdown
-> 构造 synthetic MinerU artifact
-> 索引 MinerU text/table chunk
-> 跑 dense_only
-> 跑 hybrid
-> 跑 hybrid_rerank
-> 计算 recall/hit/MRR/citation correctness/latency
-> 写 JSON/MD 报告
-> 删除临时 collection
-> 恢复全局状态
```

---

### 十一、关键设计亮点

1. **固定评估集**: 同一批 golden queries 对比多个模式。
2. **临时 collection**: 不污染生产 `biz` collection。
3. **临时 metadata store**: 不污染主项目状态。
4. **覆盖 MinerU 形状**: synthetic fixture 覆盖正文和表格 citation。
5. **多指标**: 不只看 recall，还看 citation correctness 和 latency。
6. **可读报告**: 同时输出 JSON 和 Markdown。
7. **现场恢复**: finally 恢复全局状态和删除 collection。

---

### 十二、边界与风险

- 当前 golden queries 只有 4 条，能证明链路和门禁，不足以证明大样本效果优于 dense-only。
- MinerU fixture 是 synthetic，不代表真实复杂 PDF 效果。
- p95 在小样本下只是参考，不是严格性能统计。
- `hybrid_rerank` 使用本地 lexical reranker，不是外部模型型 rerank。

---

### 十三、面试里怎么讲

可以讲成:

> 我没有直接在线上 collection 里凭感觉测试 hybrid/rerank，而是写了离线评估脚本。它用临时 Milvus collection 和临时 metadata store，索引固定语料，跑 dense_only、hybrid、hybrid_rerank 三种模式，并计算 recall、hit、MRR、citation correctness 和 latency。跑完后写 JSON/Markdown 报告并清理现场。

---

## 11. 10 个文件连起来怎么理解

读完这 10 个文件后，可以把增强版 RAG 项目讲成一条完整链路:

```text
knowledge.py
定义领域对象: DocumentRecord / ChunkRecord / SourceRef / RetrievalResult

parser_engine_router.py
决定文件进入 plain_text 还是 mineru

document_ingestion_service.py
保存原件、创建记录、维护状态、触发解析或索引准备

artifact_manifest_service.py
把 MinerU 六件套声明成可校验 contract

artifact_chunk_builder_service.py
把 chunks.json / tables.json 转成 ChunkRecord + Document

vector_index_service.py
写入 Milvus 和 metadata store，并按 doc_id 幂等清理

retrieval_service.py
把 raw hit 转成带 source_ref / citation_text 的 RetrievalResult

hybrid_search_service.py
协调 dense / sparse / RRF / optional rerank

rerank_service.py
提供可开关、可回退、可替换 scorer 的 rerank 边界

run_retrieval_eval.py
用固定 golden queries 评估 dense / hybrid / hybrid_rerank
```

一句话总结:

```text
这套代码不是只实现“能查文档”，
而是让文档接入、artifact、chunk、索引、citation、hybrid、rerank、eval 每一层都有明确职责和可验证边界。
```

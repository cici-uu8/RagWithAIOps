# WeKnora R0 Reuse Review

日期: 2026-05-13

## 1. R0 目标

R0 是 P1/P2 开发前的只读复核阶段。目标不是改代码，而是确认 WeKnora 里哪些成熟边界应该被采用、哪些必须裁剪、哪些暂不进入首轮实现，避免后续在 `SuperBizAgent` 里自造一套平行 RAG 链路。

本轮复核结论:

- 采用 WeKnora 的知识库领域对象分层: `KnowledgeBase -> Knowledge -> Chunk`。
- 采用 WeKnora 的 parser engine / DocReader 抽象边界，但不照搬 Go/gRPC 生命周期。
- 采用 WeKnora 的 chunking 配置、ContextHeader、幂等清理和检索结果补全思路。
- P1/P2 暂不接完整 WeKnora 服务，不引入多租户、权限、FAQ/Wiki、GraphRAG、异步队列和完整 hybrid search。
- 主项目的解析底座仍保持 MinerU-first，且必须满足 `docs/rag_ingestion_artifact_contract.md` 的六件套 artifact 契约。
- 按更严格的复用标准看，P1/P2 核心路径里几乎没有“原样直接接入即可运行”的代码；主要策略应是“复制 WeKnora 成熟代码到主仓库，再做最小修改”，而不是只参考边界后另写一套。

## 2. 已复核源文件

| 类别 | WeKnora 源文件 | 复核目的 |
|---|---|---|
| 知识库模型 | `/Users/cici/oncall agent/WeKnora/internal/types/knowledgebase.go` | 复核 `KnowledgeBase`、`ChunkingConfig`、`ParserEngineRule`、`ResolveParserEngine()` |
| 文档模型 | `/Users/cici/oncall agent/WeKnora/internal/types/knowledge.go` | 复核 `Knowledge`、`ParseStatus`、文件元数据、错误状态 |
| chunk 模型 | `/Users/cici/oncall agent/WeKnora/internal/types/chunk.go` | 复核 `Chunk`、`ChunkType`、`StartAt/EndAt`、`ParentChunkID`、`Metadata`、`ContextHeader` |
| parser 请求/响应 | `/Users/cici/oncall agent/WeKnora/internal/types/docparser.go` | 复核 `ReadRequest`、`ReadResult`、`ParsedChunk`、`ImageRef` |
| parser 接口 | `/Users/cici/oncall agent/WeKnora/internal/types/interfaces/document_parser.go` | 复核 `DocReader.Read()` 和 `DocumentReader.ListEngines()` 边界 |
| Go parser registry | `/Users/cici/oncall agent/WeKnora/internal/infrastructure/docparser/engine_registry.go` | 复核 `simple/builtin/mineru/mineru_cloud` 引擎注册与可用性检查 |
| 简单格式 parser | `/Users/cici/oncall agent/WeKnora/internal/infrastructure/docparser/builtin_converter.go` | 复核 md/txt/csv/json/image/audio 的简单格式读取方式 |
| MinerU adapter | `/Users/cici/oncall agent/WeKnora/internal/infrastructure/docparser/mineru_converter.go` | 复核 self-hosted MinerU endpoint、overrides、`/file_parse` 调用边界 |
| Python docreader registry | `/Users/cici/oncall agent/WeKnora/docreader/parser/registry.py` | 复核 Python 侧 `builtin/markitdown` parser registry 和 fallback 行为 |
| Python PDF parser | `/Users/cici/oncall agent/WeKnora/docreader/parser/pdf_parser.py` | 复核 PDF fallback chain，不把 MarkItDown 当当前主路径 |
| chunker 策略 | `/Users/cici/oncall agent/WeKnora/internal/infrastructure/chunker/strategy.go` | 复核 `auto/heading/heuristic/legacy` 策略选择与 fallback |
| chunker 实现 | `/Users/cici/oncall agent/WeKnora/internal/infrastructure/chunker/splitter.go` | 复核保护公式、表格、代码块和链接的切分逻辑 |
| chunking 文档 | `/Users/cici/oncall agent/WeKnora/docs/CHUNKING.md` | 复核默认 chunk size、overlap、parent-child 和策略说明 |
| chunk service | `/Users/cici/oncall agent/WeKnora/internal/application/service/chunk.go` | 复核 chunk 创建、查询、更新、删除服务边界 |
| chunk repository interface | `/Users/cici/oncall agent/WeKnora/internal/types/interfaces/chunk.go` | 复核按 `KnowledgeID` 批量列出、删除、分页查询 chunk 的仓储能力 |
| ingestion process | `/Users/cici/oncall agent/WeKnora/internal/application/service/knowledge_process.go` | 复核处理前清旧 chunk / 旧索引的幂等策略 |
| retrieval params/result | `/Users/cici/oncall agent/WeKnora/internal/types/search.go`、`/Users/cici/oncall agent/WeKnora/internal/types/retriever.go` | 复核 `SearchParams`、`RetrieveParams`、`SearchResult`、`IndexWithScore` |
| search service | `/Users/cici/oncall agent/WeKnora/internal/application/service/knowledgebase_search.go` | 复核 `HybridSearch` 的检索参数构造、召回和结果处理层次 |
| result assembly | `/Users/cici/oncall agent/WeKnora/internal/application/service/knowledgebase_search_results.go` | 复核批量取回 chunk/knowledge 元数据并装配 `SearchResult` 的流程 |
| shared lookup | `/Users/cici/oncall agent/WeKnora/internal/application/service/knowledgebase_search_shared.go` | 复核跨 KB/共享访问的补查思路，首版只保留可裁剪意识 |
| Agent search tool | `/Users/cici/oncall agent/WeKnora/internal/agent/tools/knowledge_search.go` | 复核工具输入输出、query shape、结构化结果传递 |
| Agent chunk tool | `/Users/cici/oncall agent/WeKnora/internal/agent/tools/list_knowledge_chunks.go` | 复核按 document/knowledge ID 读取完整 chunk 的工具形态 |
| Agent document info tool | `/Users/cici/oncall agent/WeKnora/internal/agent/tools/get_document_info.go` | 复核批量查文档元数据、状态、chunk 数的工具形态 |
| knowledge API | `/Users/cici/oncall agent/WeKnora/docs/api/knowledge.md` | 复核上传、解析状态、文件元数据、重新解析 API 语义 |

## 3. 采用清单

这些内容应进入后续 P1/P2 实现或成为实现的直接语义来源。

| 采用项 | 采用方式 | 落到主项目的位置 |
|---|---|---|
| `KnowledgeBase -> Knowledge -> Chunk` 三层领域模型 | 采用分层语义，不复制 GORM 结构 | `app/models/knowledge.py` 或等价模型文件 |
| `KnowledgeBase.ChunkingConfig` | 采用 `chunk_size/chunk_overlap/separators/parser_engine_rules`，预留 `strategy` | `KnowledgeBaseConfig` / 配置默认值 |
| `ParserEngineRule` 与 `ResolveParserEngine()` | 采用按文件类型选择 parser engine 的规则 | `ParserEngineRouter` |
| `Knowledge.ParseStatus` 状态流 | 采用 `pending/processing/completed/failed` 对外映射思路 | 映射到契约状态: `parse_pending/parsing/parsed/parse_failed` |
| `Knowledge` 文件元数据 | 采用 `file_name/file_type/file_size/file_path/error_message/metadata` | `DocumentRecord` |
| `Chunk` 基本字段 | 采用 `id/knowledge_id/kb_id/content/chunk_index/start/end/metadata` | `ChunkRecord` 和 Milvus metadata |
| `ContextHeader` | 采用其“用于 embedding 的标题上下文，不破坏正文内容”的语义 | `heading_path` / `source_ref.heading_path` |
| `DocReader.Read(ReadRequest) -> ReadResult` | 采用 parser adapter 的统一接口形态 | `ParserAdapter.parse()` / `ParseResult` |
| `ParserEngineInfo` | 采用 `name/file_types/available/unavailable_reason` 描述方式 | parser 可用性检查与错误消息 |
| `SimpleFormatReader` 的 md/txt 原生处理 | 采用简单格式不走外部 parser 的思路 | 旧 md/txt 上传兼容路径 |
| `MinerUReader` 的 endpoint/overrides 边界 | 采用 self-hosted MinerU adapter 的配置形态 | `MinerUParserAdapter` |
| chunk service 的批量创建/按文档删除 | 复制其 service / repository 形状后做最小修改 | `KnowledgeMetadataStore` / `VectorIndexService` |
| `knowledge_process.go` 的幂等清理 | 采用“写新 chunk 前先清旧 chunk/旧索引”的流程 | 重传同文档时按 `doc_id` 或 `_source` 清理 |
| `SearchParams` / `RetrieveParams` | 采用 query、kb scope、doc scope、topK、filter 的参数结构 | `RetrievalQuery` |
| `SearchResult` | 采用 content、knowledge_id、chunk_id、score、metadata、file_name、kb_id 的结果语义 | `retrieve_knowledge_v2` artifact |
| `processSearchResults` | 采用召回后补齐 knowledge/chunk 元数据的层次 | `RetrievalServiceV2` |
| Agent knowledge tools 的结构化输出 | 采用工具返回文本 + 结构化 data 的形态 | `retrieve_knowledge` / 未来 `retrieve_knowledge_v2` |

## 3.5 按“直接用 / 复制后最小修改”口径的判定

| WeKnora 来源 | 判定 | 原因 |
|---|---|---|
| `internal/types/knowledgebase.go`、`knowledge.go`、`chunk.go`、`search.go`、`retriever.go` | 复制后最小修改 | 这些是 Go 类型，不能直接接入当前 Python/FastAPI 主仓库；但字段、状态和值对象结构应尽量照搬。 |
| `docreader/parser/base_parser.py`、`docreader/models/document.py` | 复制后最小修改 | Python 代码可直接成为主仓库 parser 基类雏形，但需要最小修改导入路径和 artifact contract 字段。 |
| `docreader/parser/registry.py` | 复制后最小修改 | 结构可复用，但默认把 PDF/DOCX/XLSX 指向 `MarkItDown` / 内置 parser，不符合本项目 `MinerU-first`。 |
| `internal/infrastructure/docparser/mineru_converter.go` | 复制后最小修改 | 不能直接运行在 Python 主链路中，但请求参数、响应兼容、超时和图片处理逻辑适合按原样迁入 Python adapter。 |
| `internal/infrastructure/docparser/builtin_converter.go` | 不直接采用代码 | 当前主仓库已有 md/txt 路径，且这份代码是 Go 实现；这里只保留处理原则。 |
| `internal/infrastructure/chunker/strategy.go`、`splitter.go` | 暂不采用 | P1/P2 已有 `pdf_eval` 产物契约，不应现在引入第二套 chunking 主链路。 |
| `internal/application/service/chunk.go`、`knowledge_process.go` | 复制后最小修改 | 不能直接用 Go service，但 service/repository 分层和幂等清理流程应尽量保留。 |
| `internal/application/service/knowledgebase_search*.go` | 复制后最小修改 | 不能直接运行，但 DTO 和 result assembly 分层应按原实现搬到 Python 侧。 |
| `internal/agent/tools/*.go` | 暂不采用 | 当前只需要增强主仓库已有 `retrieve_knowledge`，不复制整套 Agent 工具。 |

## 4. 裁剪清单

这些内容成熟，但当前主项目只吸收边界或语义，必须裁剪到 P1/P2 所需的最小形态。

| 裁剪项 | 为什么裁剪 | 首版保留什么 |
|---|---|---|
| Go/GORM 模型实现 | 主项目是 Python/FastAPI，不应引入 Go 持久化栈 | 字段语义和状态机 |
| 多租户 `TenantID` | 当前主项目没有完整 tenant/organization 权限体系 | `kb_id` 先固定或默认 `default` |
| FAQ/Wiki 知识库类型 | P1/P2 只做文档型 RAG | `KnowledgeBaseTypeDocument` 语义 |
| storage provider / COS / S3 / OSS | 当前文件先落本地 artifact 目录 | `original_path`、`artifact_dir` |
| VLM/ASR / 多模态图片音频 | P1/P2 不扩多模态 | metadata 扩展位 |
| WeKnoraCloud / MinerU Cloud | 当前用本地 MinerU 与 `pdf_eval` 产物 | `mineru_endpoint` 形态可预留 |
| Python docreader `markitdown` 默认链 | 本项目已有 MinerU > Docling > OpenDataLoader 的评估结论 | 仅保留“registry/fallback”思路 |
| asynq 异步任务 | 首版要先跑通最小闭环 | 同步执行，状态可映射为 pending/processing/completed/failed |
| parent-child chunking | 会扩大实现面，也可能影响已有 `chunks.json` 语义 | 预留 `parent_chunk_id` 字段，不启用 |
| hybrid search / RRF / rerank | P1/P2 先解决证据与 citation | 接口预留，首版 dense search + metadata enrich |
| shared KB 权限补查 | 当前没有对应组织权限模型 | 只保留批量补齐 metadata 的模式 |
| Agent 多工具体系 | 当前 RAG/AIOps 已有工具入口 | 先增强 `retrieve_knowledge` artifact，不重做 Agent 工具集 |

## 5. 暂不采用清单

这些内容暂不进入 P1/P2，避免开发范围失控。

| 暂不采用项 | 原因 | 未来进入条件 |
|---|---|---|
| 完整 WeKnora 服务嵌入 | 部署、Go 服务、前端、数据库和鉴权牵连过大 | P1-P5 语义跑通后再评估 P6 |
| 完整 Go chunker 移植 | 当前 `pdf_eval` 已有可用 `chunks.json`，贸然替换会引入回归 | 需要主项目内置 chunker 且有回归集 |
| GraphRAG / entity / relationship chunk | 非 P1/P2 目标 | 基础 citation 和评测稳定后 |
| FAQ import / FAQ chunk diff | 当前不是 FAQ 知识库产品化阶段 | 明确要做 FAQ 知识库时 |
| Wiki 模式 | 不服务当前 oncall RAG 最小闭环 | 后续产品化知识库需要 Wiki 时 |
| 多模态图片 OCR chunk | 目前解析重点是 PDF/Office 文本和表格 | 图片引用成为关键问答需求时 |
| keyword retriever / BM25 / RRF | 会遮蔽 P1/P2 的 artifact 和 citation 问题 | dense + citation 基线稳定后 |
| rerank 模型 | 需要额外模型配置与评测 | 有固定检索回归集后 |
| 跨租户共享 KB | 当前主项目没有权限模型 | tenant/user/role 模型确定后 |

## 6. P1/P2 实现前置检查

进入 P1/P2 实现前必须满足:

1. 不修改 WeKnora 源码作为本项目运行依赖。
2. 先判断是否可直接使用；不能直接使用时，优先复制 WeKnora 代码到主仓库后做最小修改，而不是自己重写。
3. 不直接读取 `pdf_eval/outputs/` 的历史实验结果作为运行时输入。
4. `docs/rag_ingestion_artifact_contract.md` 的六件套 artifact 仍是 P2 的硬约束。
5. 每个新增模块都能说明对应的 WeKnora 来源文件和裁剪理由。
6. 旧 `md/txt` 上传路径必须保留。
7. PDF/DOCX/XLSX 不得进入普通文本读取路径。

## 7. P1/P2 建议开发顺序

R0 完成后，后续实现应按下面顺序推进:

```text
P1-1. 最小模型
      参考 KnowledgeBase / Knowledge / Chunk 字段，建立 Python 最小模型。

P1-2. Metadata store
      参考 KnowledgeRepository / ChunkRepository 能力，只做本地最小存储接口。

P1-3. md/txt 兼容索引
      参考 SimpleFormatReader，保持旧上传行为，同时写入 kb_id/doc_id/chunk_id/source_ref。

P2-1. ParserEngineRouter
      参考 ParserEngineRule / ResolveParserEngine / engine registry，建立文件类型路由。

P2-2. MinerUParserAdapter
      参考 MinerUReader 的 adapter 边界，但产物必须符合 artifact contract。

P2-3. ChunkBuilder / Indexer
      消费 chunks.json 与 tables.json，写入 Milvus metadata，按 doc_id 幂等清理。

P2-4. Retrieval citation
      参考 SearchResult / processSearchResults，先让 retrieve_knowledge 返回结构化 source_ref。
```

## 8. R0 结论

R0 已确认: WeKnora 里有足够成熟的领域对象、parser registry、chunk service、retrieval result 和 Agent 工具边界可复用。后续 P1/P2 不应自造并行链路，而应按本报告的采用、裁剪和暂不采用清单做最小适配。

下一步可以进入 P1 的“最小模型 + metadata store + md/txt 兼容索引”实现，但实现前仍要先读本报告和 `docs/rag_ingestion_artifact_contract.md`。

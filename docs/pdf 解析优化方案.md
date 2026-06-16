# PDF 解析优化方案

## 1. 结论

当前 SuperBizAgent 的 PDF 解析链路已经不是 Demo 级实现。项目已经具备:

- `.pdf/.docx/.xlsx -> mineru`、`.md/.txt -> plain_text` 的解析路由。
- 上传后保存原件、创建 `DocumentRecord`、投递异步 worker 的生命周期。
- MinerU 后处理产出 `artifact_manifest.json`、`cleaned.md`、`chunks.json`、`tables.json`、`blocks.json`、`quality_report.json` 六件套。
- `chunks.json` 和 `tables.json` 进入索引前会转成 `ChunkRecord`，并携带 `source_ref`。
- 检索结果已经有 `source_ref`、`citation_text`、`chunk_evidence` 和部门 RAG eval 的 source_ref integrity 检查。

但如果按生产级 PDF RAG / Agent PDF 能力衡量，还缺四类关键能力:

1. PDF 类型诊断不够细，当前主要按后缀进入 MinerU，没有显式区分原生文本 PDF、扫描 PDF、图文混排 PDF。
2. `quality_report.json` 已存在，但还没有形成足够强的 OCR、表格、图片、页码准确性指标。
3. Agent 工具链仍以 `retrieve_knowledge` 为主，没有独立的 `read_page`、`extract_table`、`analyze_chart`、`source` 类工具。
4. 评测闭环已有 RAG eval，但还没有 PDF parser 专项 eval，例如页码准确率、表格解析准确率、OCR 字符质量、图表说明质量。

因此优化路线不建议推倒重做 Parser。推荐在现有 MinerU-first 和 artifact contract 上增量加深:

```text
P0 固化当前基线
-> P1 PDF 类型诊断和质量报告增强
-> P2 artifact schema 与 postprocess 收口
-> P3 表格和页码可用性增强
-> P4 Agent PDF 工具链
-> P5 PDF 专项评测门禁
-> P6 多模态图表理解和长期观测
```

第一阶段目标不是“换一个更强 PDF 解析器”，而是让系统能稳定回答:

```text
这份 PDF 是什么类型？
解析出了哪些结构？
页码和表格是否可信？
为什么没有命中？
Agent 能不能按页、按表、按来源回查？
```

## 2. 当前项目事实

### 2.1 已有主链路

当前主链路如下:

```text
POST /api/upload
-> UploadAdapter
-> DocumentIngestionService.ingest_upload()
   - 保存原始文件
   - 生成 kb_id / doc_id / artifact_dir
   - ParserEngineRouter.resolve(file_ext)
   - plain_text: 同步索引
   - mineru: 投递 DocumentProcessingQueue
-> document_processing_worker
-> DocumentProcessingWorkflow.process_deferred_document()
-> MinerUParserAdapter.parse_document()
   - 调用 MinerU CLI
   - 调用 pdf_eval/scripts/mineru_postprocess.py
   - 写 artifact manifest
-> VectorIndexService.index_document_record()
-> ArtifactChunkBuilderService.prepare()
   - 读取 chunks.json
   - 读取 tables.json
   - 读取 quality_report.json
-> ChunkPolicyService.apply_with_parents()
-> Milvus + KnowledgeMetadataStore
-> RetrievalService / retrieve_knowledge
```

关键代码位置:

| 能力 | 当前落点 |
|---|---|
| 文件上传 API | `app/api/file.py` |
| 接入服务 | `app/services/document_ingestion_service.py` |
| parser 路由 | `app/services/parser_engine_router.py` |
| 异步队列 | `app/services/document_processing_queue.py` |
| 生命周期工作流 | `app/services/document_processing_workflow.py` |
| MinerU adapter | `app/services/mineru_parser_adapter.py` |
| artifact manifest | `app/services/artifact_manifest_service.py` |
| artifact 转 chunk | `app/services/artifact_chunk_builder_service.py` |
| 最终 chunk policy | `app/services/chunk_policy_service.py` |
| 检索证据映射 | `app/services/chunk_evidence_mapper.py` |
| 结构化检索 | `app/services/retrieval_service.py` |
| Agent 知识工具 | `app/tools/knowledge_tool.py` |
| RAG eval | `evals/knowledge_base/run_department_rag_eval.py` |

### 2.2 已有优势

当前项目已经做对的部分:

- PDF 不会静默走普通文本路径。
- PDF 解析和索引是异步状态机，而不是同步假成功。
- artifact 文件名和职责已经固定。
- 表格有独立 `tables.json`，不是混在正文里完全丢失结构。
- source_ref 已经贯穿 chunk、检索结果、tool artifact 和 eval。
- RAG eval 已经能识别 `data_not_indexed`、`answer_wrong`、`citation_missing`、`wrong_scope`。

### 2.3 当前短板

当前短板主要在产品化深度，不在主链路是否存在:

| 短板 | 现状 | 影响 |
|---|---|---|
| PDF 类型诊断 | 后缀路由为主 | 无法解释扫描件、图文混排失败原因 |
| OCR 指标 | 只有通用 `quality_report` | 无法判断 OCR 是否漏字或乱码 |
| 表格质量 | 有 rows/markdown/quality_flags | 缺表格准确率、跨页表格、合并单元格专项处理 |
| 图片图表 | postprocess 可保留图片路径和 caption | 没有视觉模型理解图表内容 |
| Agent 工具 | 主要是 `retrieve_knowledge` / `list_knowledge_documents` | 不能稳定按页读、抽表、看图、回源 |
| eval | 有 RAG eval | 缺 parser 专项 eval 和导入放行门 |

## 3. 目标和非目标

### 3.1 目标

本方案要补齐的是 PDF 解析到 Agent RAG 的生产可解释性:

- 解析前能识别 PDF 类型和风险。
- 解析后能解释正文、表格、图片、页码、标题层级的产出情况。
- 索引前能用 schema 和质量门禁阻止坏 artifact 入库。
- 检索后能稳定回查 `kb_id/doc_id/chunk_id/page/heading/source_file`。
- Agent 能按需调用检索、按页阅读、表格抽取、来源回查。
- eval 能分别衡量检索命中、页码正确、表格正确、OCR 质量、引用可解析。

### 3.2 非目标

第一轮优化不做:

- 不推倒现有 MinerU-first 路线。
- 不把 PDF/DOCX/XLSX 回退到普通文本读取。
- 不接完整 WeKnora 服务。
- 不直接做 GraphRAG。
- 不把所有图片都送多模态模型做高成本解析。
- 不在 reviewed import 和小样本 eval 仍未稳定前扩大全量导入。
- 不把 `quality_report.json` 直接向量化。

## 4. 分阶段方案

## P0: 固化当前基线

### 目标

先明确当前链路能跑什么、不能跑什么，避免后续优化无法判断是否回归。

### 必做项

1. 固定一组 PDF 样本。
   - 原生文本 PDF。
   - 扫描 PDF。
   - 图文混排 PDF。
   - 长表格 PDF。
   - 多栏版式 PDF。
   - 当前已知失败样本，例如部门知识库中 `index_failed` 的 PDF。

当前仓库内的 P0 baseline 样本先按真实存在文件固定为下表。若某类样本暂缺，必须显式写 `no_sample_available`，不能在 baseline 报告中留空。

| 样本类型 | baseline 样本 | 当前处理方式 | 说明 |
|---|---|---|---|
| 原生文本 PDF | `原始文件/05_调研记录/crrc_changchun_20260603/downloads/2023_中车长春轨道客车_友商合规承诺书中英对照.pdf` | 作为 native_text 候选样本跑 profile 后确认 | 文件较小，适合验证文本层、双语内容和普通页码引用 |
| 扫描 PDF | `no_sample_available` | 暂缺时不伪造样本；用 mixed 样本覆盖风险检查 | 后续若新增真实扫描件，必须补入 manifest |
| 图文混排 PDF | `原始文件/05_调研记录/crrc_changchun_20260603/downloads/2025_中车长春轨道客车_监测报告.pdf` | 作为 mixed_layout 候选样本跑 profile 后确认 | 文件较大，适合验证图片、表格、页码和长文档解析风险 |
| 长表格 PDF | `原始文件/05_调研记录/crrc_changchun_20260603/downloads/2024_中车长春轨道客车_土壤地下水自行监测方案.pdf` | 作为 table-heavy 候选样本跑 tables eval | 适合验证监测数据表、表格 rows 和表格页码引用 |
| 多栏版式 PDF | `原始文件/09_PDF解析基线/多栏版式/N19-1423_bert_pretraining_two_column.pdf` | 作为 multi_column_pdf 样本跑 profile、blocks page coverage 和文本层抽取检查 | ACL Anthology 双栏论文 PDF，16 页、未加密、文本层可抽取，来源记录见同目录 `README.md` |
| 已知失败 PDF | `uploads/documents/craft_dept/doc_27b282ca-97c3-5170-af0a-282f2e9122a1/original/线上故障处理_现场设备工艺版.pdf` | 作为 regression_failure 样本 | `data/knowledge_ingestion/current_import_state.json` 中记录为 `index_failed` |

P0 baseline manifest 至少要包含:

```text
sample_id
sample_type
relative_path
kb_id
expected_pdf_kind
expected_status
known_gap
notes
```

2. 为每个样本建立 baseline 记录。
   - 是否能进入 `parse_pending`。
   - 是否能进入 `indexed`。
   - artifact 六件套是否齐全。
   - `chunks.json` 数量。
   - `tables.json` 数量。
   - `quality_report.json` 的 warning / fatal 信息。
   - RAG eval 是否命中期望文档。

3. 固定现有回归命令。
   - artifact builder 测试。
   - document workflow 测试。
   - retrieval / evidence mapper 测试。
   - department RAG eval。

4. 增加 MinerU CLI 健康检查。
   - 在跑任何 PDF baseline 前，先检查 `config.mineru_cli_path` 指向的 MinerU CLI 是否存在、可执行。
   - 用一个已知可解析的小 PDF 做 smoke，记录 `cli_path`、返回码、耗时、`parser_version`、`postprocess_script_path` 和是否产出 `content_list`。
   - 如果健康检查失败，P0 报告必须标为 `mineru_unavailable`，不能把后续 PDF 失败误判为样本文档本身的问题。
   - 健康检查只验证外部依赖可用性，不改变 parser 参数和解析行为。

### 验收标准

- 每个样本都有一条 baseline row。
- baseline 能区分 parser 失败、index 失败、retrieval no hit、answer wrong。
- 没有新增任何 parser 行为变化。

### 建议产物

```text
data/pdf_parser_eval/pdf_samples_manifest.tsv
data/pdf_parser_eval/baseline_report.json
data/pdf_parser_eval/baseline_report.md
```

## P1: PDF 类型诊断和质量报告增强

### 目标

在进入 MinerU 前，先生成轻量级 `pdf_profile`，并只写入 `DocumentRecord.metadata.pdf_profile`。`pdf_profile_service` 不直接写 `quality_report.json` 或其他 parser artifact，避免 pre-parse 诊断模块穿透 parser/postprocess 职责。

等 MinerU / postprocess 正式产出 artifact 后，再由 parser/postprocess 路径把 `pdf_profile` 摘要合并进 `quality_report.json`，用于后续 QA、eval 和人工诊断。

### 推荐新增字段

`DocumentRecord.metadata.pdf_profile`:

```json
{
  "pdf_kind": "native_text | scanned | mixed | unknown",
  "page_count": 12,
  "extractable_text_pages": 10,
  "image_heavy_pages": 2,
  "has_tables": true,
  "has_images": true,
  "has_toc": false,
  "risk_flags": ["mixed_layout", "possible_scanned_pages"],
  "profiler_version": "pdf_profile_v1"
}
```

### 实现建议

新增模块:

```text
app/services/pdf_profile_service.py
```

第一版只做轻量检测:

- 当前项目尚未引入 `pypdf`、PyMuPDF 或 pdfplumber 运行时依赖。第一版优先评估 `pypdf`，用于页数、加密状态、文本层抽样等低风险诊断；如确实需要图片对象密度、复杂页面对象统计，再单独评估 PyMuPDF 的许可证和部署影响。
- 抽样检测每页可提取文本长度。
- 根据页面文本密度先判断 image-heavy 风险；图片对象数量检测作为后续增强，不作为 P1 首版硬依赖。
- 不做昂贵 OCR。
- 不改变 parser 路由，只补诊断。

### 状态策略

- `pdf_profile` 失败不直接阻断上传。
- 但必须写 warning 到 metadata。
- 如果 PDF 文件损坏、无法打开、页数为 0，则阻断并进入 `parse_failed` 或 `upload_failed`，不能继续投递 MinerU。
- `pdf_profile_service` 只负责 pre-parse 诊断和 metadata 更新，不创建、不覆盖、不修补 `artifact_manifest.json`、`quality_report.json`、`chunks.json`、`tables.json` 或 `blocks.json`。
- `risk_flags` 只用于诊断、展示和 eval 分组，不能被下游自动解释为“跳过检索”或“拒绝回答”。任何自动阻断都必须来自明确的 fatal 条件，例如文件损坏、页数为 0、artifact 必需文件缺失或 schema fatal。

### 验收标准

- 原生文本 PDF 能识别为 `native_text` 或低风险。
- 扫描 PDF 能识别为 `scanned` 或 `possible_scanned_pages`。
- 图文混排 PDF 能识别为 `mixed` 或 `mixed_layout`。
- `GET /api/documents/{doc_id}` 能看到 pdf_profile 或对应诊断。
- 不影响 `.md/.txt` 路径。

## P2: Artifact schema 与 postprocess 收口

### 目标

把 `chunks.json`、`tables.json`、`blocks.json`、`quality_report.json` 从“约定字段”加固为“可验证 schema”，减少坏产物进入索引。

### 必做项

1. 为 artifact 增加 Pydantic model 或等价 validator。
   - `ParsedBlock`
   - `ParsedTextChunk`
   - `ParsedTable`
   - `ParsedQualityReport`

2. 加强 `ArtifactChunkBuilderService.prepare()`。
   - 校验每个 chunk 的 `id/text/pages/heading_path/block_ids/block_types`。
   - 校验每个 table 的 `table_id/rows/markdown/page_start/page_end/source_ref`。
   - 校验页码范围合法。
   - 校验空正文、空表格、过长表格的处理策略。

3. 加强 `quality_report.json`。
   - 增加 `fatal_errors`。
   - 增加 `warnings`。
   - 增加 `ocr_risk_flags`。
   - 增加 `table_quality_flag_counts`。
   - 增加 `page_coverage`。
   - 增加 `image_count`、`table_count`、`heading_count`。

### 关键原则

`quality_report.warnings` 不阻断入库，`quality_report.fatal_errors` 必须阻断入库。

### 渐进启用策略

validator 首版必须先以 warning-only 模式运行，不能第一天直接把历史 artifact 大面积判成失败。执行顺序:

1. 先跑 P0 baseline 样本，记录每类 artifact 的字段缺失、页码缺失、表格 rows 异常和 quality warning。
2. 再扫描现有 `uploads/documents/*/*/artifacts/` 中已存在的 artifact，统计 schema pass / warning / fatal candidate 比例。
3. 只有历史 artifact 的 schema pass rate 超过 95%，并且 fatal candidate 已人工归类后，才允许把必需字段缺失、manifest 状态错误、`quality_report.fatal_errors` 等条件切成 fatal。
4. `artifact_manifest.json` 已记录 `parser_version` 和 `postprocess_version`，validator 必须按版本选择兼容 schema，不能默认所有历史 artifact 都是同一版格式。

### 验收标准

- 缺少 artifact 文件时不能入库。
- `quality_report.fatal_errors` 非空时不能入库。
- 坏 table row 不会悄悄变成普通 text chunk。
- schema 错误能在文档状态中看到明确原因。

## P3: 表格和页码可用性增强

### 目标

让 PDF RAG 能回答“表格里的值来自哪里”，并让页码引用稳定可用。

### 表格优化

第一版聚焦三个能力:

1. 表格可回查。
   - 每个 table chunk 必须有 `table_id`。
   - 每个 table chunk 必须有 `page_start/page_end`。
   - 每个 table chunk 必须保留 `rows` 到 metadata 或 metadata store。

2. 表格质量可解释。
   - `ragged_rows`
   - `empty_cells`
   - `header_only`
   - `possible_merged_cells`
   - `possible_cross_page_table`

3. 表格检索可用。
   - 表格 markdown 用于检索。
   - 结构化 rows 用于 `extract_table` 工具或 API。
   - 不把 `quality_report` 本身向量化。

### 页码优化

页码策略:

- `source_ref.page_start/page_end` 是回答引用的唯一页码来源。
- `citation_text` 是展示文本，不作为结构化消费入口。
- 如果页码缺失，允许入库但必须带 `quality_flags=["missing_page"]`。
- eval 中把页码缺失和页码错误分开统计。

### 验收标准

- 检索命中表格时，artifact 返回 `content_type` 为 table / manual_table / parameter_table 等表格类型。
- table chunk 能回查原始 `table_id` 和 rows。
- 页码引用能在 `source_ref` 中稳定出现。

## P4: Agent PDF 工具链

### 目标

把 PDF 能力从“只靠 retrieve_knowledge”扩展为 Agent 可按需调用的工具集。

### 推荐工具

第一版新增工具不要过多，先补三个:

| 工具 | 作用 | 输入 | 输出 |
|---|---|---|---|
| `read_document_page` | 按页读取清洗后的 blocks/chunks | `doc_id`, `page` | page text, source_ref list |
| `extract_document_table` | 按 table_id 或页码抽表 | `doc_id`, `table_id` 或 `page` | rows, markdown, source_ref, quality_flags |
| `get_document_source` | 根据 source_ref 回源 | `kb_id`, `doc_id`, `chunk_id` | chunk, parent, source_ref, document metadata |

`analyze_chart` 先不放入第一版强制目标。等 P5 的图片样本和图表评测集稳定后再接入多模态模型。

`get_document_source` 是 P4b 工具，不进入第一轮最小切片。第一轮先复用现有 `source_ref`、`ChunkEvidenceMapper`、metadata store 回查和 PDF eval 验证“引用可解析”的语义；等 `read_document_page`、`extract_document_table` 和 `source_ref_resolvable_rate` 稳定后，再把回源能力包装成独立工具，避免过早新增一个和 citation/evidence 语义重复的读取入口。

### 工具开发前置门

`read_document_page` 依赖 `blocks.json` 的 page 字段，不能在页码产物未确认时直接开发。进入 P4 前必须先完成:

1. 对 P0 baseline 中所有可用 PDF 样本检查 `blocks.json`。
2. 统计每个样本的:
   - `block_count`
   - `blocks_with_page_count`
   - `blocks_missing_page_count`
   - `page_min/page_max`
   - `page_coverage_rate`
3. 对至少一个已知页码问题做人工抽查，确认 `block.page` 与 PDF 页码一致。
4. 如果 `page_coverage_rate < 0.95` 或人工抽查发现页码偏移，`read_document_page` 必须阻塞，只允许先修 P2/P3 的页码策略。

`extract_document_table` 同理依赖 `tables.json` 的 `table_id/page_start/page_end/rows`。如果表格样本中 `rows` 为空或 `page_start` 缺失，先修 artifact schema 和 table postprocess，不提前暴露工具。

### 工具边界

- 工具必须经过现有 `ToolExecutionFacade` / 权限体系接入，不能绕过 `DocumentAccessService`。
- 工具读取 artifact 前，必须先通过 metadata store 找到 `DocumentRecord`，再调用当前项目已有的 `DocumentAccessService.can_read_document(context, document)`。不能只检查 `doc_id` 是否存在，也不能直接按文件路径读取 artifact。
- 工具只读取当前用户可见文档；admin / public document / document grant / knowledge_base grant 的语义沿用 `DocumentAccessService`，不要为 PDF 工具另写一套权限判断。
- 工具返回结构化 artifact，不只返回自然语言。
- `read_document_page` 不应直接读取原始 PDF 文件做新解析，优先消费已产出的 `blocks.json`。

### 验收标准

- 用户问“看第 3 页”时不需要向量检索也能回源。
- 用户问“这张表有哪些字段”时能返回 table rows。
- 用户问“这个回答引用来自哪里”时能用 `source_ref` 回查 chunk。
- 未授权文档不能通过这些工具泄露。

## P5: PDF 专项评测门禁

### 目标

把 PDF 解析质量从“主观感觉”变成可重复跑的报告。

### Eval 维度

| 维度 | 指标 | 说明 |
|---|---|---|
| parser_success | parse_success_rate | 样本是否成功产出六件套 |
| index_success | index_success_rate | 是否进入 `indexed` |
| citation | source_ref_resolvable_rate | source_ref 是否能回查 chunk |
| page | page_accuracy | 命中结果页码是否在期望页范围 |
| table | table_value_accuracy | 表格值是否抽取正确 |
| retrieval | expected_doc_hit_rate | query 是否命中期望 doc |
| answer | answer_keyword_score | context 是否包含期望关键词 |
| scope | wrong_scope_rate | 是否跨部门或越权命中 |
| ocr | ocr_quality_flag_rate | OCR 风险标记比例 |

### Evalset 设计

建议新增:

```text
evals/pdf_parser/evalsets/pdf_parser_smoke_12q.jsonl
evals/pdf_parser/evalsets/pdf_table_qa_10q.jsonl
evals/pdf_parser/evalsets/pdf_page_citation_10q.jsonl
```

每条样本至少包含:

```json
{
  "sample_id": "pdf_page_001",
  "doc_id": "doc_xxx",
  "kb_id": "process_digital_dept",
  "query": "某某流程第 3 页说明了什么？",
  "expected_doc_ids": ["doc_xxx"],
  "expected_page_range": [3, 3],
  "expected_keywords": ["..."],
  "expected_table_values": [],
  "expected_failure_allowed": false
}
```

### 评分规则

第一版 PDF parser eval 不依赖最终 LLM 回答，优先评估 retrieval / artifact / tool artifact。后续 live-agent eval 可以在同一报告中增加最终回答评分，但不能替代 parser 专项指标。

| 指标 | 评分规则 | 失败分类 |
|---|---|---|
| `parse_success_rate` | 文档状态进入 `parsed`、`index_pending`、`indexing` 或 `indexed`，且 artifact 六件套存在 | `parse_failed` / `artifact_missing` |
| `index_success_rate` | 文档状态为 `indexed`，且 metadata store 中存在该 doc 的 chunk | `index_failed` / `data_not_indexed` |
| `source_ref_resolvable_rate` | 每个检索结果的 `source_ref.kb_id/doc_id/chunk_id/source_file` 完整，且能在 metadata store 回查 chunk | `citation_missing` |
| `page_accuracy` | 任一命中结果满足 `source_ref.page_start <= expected_end` 且 `source_ref.page_end >= expected_start`；单页样本等价于页码范围重叠 | `page_missing` / `page_wrong` |
| `table_value_accuracy` | `extract_document_table` 返回的 normalized rows 中包含 `expected_table_values`；第一版 exact match，第二版再加 fuzzy match | `table_missing` / `table_value_wrong` |
| `expected_doc_hit_rate` | `actual_doc_ids` 与 `expected_doc_ids` 有交集 | `answer_wrong` / `retrieval_no_hit` |
| `answer_keyword_score` | `RetrievalResponse.context_text` 中包含 `expected_keywords` 的比例；live-agent 模式另算 `final_answer_keyword_score` | `answer_wrong` |
| `wrong_scope_rate` | 命中结果的 `kb_id` 不在 `allowed_kb_ids` 内则失败 | `wrong_scope` |
| `ocr_quality_flag_rate` | 命中 chunk 或文档 `quality_flags` 中 OCR 风险标记的占比；超过阈值不一定失败，但必须进入 warning | `ocr_risk` |

页码判断必须使用结构化 `source_ref.page_start/page_end`，不能从 `citation_text` 字符串里解析。`expected_keywords` 默认匹配检索上下文，不匹配 `quality_report.json`、`blocks.json` 或其他未进入回答上下文的调试产物。

### 放行门

第一版门禁建议:

- `parse_success_rate >= 90%`
- `index_success_rate >= 90%`
- `source_ref_resolvable_rate = 100%`
- `wrong_scope_rate = 0%`
- 表格专项 eval 未通过时，不允许宣称“表格解析已完成”
- 图表专项 eval 未建立前，不允许宣称“图表理解已完成”
- 即使 P6 多模态暂缓，P5 也必须至少包含 1 道图表或图片相关样本题，用来暴露“当前只能处理 caption / 图片占位，不能理解图表内容”的真实缺口。

### 验收标准

- 每次修改 parser/postprocess/chunk policy 后能跑 PDF eval。
- 报告能区分 parser 失败、index 失败、retrieval 失败、citation 失败、answer 错误。
- 报告路径写入 `PROJECT_STATE.md` 或阶段开发记录。

## P6: 多模态图表理解和长期观测

### 目标

在基础链路稳定后，再补图表视觉理解，不提前扩大成本和复杂度。

### 触发条件

同时满足以下条件再进入 P6:

- P0 到 P5 已完成。
- PDF eval 中图表类样本明确失败。
- 用户真实问题需要图表内容，而不只是图片 caption。
- 已有成本和延迟预算。

### 方案

1. 从 `blocks.json` 中提取 image block。
2. 为每个 image block 建立 `image_ref`。
3. 对高价值图片调用多模态模型生成 `image_caption` 或 `chart_summary`。
4. 把摘要作为独立 chunk 入库，content_type 使用:
   - `image_caption`
   - `chart_summary`
   - `diagram_summary`
5. `source_ref` 必须指向原始 doc、page、image block。

### 不允许

- 不允许把所有图片无差别送模型。
- 不允许没有 source_ref 的图表摘要入库。
- 不允许把模型生成的图表解释伪装成原文。

## 5. 推荐执行顺序

| 阶段 | 优先级 | 是否建议现在做 | 原因 |
|---|---:|---:|---|
| P0 基线 | P0 | 是 | 没有 baseline 无法判断优化收益 |
| P1 PDF 类型诊断 | P0 | 是 | 成本低，能解释失败原因 |
| P2 schema 收口 | P0 | 是 | 防止坏 artifact 入库 |
| P3 表格页码增强 | P1 | 是 | 与 PDF RAG 用户体验直接相关 |
| P4 Agent PDF 工具 | P1 | 是 | 补齐面试和产品演示能力 |
| P5 PDF eval | P1 | 是 | 形成质量闭环 |
| P6 多模态图表 | P2 | 暂缓 | 成本和不确定性较高 |

## 6. 第一轮最小实现切片

如果只做一个最小闭环，建议按下面 5 个任务执行:

```text
1. 增加 pdf_profile_service，只写 metadata，不改解析结果。
2. 为 artifact 加 validator，先覆盖 chunks/tables/quality_report。
3. 增加 read_document_page 和 extract_document_table 两个只读工具。
4. 增加 pdf_page_citation 和 pdf_table_qa 小 evalset，先用 eval 验证 source_ref 可回查；get_document_source 延后到 P4b。
5. 跑现有 RAG 回归 + 新 PDF eval，形成报告。
```

第一轮不要做:

- 不改 MinerU CLI 参数策略。
- 不引入新的 PDF parser。
- 不做全量多模态图片理解。
- 不扩大 reviewed import。

## 7. 验证清单

### 单元测试

建议新增或扩展:

```text
tests/test_pdf_profile_service.py
tests/test_artifact_schema_validation.py
tests/test_pdf_page_tool.py
tests/test_pdf_table_tool.py
tests/test_pdf_parser_eval_runner.py
```

### 回归测试

必须继续跑:

```text
uv run pytest tests/test_artifact_chunk_builder_service.py -q --no-cov
uv run pytest tests/test_document_processing_workflow.py tests/test_document_processing_queue.py tests/test_document_ingestion_service.py -q --no-cov
uv run pytest tests/test_chunk_evidence_mapper.py tests/test_retrieval_service.py tests/test_knowledge_search_diagnostics.py -q --no-cov
```

### 静态检查

```text
uv run ruff check --select F,E9,I app tests evals scripts
uv run python -m compileall app tests evals scripts
git diff --check
```

### 手工 smoke

```text
1. 上传原生文本 PDF，确认 indexed。
2. 上传扫描 PDF，确认 pdf_profile 标出扫描风险。
3. 上传含表格 PDF，确认 tables.json 非空。
4. 查询表格问题，确认 source_ref 有页码。
5. 调用 extract_document_table，确认 rows 可回查。
6. 调用 read_document_page，确认指定页内容可读。
```

## 8. 风险和控制

| 风险 | 控制方式 |
|---|---|
| parser 改动导致已有 PDF 入库回归 | P0 baseline + parser eval |
| MinerU CLI 外部依赖不可用 | P0 先跑 MinerU health check，失败时标为 `mineru_unavailable` |
| schema 太严导致历史数据不可用 | validator 先 warning，历史 artifact pass rate > 95% 后再逐步 fatal |
| MinerU / postprocess 升级导致新旧 artifact 混杂 | manifest 记录 `parser_version` / `postprocess_version`，validator 按版本兼容 |
| artifact 文件随 PDF 数量持续增长 | 后续增加 artifact size 统计、orphaned_at 标记和延迟清理策略 |
| 多模态成本失控 | P6 暂缓，按高价值图片触发 |
| 工具绕过权限 | 接入 ToolExecutionFacade，并在读取 artifact 前调用 `DocumentAccessService.can_read_document(context, document)` |
| 表格 rows 泄露未授权内容 | 所有 table 工具先做 doc 权限检查 |
| `risk_flags` 被下游过度信任 | `risk_flags` 只做诊断和 eval 分组，不自动拒绝检索或回答 |
| citation_text 被当结构化字段 | 继续以 source_ref / chunk_evidence 为准 |
| reviewed import 未完成就扩大导入 | 保留 review gate，不自动 apply |

## 9. 面试表达版本

如果面试中解释当前项目，可以这样说:

```text
我们的 PDF RAG 不是直接转文本切片。上传阶段会先进入统一 DocumentIngestionService，
根据 ParserEngineRouter 把 PDF/DOCX/XLSX 路由到 MinerU-first 的异步解析链路。
解析完成后必须产出 artifact manifest、cleaned.md、chunks.json、tables.json、
blocks.json 和 quality_report.json，索引阶段只消费这个契约里的 chunks/tables，
不会猜临时目录，也不会把失败 PDF 当普通文本入库。

检索侧每个 chunk 都带 kb_id、doc_id、chunk_id、page、heading_path 和 source_ref。
retrieve_knowledge 返回的不只是文本，还有 chunk_evidence 和 citation_text，
评测里会检查 source_ref 是否能回查到 metadata store 中的 chunk。

下一步优化不是换 parser，而是补 PDF 类型诊断、表格/页码专项 eval、
read_page/extract_table/source 这类 Agent 工具，以及图表多模态理解。
```

## 10. 最终判断

当前项目 PDF RAG 主链路已经完成大约 70%。优化重点不是补“有没有 PDF 解析”，而是补“解析质量可诊断、引用可验证、表格可回查、Agent 可按需操作、eval 可放行”。

本方案的执行完成标准是:

```text
用户上传 PDF 后，
系统能说明它是什么 PDF，
解析出了什么结构，
哪些地方质量有风险，
检索结果来自哪一页哪一段哪张表，
Agent 能按页和按表回查，
eval 能证明这些行为不是偶然跑通。
```

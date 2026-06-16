# P1/P2/P3 可执行计划清单

日期: 2026-05-13
最近更新: 2026-05-17

## 1. 文档用途

这份文档是 `oncall agent` 当前阶段的正式执行清单，供后续 P1/P2/P3 开发直接参考和逐项打勾。

它不是背景分析，也不是教材解释，而是把下面三类内容固定下来:

1. 当前阶段到底按什么顺序推进。
2. 每一步开始前必须满足什么前提。
3. 每一步做完后，怎样才算通过验收。

本清单必须和以下文档一起使用:

- [docs/technical_fusion_decision_manual.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/technical_fusion_decision_manual.md>)
- [docs/oncall_rag_weknora_fusion_analysis_plan.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/oncall_rag_weknora_fusion_analysis_plan.md>)
- [docs/rag_ingestion_artifact_contract.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/rag_ingestion_artifact_contract.md>)
- [docs/weknora_r0_reuse_review.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/weknora_r0_reuse_review.md>)

---

## 2. 固定前提

后续执行默认以以下前提为真，不再反复讨论:

- 保留 `oncall agent` 的 Python 应用主栈。
- 当前最缺的是知识库层，不是先换 parser。
- P1/P2 不接完整 WeKnora 服务。
- `pdf_eval` 的 MinerU 产物语义是 P2 运行时标准。
- 复用方式采用“复制 WeKnora 成熟实现后最小修改”，不从零设计平行链路。

如果后续任何任务与以上 5 条冲突，该任务默认暂停，不进入实现。

---

## 3. 使用规则

执行这份清单时，遵守下面 6 条规则:

1. 必须按顺序推进，除非某项明确标注可并行。
2. 每完成一项，先更新状态，再进入下一项。
3. 未满足前置条件的任务不得提前开工。
4. 如果某一步只“链路跑通”但没过验收门，只能标记为“部分完成”，不能视为完成。
5. 如果发现计划含义需要调整，先更新计划文档与决策文档，再改实现。
6. 如果某阶段列出的风险在后续步骤中被实际解决，必须回写到清单中，并明确把该风险标成 `已完成`，不能只在后续阶段口头说明。

建议状态字段只使用:

- `未开始`
- `进行中`
- `已完成`
- `阻塞`
- `部分完成`

---

## 4. 阶段总览

| 阶段 | 目标 | 是否当前必须做 |
|---|---|---:|
| `P1` | 建立最小知识库对象层，并保持现有 `md/txt` 行为不回退 | 是 |
| `P2` | 把 MinerU-first 文档接入链路正式产品化进主项目 | 是 |
| `P3` | 按 DataWhale all-in-rag 方法补齐 BM25 + 向量混合召回、rerank 层和离线评估门禁 | 是 |

阶段顺序固定为:

```text
先 P1，
后 P2，
再 P3。

P2 内部必须先路由与接入，再 artifact，再索引，再 citation。
P3 内部必须先评测基线，再混合召回，再 rerank，再离线评估门禁。
```

---

## 5. P1 清单

### P1-0 执行前检查

- 状态: `已完成`
- 前置条件:
  - [x] 已确认固定前提 5 条成立。
  - [x] 已确认本次工作只做 P1/P2，不提前扩到完整 WeKnora 服务接入。
  - [x] 已确认 `md/txt` 现有链路是必须保留的兼容边界。
- 产出物:
  - [x] 本清单作为执行基线被确认。
- 验收标准:
  - [x] 后续任务标题、顺序、验收都以本清单为准。
- 暂停条件:
  - [ ] 如果此时还在摇摆“要不要改主框架”，P1 不启动。

### P1-1 最小领域对象落地

- 状态: `已完成`
- 目标:
  - 建立 `KnowledgeBase`、`DocumentRecord`、`ChunkRecord` 的最小 Python 版本。
- 前置条件:
  - [x] `P1-0` 已完成。
  - [x] 已明确字段语义优先对齐 WeKnora 对应对象，而不是自定义一套。
- 参考来源:
  - `WeKnora/internal/types/knowledgebase.go`
  - `WeKnora/internal/types/knowledge.go`
  - `WeKnora/internal/types/chunk.go`
- 必做项:
  - [x] 明确 `kb_id/doc_id/chunk_id` 的最小字段集。
  - [x] 明确 `status` 状态枚举与映射关系。
  - [x] 明确 `source_ref` 在 chunk 层的归属位置。
- 不允许:
  - [ ] 不允许先写“本项目特有模型”再回头映射 WeKnora。
  - [ ] 不允许在这一步引入多租户、FAQ、Wiki 额外字段扩面。
- 产出物:
  - [x] 最小模型文件或等价实现。
  - [x] 字段与 WeKnora 来源的对应说明。
- 验收标准:
  - [x] 模型字段足以支撑后续 `artifact_dir/parser_engine/status/source_ref`。
  - [x] 不破坏现有 `md/txt` 上传调用路径。
- 风险提示:
  - 风险: 字段只存在模型层，不进入后续 metadata。

### P1-2 Metadata Store 落地

- 状态: `已完成`
- 目标:
  - 建立最小 `KnowledgeMetadataStore`，承接文档和 chunk 生命周期。
- 前置条件:
  - [x] `P1-1` 已完成。
- 参考来源:
  - `WeKnora/internal/application/service/chunk.go`
  - `WeKnora/internal/types/interfaces/chunk.go`
- 必做项:
  - [x] 提供按 `doc_id` 查询、写入、删除 chunk 的最小能力。
  - [x] 提供按 `doc_id` 查询文档状态的最小能力。
  - [x] 预留与 Milvus metadata 对齐的字段出口。
- 不允许:
  - [ ] 不允许只依赖 Milvus JSON metadata 充当唯一状态存储。
- 产出物:
  - [x] `KnowledgeMetadataStore` 或等价实现。
- 验收标准:
  - [x] 文档与 chunk 不再只是“文件 + Milvus 记录”的松散关系。
- 风险提示:
  - 风险: 只做了接口壳，没有真正承接后续索引链路。
- 风险收口情况:
  - [x] 已完成: `KnowledgeMetadataStore` 已被 `app/services/vector_index_service.py` 实际接入 legacy `md/txt` 索引链路，承担 document upsert、status update、old chunk delete 和 new chunk replace，不再只是接口壳。

### P1-3 md/txt 兼容索引改造

- 状态: `已完成`
- 目标:
  - 在不改变现有外部行为的前提下，让 `md/txt` 入库附带稳定 `kb_id/doc_id/chunk_id/source_ref`。
- 前置条件:
  - [x] `P1-1`、`P1-2` 已完成。
- 参考来源:
  - 当前主仓库 `app/api/file.py`
  - 当前主仓库 `app/services/vector_index_service.py`
  - 当前主仓库 `app/services/document_splitter_service.py`
  - WeKnora `builtin_converter.go` 的简单格式处理思路
- 必做项:
  - [x] 保持 `md/txt` 原上传入口可用。
  - [x] 保持现有切分主逻辑不回退。
  - [x] 新增 `kb_id/doc_id/chunk_id/source_ref` 到 metadata。
  - [x] 保留 `_source/_file_name/_extension` 兼容字段。
- 不允许:
  - [ ] 不允许在 P1 改写 `document_splitter_service` 主算法。
  - [ ] 不允许为了新对象层破坏旧响应主结构。
- 产出物:
  - [x] 兼容改造后的 `md/txt` 索引路径。
- 验收标准:
  - [x] `md/txt` 上传后仍可入库和检索。
  - [x] Milvus metadata 中同时存在旧键与新键。
  - [x] 同一 `md/txt` 文件重复上传不产生明显重复脏数据。
- 风险提示:
  - 风险: 外部看似没改，内部 metadata 却断层，导致后面 P2 接不上。
- 风险收口情况:
  - [x] 已完成: `P1-4` 正式回归已经覆盖 `kb_id/doc_id/chunk_id/source_ref` 与旧 `_source/_file_name/_extension` 共存，legacy `md/txt` 路径的 metadata 断层风险已收口。

### P1-4 P1 回归门

- 状态: `已完成`
- 目标:
  - 确认 P1 真的是“补知识库对象层”，而不是“顺手改坏了旧链路”。
- 前置条件:
  - [x] `P1-1` 至 `P1-3` 已完成。
- 必做项:
  - [x] 对同一批 `md/txt` 样本做索引与检索逻辑级回归。
  - [x] 检查 metadata 是否带稳定来源字段。
  - [x] 检查旧链路响应是否未发生不必要回退。
- 验收标准:
  - [x] `md/txt` 行为无明显回退。
  - [x] 新对象与新 metadata 已稳定落地。
- 进入 P2 的放行条件:
  - [x] 通过后才能进入 `P2-0`。
- 本轮补充说明:
  - [x] 已完成无 Milvus 依赖的逻辑级回归验证。
  - [x] 已补齐旧 `/api/upload` 响应回归检查，并形成可重复执行的正式测试。
  - [x] 2026-05-15 已补做 live Milvus + DashScope smoke: Docker Milvus 从 `vector-database.yml` 启动，DashScope `text-embedding-v4` 返回 1024 维向量，`biz` collection 完成 1 条 smoke 文档写入、检索和按 `_source` 删除。
  - [x] 但按本清单的 P1 门禁语义，P1-4 放行依据是 `md/txt` 兼容行为与响应不回退的正式回归，而不是要求当前工作站必须先具备完整外部依赖。

---

## 6. P2 清单

### P2-0 执行前检查

- 状态: `已完成`
- 前置条件:
  - [x] `P1-4` 已完成。
  - [x] 已接受 `pdf_eval` 产物语义是主项目运行标准。
  - [x] 已明确 `.md/.txt -> plain_text`，`.pdf/.docx/.xlsx -> mineru` 是固定主路由。
- 不允许:
  - [x] 不允许在此时重新讨论 `MarkItDown` 是否回到 Office 主路径。
  - [x] 不允许跳过 artifact contract 直接做 PDF 入库。
- 检查结论:
  - [x] `P1-4` 已在本仓库内完成正式回归并在 `PROJECT_STATE.md` 收口。
  - [x] `docs/technical_fusion_decision_manual.md` 已把 “接受 `pdf_eval` 的 MinerU 产物语义作为主项目运行时标准” 记为固定决策。
  - [x] `docs/technical_fusion_decision_manual.md` 已把 `.md/.txt -> plain_text`、`.pdf/.docx/.xlsx -> mineru` 写成固定主路由控制方式。

### P2-1 ParserEngineRouter 固化

- 状态: `已完成`
- 目标:
  - 建立文件类型到 `parser_engine` 的正式路由。
- 前置条件:
  - [x] `P2-0` 已完成。
- 参考来源:
  - `WeKnora/internal/types/knowledgebase.go`
  - `WeKnora/internal/infrastructure/docparser/engine_registry.go`
  - `WeKnora/docreader/parser/registry.py`
- 必做项:
  - [x] 固定 `.md/.txt -> plain_text`
  - [x] 固定 `.pdf/.docx/.xlsx -> mineru`
  - [x] 为后续可用性检查预留 `ParserEngineInfo` 风格描述
- 验收标准:
  - [x] 不同扩展名输入命中的 engine 可预测、可复现。
- 本轮实现说明:
  - [x] 新增 `app/services/parser_engine_router.py` 作为正式路由边界，不再只依赖文档中的规则描述。
  - [x] 路由默认规则已落为代码，且保留 `ChunkingConfig.parser_engine_rules` 覆盖入口。
  - [x] `app/services/vector_index_service.py` 已开始消费该路由结果，而不是继续硬编码 `plain_text`。
  - [x] 新增 `tests/test_parser_engine_router.py`，覆盖固定主路由、可预测扩展名集合、覆盖规则和 `ParserEngineInfo` 描述结构。
- 风险提示:
  - 风险: 路由逻辑散落在上传代码和 adapter 代码里，后面难维护。
- 风险收口情况:
  - [x] 已完成: `app/services/parser_engine_router.py` 已成为正式路由边界，`app/services/vector_index_service.py` 已开始消费该路由结果；后续 `P2-2/P2-3` 需要继续沿用这一个真源，而不是再各自扩展一套判断。

### P2-2 DocumentIngestionService 落地

- 状态: `已完成`
- 目标:
  - 把“保存原件 -> 创建文档记录 -> 选择 parser -> 校验 artifact -> 触发索引”串成正式工作流。
- 前置条件:
  - [x] `P2-1` 已完成。
- 必做项:
  - [x] 固定上传目录与 artifact 目录结构。
  - [x] 生成 `DocumentRecord.original_path` 和 `artifact_dir`。
  - [x] 管理 `uploaded -> parse_pending -> parsing -> parsed/index_pending` 等状态流。
- 验收标准:
  - [x] 文档进入系统后，不再只是“上传文件后立刻索引”的临时路径。
- 本轮实现说明:
  - [x] 新增 `app/services/document_ingestion_service.py`，把原件保存、`doc_id` 生成、`DocumentRecord` 建立、parser 选择和后续分支调度收成正式服务。
  - [x] `/api/upload` 已改为通过 `DocumentIngestionService` 进入正式链路，并把返回的 `file_path` 切到 canonical `original_path`。
  - [x] `plain_text` 分支现在会同步走 `uploaded -> parse_pending -> parsing -> parsed -> index_pending/indexing/indexed`。
  - [x] `mineru` 分支当前会正式落库并停在 `parse_pending`，等待 `P2-3` 接入 parser adapter，而不是偷偷回退成普通文本索引。
  - [x] 新增 `tests/test_document_ingestion_service.py`，覆盖 plain-text 正式接入、MinerU 文档进入 `parse_pending`、以及 PDF API 级上传验证。
- 风险提示:
  - 风险: 接入服务存在，但状态流仍然不闭合。
- 风险收口情况:
  - [x] 已完成: `P2-3 MinerUParserAdapter` 接入后，`mineru` 分支已能从 `parse_pending` 进入 `parsing -> parsed -> index_pending`，不再停在半路。

### P2-3 MinerUParserAdapter 接入

- 状态: `已完成`
- 目标:
  - 基于 WeKnora `MinerUReader` 结构，做主仓库的 Python 版本最小适配。
- 前置条件:
  - [x] `P2-2` 已完成。
- 参考来源:
  - `WeKnora/internal/infrastructure/docparser/mineru_converter.go`
  - `pdf_eval` 已验收的 MinerU 后处理语义
- 必做项:
  - [x] 复制请求参数、超时、响应兼容处理核心结构。
  - [x] 对接主项目配置与本地 artifact 目录。
  - [x] 不直接读取 `pdf_eval/outputs/` 历史实验目录。
- 不允许:
  - [x] 不允许在此步骤自己重写新的 chunk/table 语义。
- 验收标准:
  - [x] 对同一 PDF，能稳定拿到 markdown/images 和后续 artifact 产物。
- 本轮实现说明:
  - [x] 新增 `app/services/mineru_parser_adapter.py`，以主项目配置驱动本地 MinerU CLI 参数、超时和 raw 输出定位逻辑。
  - [x] `DocumentIngestionService.process_deferred_document()` 已能把 `mineru` 文档从 `parse_pending` 推进到 `parsing -> parsed -> index_pending`。
  - [x] 后处理直接复用 `pdf_eval/scripts/mineru_postprocess.py`，没有在主仓库手写新的 chunk/table 语义。
  - [x] 新增 `tests/test_mineru_parser_adapter.py`，覆盖成功路径、失败路径和 `DocumentIngestionService` 对 deferred MinerU 文档的接入。
  - [x] 已对真实合同 PDF 样本做一次外部提权 smoke，确认 `mineru` 路径能生成 raw markdown 并把文档状态推进到 `index_pending`。
- 风险提示:
  - 风险: 看起来接了 MinerU，实际上已经和 `pdf_eval` 语义悄悄分叉。
- 风险收口情况:
  - [x] 已完成: 主仓库后处理直接复用 `pdf_eval/scripts/mineru_postprocess.py`，而不是另写一套 chunk/table 语义；同时真实合同 PDF smoke 已证明当前 adapter 能走通这条复用链。

### P2-4 artifact 六件套落地

- 状态: `已完成`
- 目标:
  - 确保 parser adapter 产出固定六件套。
- 前置条件:
  - [x] `P2-3` 已完成。
- 必做项:
  - [x] 生成 `artifact_manifest.json`
  - [x] 生成 `cleaned.md`
  - [x] 生成 `chunks.json`
  - [x] 生成 `tables.json`
  - [x] 生成 `blocks.json`
  - [x] 生成 `quality_report.json`
  - [x] 缺任一关键文件时直接失败
- 验收标准:
  - [x] 六件套路径、文件名、字段语义符合 contract。
  - [x] 手工删除某一关键文件后，索引必须拒绝继续。
- 本轮实现说明:
  - [x] 新增 `app/services/artifact_manifest_service.py`，统一负责 `artifact_manifest.json` 的生成、读取和严格校验。
  - [x] `MinerUParserAdapter` 现在会在 postprocess 成功后写入 manifest，并在把文档推进到 `index_pending` 前做缺件校验。
  - [x] `DocumentIngestionService.validate_artifacts_for_index(doc_id)` 已提供后续索引阶段的正式入口，不再依赖硬编码路径。
  - [x] 新增 `tests/test_artifact_manifest_service.py`，覆盖 manifest 写入与缺件拒绝。
  - [x] 新增 `tests.test_mineru_parser_adapter` 的缺件失败用例，确认缺少 `tables.json` 时文档会转成 `parse_failed`。
  - [x] 已对真实合同 PDF 样本做一次外部提权 smoke，确认六件套 + `artifact_manifest.json` 实际落出。
- 风险提示:
  - 风险: 只产出 Markdown，剩下文件靠推测补，后续整条链不稳。
- 风险收口情况:
  - [x] 已完成: 当前 `mineru` 分支已经在真实样本上产出 `artifact_manifest.json + cleaned.md + chunks.json + tables.json + blocks.json + quality_report.json`，并且缺少任一关键文件会被 manifest 校验直接拒绝继续。

### P2-5 ChunkBuilder / Indexer 落地

- 状态: `已完成`
- 目标:
  - 用 `chunks.json` 与 `tables.json` 作为正式主输入，建立索引数据。
- 前置条件:
  - [x] `P2-4` 已完成。
- 必做项:
  - [x] 正文只从 `chunks.json` 建 chunk。
  - [x] 表格只从 `tables.json` 建 chunk。
  - [x] 不允许从 `cleaned.md` 猜表格或正文结构。
  - [x] 把 `doc_id/chunk_id/page/content_type/parser_engine/source_ref` 写入 metadata。
- 验收标准:
  - [x] 检索层可见稳定 chunk 身份和来源字段。
- 本轮实现说明:
  - [x] 新增 `app/services/artifact_chunk_builder_service.py`，负责把 `chunks.json` / `tables.json` 适配为 index-ready `ChunkRecord` 与 LangChain `Document`。
  - [x] `DocumentIngestionService.prepare_artifacts_for_index(doc_id)` 已固定 P2-5 前置顺序: 先 `validate_artifacts_for_index()`，再做 artifact contract adapter。
  - [x] 当前 adapter 会把正文 chunk 标准化为 `doc_id:cxxxxx`，把表格 chunk 标准化为 `doc_id:table:txxxxx`，并写入 `source_ref` 与旧 `_source/_file_name/_extension` 兼容 metadata。
  - [x] P2-5 准备阶段遇到坏 chunk 或 `quality_report.fatal_errors` 会把文档状态更新为 `index_failed` 并重新抛出异常，调用方不能误以为已成功。
  - [x] `app/services/vector_index_service.py` 已支持 `mineru` 文档从 prepared artifacts 写入 vector store，并把 `ChunkRecord` 持久化到 `KnowledgeMetadataStore`。
  - [x] 新增 `tests/test_artifact_chunk_builder_service.py`，覆盖正文/表格标准化、坏 chunk 失败、`fatal_errors` 拦截、MinerU prepared artifacts 索引成功和向量写入失败状态。
- 风险提示:
  - 风险: 文本能搜到，但来源字段不完整，后面 citation 无法站住。
- 风险收口情况:
  - [x] 已完成: P2-5 当前测试已覆盖 MinerU prepared artifacts 进入 vector index 写入路径，且 fake vector-store 文档 metadata 与 metadata-store `ChunkRecord` 都带 `doc_id/chunk_id/page/content_type/parser_engine/source_ref`。2026-05-15 已另行完成 live Milvus + DashScope smoke，验证真实 `VectorStoreManager` 写入、检索、清理路径可用；P2-5 的正式阶段口径仍是代码路径与逻辑回归完成。

### P2-6 doc_id 幂等清理

- 状态: `已完成`
- 目标:
  - 让同一文档重传、重解析、重索引不会产生重复脏数据。
- 前置条件:
  - [x] `P2-5` 已完成。
- 参考来源:
  - `WeKnora/internal/application/service/knowledge_process.go`
- 必做项:
  - [x] 先清旧 chunk
  - [x] 再清旧索引
  - [x] 再写新数据
  - [x] 优先按 `doc_id` 清理，同时兼容现有 `_source` 清理逻辑
- 验收标准:
  - [x] 重传同一文档后，Milvus 不出现明显重复脏数据。
- 本轮实现说明:
  - [x] `app/services/vector_store_manager.py` 新增 `delete_by_doc_id(doc_id)`，并把 `delete_by_source()` 统一到 `_delete_by_metadata_field()`，Milvus JSON metadata 表达式使用 `json.dumps()` 安全转义。
  - [x] `app/services/vector_index_service.py` 新增 `_cleanup_existing_document_data(document_record)`，固定清理顺序为 `delete_chunks_by_doc_id -> delete_by_doc_id -> delete_by_source -> add_documents`。
  - [x] 清理动作已同时进入 `plain_text` 与 `mineru` 两条索引路径，避免 P2-5 新接入的 prepared artifacts 路径绕过幂等逻辑。
  - [x] 新增 `tests/test_p2_6_idempotent_cleanup.py`，覆盖 MinerU 同 `doc_id` 重索引、plain-text 同 `doc_id` 重索引、清理顺序，以及只带 `_source` 的 legacy 脏行兼容清理。
  - [x] 2026-05-17 已补做 P2-6 live Milvus + DashScope smoke: 重索引前 `doc_id_rows=1/source_rows=2/chunk_records=1`，重索引后 `doc_id_rows=1/source_rows=1/chunk_records=1`，最终 smoke 数据清理为 `doc_id_rows=0/source_rows=0`，collection 为 `biz`。
- 风险提示:
  - 风险: 表面看入库成功，实际积累大量旧 chunk 和旧向量。
- 风险收口情况:
  - [x] 已完成: P2-6 当前已经在单元测试中证明清理顺序，在 live Milvus + DashScope smoke 中证明真实向量库不会在同一 `doc_id` 重索引后保留重复脏数据。

### P2-7 Retrieval citation 基线

- 状态: `已完成`
- 目标:
  - 让检索结果成为正式证据对象，而不只是上下文字符串。
- 前置条件:
  - [x] `P2-6` 已完成。
- 参考来源:
  - `WeKnora/internal/types/search.go`
  - `WeKnora/internal/types/retriever.go`
  - `WeKnora/internal/application/service/knowledgebase_search.go`
  - `WeKnora/internal/application/service/knowledgebase_search_results.go`
- 必做项:
  - [x] 建 `RetrievalQuery` 或等价 DTO
  - [x] 建 `SearchResult` 等价结构
  - [x] 检索后补齐 `file_name/page/heading_path/source_ref`
  - [x] 返回 `citation_text`
- 验收标准:
  - [x] 至少一条检索结果同时带 `doc_id/chunk_id/page/source_ref/citation_text`
  - [x] 当前 Agent 工具调用不报错
- 本轮实现说明:
  - [x] `app/models/knowledge.py` 新增 `RetrievalQuery`、`RetrievalResult`、`RetrievalResponse`，把 retrieval 的输入/输出都提升为正式模型。
  - [x] `app/services/retrieval_service.py` 把原始 Milvus 命中转成结构化证据对象，统一构造 `citation_text`，并跳过缺少稳定引用字段的命中。
  - [x] `app/tools/knowledge_tool.py` 继续保留 `retrieve_knowledge` 这个工具名，但返回 `content_and_artifact`，并把调用输入 query 作为 artifact 的真实查询，同时让 `source_ref` 与 result 身份保持一致。
  - [x] `tests/test_retrieval_service.py` 覆盖 citation 格式、空结果、以及 tool artifact 形状。
  - [x] 2026-05-17 验证通过：`.venv/bin/python -m unittest tests.test_retrieval_service -v`、`.venv/bin/python -m unittest discover tests -v`、`.venv/bin/python -m compileall app tests`。
- 风险收口情况:
  - [x] 已完成: 检索结果现在是正式证据对象，而不是单纯拼好的上下文字符串；调用方可以直接消费 `doc_id/chunk_id/page/source_ref/citation_text`。
- 风险提示:
  - 风险: 只是把引用显示出来了，但底层没有稳定来源链。

### P2-8 P2 端到端门禁

- 状态: `已完成`
- 目标:
  - 用正式门禁确认 P2 不是“只接通了 PDF”，而是真的完成了主链路接入。
- 前置条件:
  - [x] `P2-1` 至 `P2-7` 已完成。
- 必做项:
  - [x] `md/txt` 回归门禁通过。
  - [x] artifact 完整性门禁通过。
  - [x] MinerU 参考门禁通过。
  - [x] 非降级门禁通过。
  - [x] citation 门禁通过。
- 验收标准:
  - [x] 只有全部通过，P2 才能标记为完成。
- 本轮实现说明:
  - [x] 新增 `tests/test_p2_8_gate.py`，把 P2-8 门禁拆成 5 个可重复执行的 unittest 检查，分别覆盖 md/txt 回归、artifact 完整性、MinerU 引用链、上传非降级和 citation 输出。
  - [x] md/txt 回归门禁通过 `VectorIndexService.index_single_file()` 的真实路径，确认 `doc_id/chunk_id/source_ref` 仍稳定写入。
  - [x] artifact 完整性门禁通过 `DocumentIngestionService.validate_artifacts_for_index()` / `prepare_artifacts_for_index()`，确保 manifest 与六件套文件一致。
  - [x] MinerU 参考门禁通过 `VectorIndexService.index_document_record()`，确认 prepared artifacts 进入索引时仍保留 `source_ref` 与页码信息。
  - [x] 非降级门禁通过 `app.api.file.upload_file` 的正式响应 envelope，确认 `code/message/data` 仍稳定。
  - [x] citation 门禁通过 `retrieve_knowledge` 的 `content_and_artifact` 边界，确认 `citation_text` 与稳定引用对象同时返回。
  - [x] 2026-05-17 验证通过：`.venv/bin/python -m unittest tests.test_p2_8_gate -v`、`.venv/bin/python -m unittest discover tests -v`、`.venv/bin/python -m compileall app tests`。
- 风险收口情况:
  - [x] 已完成: P2 现在有一组可重复执行的正式门禁，而不是只靠人工描述“应该都通过了”。
- 风险提示:
  - 风险: 把“链路跑通”误当成“功能等价接入完成”。

---

## 7. P3 清单

### P3-0 执行前检查

- 状态: `已完成`
- 目标:
  - 明确 P3 不是重做 P1/P2，而是在 P2 结构化证据链之上补检索质量层和评估层。
- 前置条件:
  - [x] `P2-8` 已完成。
  - [x] 当前 `retrieve_knowledge` 已有 `content_and_artifact` 边界。
  - [x] 当前检索结果已能返回 `doc_id/chunk_id/page/source_ref/citation_text`。
  - [x] 已确认 DataWhale all-in-rag 作为 P3 方法参考，而不是要求照搬其 demo 数据集和完整项目结构。
- 参考来源:
  - DataWhale all-in-rag `docs/chapter4/11_hybrid_search.md`
  - DataWhale all-in-rag `docs/chapter6/18_system_evaluation.md`
  - `docs/oncall_rag_weknora_fusion_analysis_plan.md`
  - `app/services/retrieval_service.py`
  - `app/tools/knowledge_tool.py`
- 必做项:
  - [x] 固定 P3 的三层边界: `recall -> fusion -> rerank -> evidence assembly`。
  - [x] 固定 P3 不改 parser、artifact contract、ChunkBuilder、doc_id 幂等清理。
  - [x] 明确 P3 输出仍然必须是 `RetrievalResult` / `RetrievalResponse`，不能绕过 P2-7 的 citation 模型。
- 不允许:
  - [ ] 不允许为了上 hybrid/rerank 重写 MinerU 解析链路。
  - [ ] 不允许把检索质量提升说成端到端问答质量已经达标。
  - [ ] 不允许跳过评测基线直接调融合参数。
- 产出物:
  - [x] P3 计划清单被确认。
  - [x] P3 方法边界写入开发记录。
- 验收标准:
  - [x] P3 的实现顺序、验收指标、暂停条件都能从本清单读出来。
- 风险提示:
  - 风险: 把 DataWhale 教程里的 demo 代码原样搬进主仓库，导致架构边界变乱。
- 风险收口情况:
  - [x] 已完成: P3-0 明确只复用 DataWhale 的方法顺序与指标体系，不照搬 demo 项目结构；当前仓库继续保持 `recall -> fusion -> rerank -> evidence assembly` 分层，且 P2 的 parser、artifact、chunk、doc_id、citation 契约不被重写。

### P3-1 离线评测集与 dense baseline 固化

- 状态: `已完成`
- 目标:
  - 先建立可重复评测的查询集和 dense-only 基线，再开始 hybrid/rerank 改造。
- 前置条件:
  - [x] `P3-0` 已完成。
  - [x] `P2-7` 已能输出 citation-aware evidence。
- 参考来源:
  - DataWhale all-in-rag `docs/chapter6/18_system_evaluation.md`
  - `tests/test_retrieval_service.py`
  - `tests/test_p2_8_gate.py`
- 必做项:
  - [x] 新建离线评测样本文件，例如 `evals/rag_retrieval/golden_queries.jsonl`。
  - [x] 每条样本至少包含 `query`、`gold_doc_ids`、`gold_chunk_ids`、`gold_source_refs`、`expected_keywords`。
  - [x] 先跑当前 dense-only 检索，生成 baseline 报告。
  - [x] 报告中记录 `top_k`、检索模式、命中列表、citation 字段完整性和耗时。
- 不允许:
  - [ ] 不允许用人工感觉替代固定评测集。
  - [ ] 不允许只看最终答案，不看检索命中是否命中 gold evidence。
  - [ ] 不允许把未标注来源的问题加入正式指标统计。
- 产出物:
  - [x] `evals/rag_retrieval/golden_queries.jsonl`
  - [x] dense-only baseline JSON/Markdown 报告:
    - `evals/rag_retrieval/reports/dense_only_baseline_20260517_172313.json`
    - `evals/rag_retrieval/reports/dense_only_baseline_20260517_172313.md`
  - [x] 可重复执行的 baseline 命令: `.venv/bin/python evals/rag_retrieval/run_dense_baseline.py`
- 验收标准:
  - [x] 至少覆盖 `md/txt`、MinerU PDF 正文 chunk、MinerU table chunk 三类证据。
  - [x] 每条样本都有可核查的 gold evidence 身份。
  - [x] dense-only 指标能被后续 hybrid/rerank 报告直接对比。
- 本轮实现说明:
  - [x] 新增 `evals/rag_retrieval/run_dense_baseline.py`，使用隔离的临时 Milvus collection 跑 dense-only baseline，完成后自动清理该 collection。
  - [x] `golden_queries.jsonl` 当前包含 4 条样本: `HighCPUUsage` markdown 文档、`HighMemoryUsage` markdown 文档、MinerU 正文 chunk、MinerU table chunk。
  - [x] baseline 真实经过 DashScope `text-embedding-v4` 与本地 Docker Milvus，普通 sandbox 下 PyMilvus 连接 `localhost` 会超时，正式验证使用 sandbox-external 执行并强制 `127.0.0.1`。
  - [x] baseline 指标: `query_count=4`，`doc_recall@1=1.000`，`doc_recall@3=1.000`，`hit@1=1.000`，`hit@3=1.000`，`citation_correctness@3=1.000`，`mrr@3=1.000`，latency p50 `170.5ms`，p95 `177ms`。
- 风险提示:
  - 风险: 没有 baseline 就开始调 hybrid，后续无法证明收益来自哪里。
- 风险收口情况:
  - [x] 已完成: P3-1 已有固定 golden queries、可复跑 baseline 命令和 dense-only JSON/Markdown 报告；P3-2 的 hybrid/rerank 收益以后必须与这版 dense-only baseline 对比，不能凭主观感觉判断。

### P3-2 BM25 + 向量混合召回

- 状态: `已完成`
- 目标:
  - 在现有 dense vector search 之外补 BM25 稀疏召回，并按 DataWhale 的“稀疏 + 密集并行检索后融合”方法形成统一候选集。
- 前置条件:
  - [x] `P3-1` 已完成 dense-only baseline。
  - [x] 当前 `VectorSearchService` dense 检索行为可回归。
- 参考来源:
  - DataWhale all-in-rag `docs/chapter4/11_hybrid_search.md`
  - DataWhale all-in-rag `code/C4/01_hybrid_search.py`
  - `app/services/vector_search_service.py`
  - `app/services/knowledge_metadata_store.py`
- 必做项:
  - [x] 新增独立 `SparseSearchService` 或等价 BM25 retriever，不把 BM25 逻辑塞进 `RetrievalService`。
  - [x] BM25 索引必须使用与 P2 一致的 `kb_id/doc_id/chunk_id/source_ref`。
  - [x] 保留现有 dense 检索作为 `DenseSearchService` 或兼容路径。
  - [x] 支持 `dense_only`、`sparse_only`、`hybrid` 三种检索模式，便于评测对比。
  - [x] 首版采用 RRF 融合；加权线性融合只能作为后续调参项，不作为第一版默认。
- 不允许:
  - [x] 不允许为 BM25 新建一套不含 citation 身份的平行 chunk 数据。
  - [x] 不允许改坏当前 Milvus `biz` collection 的 dense smoke。
  - [x] 不允许在没有迁移门禁前强行重建生产 collection schema。
- 产出物:
  - [x] BM25 sparse retriever
  - [x] dense/sparse 并行召回接口
  - [x] RRF fusion 结果模型
  - [x] hybrid 检索单元测试
- 验收标准:
  - [x] 对同一 query，可以分别输出 dense hits、sparse hits、hybrid fused hits。
  - [x] hybrid hits 中每条结果仍带 `doc_id/chunk_id/source_ref/citation_text`。
  - [x] `Recall@k` 或 `Hit@k` 至少不能低于 dense-only baseline；如果下降，必须记录失败样本并暂停默认启用。
- 风险提示:
  - 风险: 混合召回提升了“看起来相关”的结果数量，但破坏了稳定引用和可解释评测。

### P3-3 明确 rerank 层

- 状态: `已完成`
- 目标:
  - 在 hybrid candidate 之后建立独立 rerank 层，让“召回”和“精排”分开，不把 rerank 混在 fusion 或 prompt 里。
- 前置条件:
  - [x] `P3-2` 已完成。
  - [x] hybrid candidate 能保持稳定 evidence identity。
- 参考来源:
  - DataWhale all-in-rag 第四章检索优化主线
  - `docs/oncall_rag_weknora_fusion_analysis_plan.md`
  - `WeKnora/internal/application/service/knowledgebase_search.go`
  - `WeKnora/internal/application/service/knowledgebase_search_results.go`
- 必做项:
  - [x] 新增 `RerankService` 或等价边界，输入为 fused candidates，输出为 reordered candidates。
  - [x] 支持 `rerank_enabled=false` 的默认回退路径。
  - [x] 明确 rerank 模型配置、超时、失败降级和最大候选数。
  - [x] rerank 只改变排序和 rerank score，不改变 `doc_id/chunk_id/source_ref`。
  - [x] 记录 `recall_score`、`fusion_score`、`rerank_score`，便于后续定位。
- 不允许:
  - [x] 不允许 rerank 失败导致整个知识检索不可用。
  - [x] 不允许用 LLM 生成新 citation 代替原始 source_ref。
  - [x] 不允许 rerank 直接调用 answer prompt 或改写最终回答。
- 产出物:
  - [x] `RerankService` 或等价实现
  - [x] rerank 配置项
  - [x] rerank 单元测试和失败降级测试
- 验收标准:
  - [x] `hybrid` 和 `hybrid_rerank` 两种模式可独立评测。
  - [x] rerank 后 `MRR` 或 `Hit@k` 相比 hybrid baseline 有可解释变化。
  - [x] rerank 超时或异常时能回退到未 rerank 的 fused candidates，并记录原因。
- 风险提示:
  - 风险: rerank 层如果没有明确输入输出，会和召回、融合、回答层纠缠在一起。

### P3-4 离线评估指标和脚本

- 状态: `已完成`
- 目标:
  - 建立一套可重复执行的离线评估脚本，量化 dense、hybrid、hybrid+rerank 的差异。
- 前置条件:
  - [x] `P3-1` 已完成评测集。
  - [x] `P3-2`、`P3-3` 已完成检索模式。
- 参考来源:
  - DataWhale all-in-rag `docs/chapter6/18_system_evaluation.md`
  - `tests/test_p2_8_gate.py`
- 必做项:
  - [x] 新增评估脚本，例如 `scripts/eval_rag_retrieval.py`。
  - [x] 指标至少包括 `Recall@k`、`MRR`、`Hit@k`、`citation correctness`、`latency p50/p95`。
  - [x] 可选补充 `Precision@k`、`MAP`、失败样本明细。
  - [x] 输出机器可读 JSON 和人工可读 Markdown。
  - [x] 对每个 query 记录 retrieved chunk ids、matched gold ids、citation 字段缺失情况和耗时。
- 不允许:
  - [x] 不允许只输出一个总分，不保留逐 query 明细。
  - [x] 不允许把 citation correctness 简化成“有 citation_text 字符串”。
  - [x] 不允许把真实外部依赖失败隐藏成 0 分。
- 产出物:
  - [x] `evals/rag_retrieval/run_retrieval_eval.py`
  - [x] `evals/rag_retrieval/reports/*.json`
  - [x] `evals/rag_retrieval/reports/*.md`
- 验收标准:
  - [x] 同一评测集能分别跑 `dense_only`、`hybrid`、`hybrid_rerank`。
  - [x] `citation correctness` 至少校验 `doc_id/chunk_id/source_ref/source_file/page` 与 gold evidence 的一致性。
  - [x] latency 至少拆分出 retrieval total；如果能拆到 dense/sparse/fusion/rerank 更好。
- 风险提示:
  - 风险: 指标脚本只评价“召回到了没”，却没评价返回证据是否真的可引用。

### P3-5 P3 回归门禁

- 状态: `已完成`
- 目标:
  - 把 P3 的新能力固定成可重复门禁，而不是一次性实验。
- 前置条件:
  - [x] `P3-2` 至 `P3-4` 已实现。
- 必做项:
  - [x] BM25 sidecar 或 sparse index 构建门禁通过。
  - [x] dense-only 兼容门禁通过。
  - [x] hybrid RRF 融合门禁通过。
  - [x] rerank 开关与失败降级门禁通过。
  - [x] 离线评估脚本门禁通过。
  - [x] citation correctness 门禁通过。
- 不允许:
  - [x] 不允许 P3 默认启用后导致 P2-8 任一门禁失败。
  - [x] 不允许没有对比报告就宣布 hybrid/rerank 有效。
- 产出物:
  - [x] `tests/test_p3_retrieval_gate.py` 或等价门禁测试
  - [x] P3 评估报告
- 验收标准:
  - [x] P2-8 gate 仍通过。
  - [x] P3 gate 能在无真实外部网络条件下稳定验证核心契约。
  - [x] live Milvus + DashScope smoke 如需执行，必须单独记录外部依赖状态和结果。
- 风险提示:
  - 风险: P3 做成了实验脚本，不能作为主项目长期能力维护。

### P3-6 文档、状态与默认策略收口

- 状态: `已完成`
- 目标:
  - 把 P3 的方法、默认开关、指标结果和剩余边界写回项目文档，形成可交接状态。
- 前置条件:
  - [x] `P3-5` 已完成。
- 必做项:
  - [x] 更新 `PROJECT_STATE.md`。
  - [x] 更新 `docs/rag_fusion_development_record.md`。
  - [x] 更新本清单中 P3 项目的状态、验收结果和风险收口情况。
  - [x] 明确默认检索模式，例如继续 `dense_only`，或切到 `hybrid`，或按配置启用 `hybrid_rerank`。
  - [x] 明确不能声称的边界，例如大规模线上效果、完整多模态图像检索、GraphRAG、完整 WeKnora 服务接入。
- 不允许:
  - [x] 不允许只在聊天里说明 P3 完成，不回写项目状态。
  - [x] 不允许把离线小样本指标扩大表述成生产 SLA。
- 产出物:
  - [x] 更新后的 `PROJECT_STATE.md`
  - [x] 更新后的开发记录
  - [x] 更新后的 P3 清单状态
- 验收标准:
  - [x] 后续从仓库文件恢复上下文时，能清楚知道 P3 做到了什么、没做到什么、怎么验证。
- 风险提示:
  - 风险: 代码能力补上了，但项目叙述仍停留在 P2，导致后续交接和简历表达都不准。

---

## 8. 当前明确不做

在本清单执行期间，下列方向默认不进入实现:

- [ ] 不接完整 WeKnora 服务
- [ ] 不把主框架改为 Go
- [ ] 不重写自己的平行 chunker
- [ ] 不绕过 P3-1 评测基线直接做 hybrid search / rerank
- [ ] 不先重写 grounded answer prompt
- [ ] 不把 `MarkItDown` 拉回 Office 主路径
- [ ] 不把 P3 扩成 GraphRAG 或完整多模态图像检索

如果后续要做其中任一项，必须先更新决策手册与融合计划，再新开阶段。

---

## 9. 计划清单写法模板

如果后续要继续往更细的任务表拆分，建议每项都按这个模板写:

```text
任务编号:
任务名称:
所属阶段:
前置条件:
参考来源:
必做项:
不允许:
产出物:
验收标准:
风险提示:
当前状态:
```

这样写的好处是:

- 不会只剩“做某某模块”这种空标题
- 不会漏掉风险和暂停条件
- 能直接回填到项目执行记录里

---

## 10. 当前推荐执行主线

本清单的执行主线固定为:

```text
P1-1 最小领域对象落地
P1-2 Metadata Store 落地
P1-3 md/txt 兼容索引改造
P1-4 P1 回归门
P2-1 ParserEngineRouter 固化
P2-2 DocumentIngestionService 落地
P2-3 MinerUParserAdapter 接入
P2-4 artifact 六件套落地
P2-5 ChunkBuilder / Indexer 落地
P2-6 doc_id 幂等清理
P2-7 Retrieval citation 基线
P2-8 P2 端到端门禁
P3-1 离线评测集与 dense baseline 固化
P3-2 BM25 + 向量混合召回
P3-3 明确 rerank 层
P3-4 离线评估指标和脚本
P3-5 P3 回归门禁
P3-6 文档、状态与默认策略收口
```

如果中间某一步没过门禁，不要跳着做后面的“更高级功能”。

---

## 11. 关联文档

- [docs/technical_fusion_decision_manual.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/technical_fusion_decision_manual.md>)
- [docs/oncall_rag_weknora_fusion_analysis_plan.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/oncall_rag_weknora_fusion_analysis_plan.md>)
- [docs/rag_ingestion_artifact_contract.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/rag_ingestion_artifact_contract.md>)
- [docs/weknora_r0_reuse_review.md](</Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21/docs/weknora_r0_reuse_review.md>)
- [DataWhale all-in-rag 混合检索](<https://github.com/datawhalechina/all-in-rag/blob/main/docs/chapter4/11_hybrid_search.md>)
- [DataWhale all-in-rag 系统评估](<https://github.com/datawhalechina/all-in-rag/blob/main/docs/chapter6/18_system_evaluation.md>)

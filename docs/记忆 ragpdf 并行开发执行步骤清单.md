# 记忆 RAG/PDF 并行开发执行步骤清单

日期：2026-06-08

状态：执行中。批次 0a 静态门已完成；批次 0b 已完成 MinerU CLI 最小 smoke 并修复 adapter 输出目录兼容；C 线 C1 `SessionMemoryStore` 已完成模块级实现和单测，C2 archive / C3 tool-result offload 已完成模块级 scaffold 和单测；B 线 B1 `pdf_profile_service` 已完成 metadata-only hook 和单测；B 线 B2 artifact validator warning-only 已完成模块级实现和单测；A 线 R0 已完成已有报告的静态 baseline summarizer 和摘要产物；A 线 R1 已完成默认关闭的 retrieval-mode policy hook，并新增 dense-only vs hybrid 对照 report runner。B 线已完成 PDF baseline report runner、固定样本、当前失败 PDF 的临时 MinerU baseline 报告、页码/表格/source_ref eval runner、受控真实重试 apply 和 after-retry 复核。清单已同步 `docs/路由升级方案.md`，把路由语义升级纳入 D 线，并明确 D0/D1/D2/D4 第一批可并行、D3 必须作为后置共享边界收口。RAG/PDF 数据门已更新：当前 3 个小样本文档均为 `indexed`；失败 PDF 已从 `index_failed` 推进到 `indexed`，写入 6 个 chunks，artifact validator 仍 pass；PDF page/table/source_ref eval 为 1/1；RAG 20q after-retry 为 16/20 passed、4 个 `answer_wrong`，unscoped 4q 为 4/4 passed，`data_not_indexed`、`not_ready` 和 source_ref gate 均清零。4 个 `answer_wrong` 已通过只读 triage report 归因：2 个是 expected doc 已召回但 expected keywords/上下文评分不满，2 个是 eval 指向的原始 PDF 仍在 pending review/import gate 外。RAG-06/RAG-07 的 keyword-gap 桶已进一步生成只读报告：RAG-06 的 expected keywords 在目标手册中不存在，RAG-07 的 `API` 存在于目标手册其他 chunk 但没有进入当前召回的目标文档 chunk。已按 eval 层修正 RAG-06/RAG-07：RAG-06 改为当前手册 corpus 中真实存在的 Runbook 索引问题，RAG-07 保留原 query 但把评分关键词从背景词 `API` 调整为升级流程关键词 `Ack` / `升级`。修正后 RAG 20q 为 18/20 passed，keyword-gap rows=0。RAG-12/RAG-13 经产品定位判断为 out_of_scope：环保监测/合规披露不进入当前 oncall + 工艺 + AIOps 小样本 baseline，相关 6 个唯一 PDF 文件组在 review 清单中标记为 `rejected_current_kb`，不导入当前知识库。当前有效基线改为 `department_rag_18q_current_scope_20260608`，复跑结果 18/18 passed；18/18 只代表当前 3 个 indexed 文档的小样本 current-scope baseline，不代表长期评测充分性。后续评测扩展应优先补权限隔离、scope 锁定、跨库不串、citation 准确性和 PDF 页码引用等系统能力题。

来源文档：

- `docs/RAG 系统优化方案.md`
- `docs/pdf 解析优化方案.md`
- `docs/记忆系统修改指南.md`
- `docs/路由升级方案.md`
- `docs/项目完整架构.md`
- `PROJECT_STATE.md`

适用范围：RAG 系统优化、PDF 解析优化、记忆系统改造、路由语义升级四条线并行推进时的步骤、边界、门禁和验收顺序。

## 0. 结论

三份方案和路由升级方案没有根本冲突，可以并行开发。

但并行只限于独立新增层、shadow/eval 层、warning-only 校验层和单模块接口层。不能同时抢改下列共享边界：

- `RetrievalService` / `ChunkEvidenceMapper` / `SourceRef` / `CitationVerifier`
- `DocumentAccessService` / `PermissionService` / `RagAdapter`
- `ToolGateway` / `ToolExecutionFacade` / ToolProvider Adapter
- parser artifact contract 和 schema fatal 规则
- session ownership / `SessionAccess` / 会话持久化源头
- routing semantics / `StrategyRouter` / `QueryIntentRouter` / 未来 `EnterpriseIntentRouter`

第一阶段目标不是证明效果提升，而是把四条线都推进到“代码可验证、数据门禁清晰、后续效果验收有基线”的状态。

## 0.1 当前事实

执行前必须按当前仓库状态重新确认，不允许沿用口头记忆。

截至本清单写入时，`PROJECT_STATE.md` 记录的关键事实是：

- RAG 小样本当前不是 `20/20 not_ready`。
- after-retry `department_rag_20q` 当前为 20 total、16 passed、4 failed。
- after-retry 失败分类为 `answer_wrong=4`，`data_not_indexed=0`。
- `evals/knowledge_base/reports/rag_answer_failure_triage_after_pdf_retry_20260608.json` 已把 4 个 `answer_wrong` 分成 `expected_doc_retrieved_keyword_gap=2` 和 `eval_asset_pending_review_import=2`。
- `evals/knowledge_base/reports/rag_keyword_gap_after_pdf_retry_20260608.json` 已把 RAG-06/RAG-07 进一步分为 `expected_keyword_absent_from_expected_doc=1` 和 `expected_keyword_available_outside_top_context=1`。
- `evals/knowledge_base/evalsets/department_rag_20q.jsonl` 已完成两处 eval 期望修正：RAG-06 不再要求当前手册不存在的 `MCP` / `工具`，改为 Runbook 索引样本；RAG-07 不再强制把背景词 `API` 当作必答关键词，改为 `Ack` / `升级`。
- RAG-06 是题目替换，不是评分放松：原始 `MCP 工具调用失败怎么排查` 仍代表一个真实的 corpus 覆盖缺口。本次替换不代表系统获得了回答 MCP 工具排查问题的能力；若未来要覆盖 MCP，必须通过补充资料和新增/恢复对应 eval 样本解决，而不是靠检索优化或继续改当前 baseline。
- after eval 期望修正的 `department_rag_20q` 当前为 20 total、18 passed、2 failed，失败分类为 `answer_wrong=2`。
- `department_rag_20q.jsonl` 现在保留为历史审计 evalset，不再为了当前小样本 baseline 继续追求 20/20。RAG-12/RAG-13 的失败原因保留在 20q 报告中，作为“曾经存在但当前范围外”的证据。
- 当前有效 baseline 是 `evals/knowledge_base/evalsets/department_rag_18q_current_scope_20260608.jsonl`，它从 20q 中排除 RAG-12/RAG-13，保留 RAG-01 到 RAG-11、RAG-14 到 RAG-20 共 18 题。
- 18q 说明文件为 `evals/knowledge_base/evalsets/department_rag_18q_current_scope_20260608.md`，明确 RAG-12/RAG-13 属于 `out_of_scope`，因为环保监测 / 合规披露不属于当前 oncall + 工艺 + AIOps 小样本 baseline。
- 18q 复跑报告为 `evals/knowledge_base/reports/department_rag_eval_department_rag_18q_current_scope_20260608.json` / `.md`：18 total、18 passed、0 failed、0 not_ready、`all_source_ref_resolvable=true`。
- 18q baseline 摘要为 `evals/knowledge_base/reports/rag_baseline_18q_current_scope_20260608.json` / `.md`：合并 18q 与 unscoped 4q 后 `failure_totals={"passed": 22}`，`data_not_indexed_present=false`、`source_ref_unresolvable_present=false`、`not_ready_present=false`。
- `evals/knowledge_base/reports/rag_baseline_after_eval_expectation_fix_20260608.json` 显示 `data_not_indexed_present=false`、`source_ref_unresolvable_present=false`、`not_ready_present=false`。
- `evals/knowledge_base/reports/rag_answer_failure_triage_after_eval_expectation_fix_20260608.json` 显示剩余 2 个 `answer_wrong` 均为 `eval_asset_pending_review_import`。
- `evals/knowledge_base/reports/rag_keyword_gap_after_eval_expectation_fix_20260608.json` 显示 `total_keyword_gap_rows=0`。
- `docs/pending_pdf_review_decision_list_20260608.md` 已更新为当前决策清单：12 条 manifest 记录按 SHA1 去重后是 6 个唯一 PDF 文件组，当前决策均为 `rejected_current_kb`；清单未修改 manifest、未启用 import、未改 `current_import_state.json`。
- 原始 manifest 中这 12 条 PDF 记录仍保持 `review_status=pending`、`import_enabled=false`。这是底层资产状态，不代表当前 baseline 仍等待导入；当前产品决策是不导入当前知识库。
- 18/18 只能说明当前 3 个 indexed 文档的小样本 current-scope baseline 通过，不代表长期 RAG 评测充分。后续应新建评测体系扩展任务，优先补权限隔离、scope 锁定、跨库不串、citation 准确性、PDF 页码引用等系统能力题，而不是继续用环保资料追当前 20/20。
- after-retry `department_rag_unscoped_4q` 当前为 4 total、4 passed、0 failed。
- 两份报告的 `all_source_ref_resolvable=true`。
- 当前小样本文档状态为 3 个部门文档，`indexed=3`、`index_failed=0`。
- 已修复的 PDF 是 `craft_dept/doc_27b282ca-97c3-5170-af0a-282f2e9122a1`，文件名为 `线上故障处理_现场设备工艺版.pdf`。
- `data/knowledge_ingestion/original_files_manifest.json` 中 12 个受支持原始 PDF 资产仍是 `review_status=pending`、`import_enabled=false`；当前 review 清单已把它们标记为 `rejected_current_kb`，因此不再作为当前 18q baseline 的 blocker。
- 旧的长期记忆 P6/P7 主线在 `PROJECT_STATE.md` 中处于冻结状态。若本清单执行记忆线，只允许执行 `docs/记忆系统修改指南.md` 中明确重开的短期会话记忆 / offload / 检索增强步骤，不能顺手重启旧 P6/P7 调参。

## 0.2 四线定义

| 线 | 名称 | 当前第一阶段目标 | 第一阶段不能做 |
|---|---|---|---|
| A | RAG 系统优化 | R0 baseline、R1 retrieval mode policy shadow/eval | 不做 R2 query rewrite shadow、R3 multi-query、R4 rerank、R5 answer active、R7 self-correction |
| B | PDF 解析优化 | P0 baseline、P1 pdf profile、P2 artifact validator warning-only | 不直接改 MinerU 参数、不换 parser、不把 schema warning 直接切 fatal、不提前暴露 P4 工具 |
| C | 记忆系统改造 | P0 边界确认、P1 SessionMemoryStore、P2 archive summary、P3 tool result offload | 不污染 RAG citation、不默认注入 prompt、不做 memory vector/RRF、不自动 promotion |
| D | 路由语义升级 | D0/D1/D2/D4 shadow 诊断字段和 eval 准备 | 不做 D3 RAG 分流上移、不改真实执行路由、不绕开 ToolGateway / 权限 / 人审链路 |

## 0.3 并行和验收的区别

四条线可以并行开工，但不能同时完成效果验收。

| 类型 | 是否可以并行 | 说明 |
|---|---:|---|
| 代码实现 | 可以 | 只要每条线不改共享边界和默认线上行为 |
| 单元测试 | 可以 | 每条线先测自己的模块接口、shadow 诊断和降级路径 |
| 集成 smoke | 部分可以 | RAG/PDF 依赖 indexed 文档和 MinerU，Memory P0/P1 依赖较少 |
| 效果验收 | 不能一概并行 | RAG/PDF 必须等 reviewed import、PDF index failure、`data_not_indexed` 等门禁解除 |

## 0.4 统一门禁

### 代码开工门

满足以下条件即可开工：

- 当前工作区改动已识别，不能混入无关变更。
- 三份源方案存在。
- 本次任务明确只做一条线或一个小切片。
- 默认行为保持关闭、shadow、warning-only 或 local-only。

### 集成验收门

RAG / PDF 的集成验收需要：

- reviewed import 至少有一批样本批准并导入。
- 当前 `index_failed` PDF 有明确处理结果：修复、替换样本或标记为已知阻塞。
- RAG eval 不再主要被 `data_not_indexed` 主导。
- PDF baseline 能区分 MinerU 不可用、样本损坏、artifact schema 问题和检索问题。

Memory 的 P0/P1 集成验收不依赖 indexed 文档，但需要：

- 明确 `SessionAccess` / session owner 仍是会话所有权边界。
- `SessionMemoryStore` 不成为第二套用户可见聊天历史。
- store 失败时 `/api/chat`、`/api/chat_stream`、`/api/aiops` 只能 degraded，不能主流程失败。

### 效果验收门

只有满足下列条件，才能声称 RAG/PDF 效果验收通过：

- R0 baseline 可复跑。
- before/after 使用同一 evalset 和同一数据状态。
- failure category 不再主要是 `data_not_indexed`、`mineru_unavailable` 或 `artifact_missing`。
- `wrong_scope`、`citation_unresolvable`、权限泄漏均为硬失败。
- p50/p95 latency 有对照，且没有超过方案指定门槛。

## 1. 全局预检

在任一条线开工前执行。

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
pwd
git status --short
test -f "docs/RAG 系统优化方案.md"
test -f "docs/pdf 解析优化方案.md"
test -f "docs/记忆系统修改指南.md"
test -f "docs/项目完整架构.md"
test -f PROJECT_STATE.md
```

确认当前门禁事实：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
rg -n "department_rag_20q|data_not_indexed|index_failed|original_files_manifest|Memory work is now frozen|RAG 系统优化方案" PROJECT_STATE.md
rg -n "R0 baseline|R1 retrieval mode|R2 query rewrite|P2 gate|SourceRef|ToolGateway" "docs/RAG 系统优化方案.md"
rg -n "MinerU CLI|pdf_profile|warning-only|DocumentAccessService|read_document_page|extract_document_table" "docs/pdf 解析优化方案.md"
rg -n "SessionMemoryStore|memory hit 不生成 RAG|memory_mode=off|vector/RRF|不要替换现有 RAG 主链路" "docs/记忆系统修改指南.md"
```

验收标准：

- 能说清当前 RAG eval 是多少题通过、多少题失败、失败原因是什么。
- 能说清当前 PDF blocker 是 MinerU、样本、artifact、索引还是权限。
- 能说清本次是否显式重开记忆线，以及是否仍保持旧 P6/P7 冻结。

## 2. 共享边界锁定

四条线开工前先锁定共享边界，后续 PR 或 commit 里不能把这些边界改成多套实现。

| 边界 | 权威模块 | 允许新增 | 禁止事项 |
|---|---|---|---|
| citation / source evidence | `RetrievalService`、`ChunkEvidenceMapper`、`CitationVerifier` | 增加字段校验、trace、eval | 在 RAG rewrite、PDF 工具、Memory hit 中自己拼伪 `SourceRef` |
| 文档可见性 | `DocumentAccessService`、`PermissionService`、`RagAdapter` | 新工具调用前复用 `can_read_document(context, document)` | 只靠 `doc_id` 或 artifact 路径读文件 |
| 工具执行 | `ToolGateway`、`ToolExecutionFacade`、ToolProvider Adapter | 新 PDF 工具或 RAG 能力通过 provider 接入 | 直接塞进 legacy tool list 扩大绕行 |
| parser artifact | MinerU adapter、postprocess、`ArtifactChunkBuilderService` | warning-only validator、版本兼容 schema | pre-parse 诊断直接写 `quality_report.json` 或第一天切 fatal |
| 会话所有权 | `SessionAccess`、enterprise session repository | Agent prompt 专用 summary/live tail store | 新建第二套孤立 session owner 或把 raw messages 直接变 active memory |
| 路由语义 | `StrategyRouter`、`QueryIntentRouter`、未来 `EnterpriseIntentRouter` | 补 `domain` / `intent` / `approval_required` / `execution_mode` 诊断字段和 shadow eval | `QueryIntentRouter` 迁出 DB/权限/human_review 必须作为共享边界收口，不夹在 A/B/C/D 第一批任务里 |

验收标准：

- 任一条线的设计或实现都能指出自己使用了哪一个权威边界。
- 如果确实要改共享边界，必须单独开“共享边界收口”任务，不能夹在 A/B/C/D 任一条线里。
- D3 `QueryIntentRouter` 职责迁出属于共享边界收口，必须等 RAG R0/R1 baseline 稳定后单独推进，并且要先于 A 线 R2 query rewrite。

## 3. 共享数据门：reviewed import 和 indexed 文档

RAG 和 PDF 共同依赖真实 indexed 文档。

### 3.1 先确认 import gate

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
test -f data/knowledge_ingestion/original_files_manifest.json
test -f data/knowledge_ingestion/current_import_state.json
rg -n "\"review_status\"|\"import_enabled\"|\"status\"|index_failed|indexed" data/knowledge_ingestion
```

需要得到：

- 哪些样本已批准。
- 哪些样本已导入。
- 哪些样本已 indexed。
- 哪些样本 parse/index failed。
- 失败原因是否来自 PDF parser、queue、artifact schema、权限或 evalset 覆盖。

### 3.2 先修 blocker，不扩大导入

如果仍存在 pending review、PDF `index_failed`、大量 `data_not_indexed`：

- 可以写 A/B/C/D 的模块代码、shadow 诊断和单测。
- 可以跑 dry-run、profile、validator warning report。
- 不可以声称 RAG/PDF 效果验收通过。
- 不可以直接全量导入来掩盖小样本问题。

验收标准：

- 有一份当前 import gate 摘要写入对应开发记录或阶段报告。
- 每个 blocker 都归类为 `review_pending`、`mineru_unavailable`、`parse_failed`、`artifact_missing`、`schema_warning`、`schema_fatal_candidate`、`index_failed`、`data_not_indexed` 或 `permission_filtered`。

## 4. A 线：RAG 系统优化步骤

来源：`docs/RAG 系统优化方案.md`

### A0：确认当前主链路

目标：确认 `/api/chat`、`/api/chat_stream`、`retrieve_knowledge`、`/api/knowledge-search` 当前分别使用什么 retrieval mode。

动作：

1. 读取当前配置和 `RetrievalQuery` 默认值。
2. 确认 `retrieve_knowledge()` 是否仍默认 `dense_only`。
3. 确认 `/api/knowledge-search` 是否已有 hybrid 入口或 diagnostics。
4. 确认 `RagAdapter.retrieve(context, query)` 仍经过 `DocumentAccessService`。

建议验证：

```bash
cd "/Users/cici/oncall agent/super_biz_agent_py-release-2026-03-21"
test -f tests/test_retrieval_service.py
test -f tests/test_p3_hybrid_retrieval.py
test -f tests/test_knowledge_search_diagnostics.py
uv run pytest tests/test_retrieval_service.py tests/test_p3_hybrid_retrieval.py tests/test_knowledge_search_diagnostics.py -q --no-cov
```

如果任一测试文件不存在，不要把验证失败直接归因于 RAG 主链路。先记录缺失文件，再选择当前仓库已有的等价 retrieval / hybrid / diagnostics 测试入口。

最低产物：

- `rag_baseline_<timestamp>.json`
- `rag_baseline_<timestamp>.md`
- 记录 retrieval mode、failure category、source_ref integrity、p50/p95 latency。

### A1：R0 baseline

目标：让 baseline 可复跑，而不是先改召回策略。

动作：

1. 固定 evalset 和数据状态。
2. 跑 `department_rag_20q` 和 unscoped 4q。
3. 分桶统计 `data_not_indexed`、`permission_filtered`、`retrieval_no_hit`、`answer_wrong`、`citation_unresolvable`。
4. 单独记录当前 `index_failed` PDF 对 RAG eval 的影响。

通过条件：

- baseline 报告可复跑。
- `source_ref` 可解析性单独统计，不和资料覆盖率混为一谈。
- 如果 `data_not_indexed` 仍然主导失败，只能进入数据门修复，不能进入 R2/R3。

### A2：R1 retrieval mode policy shadow

目标：在不改变线上默认的前提下比较 dense-only 与 hybrid。

动作：

1. 增加或确认 `rag_default_retrieval_mode` 配置只由配置、preset 或企业编排层控制。
2. 跑 dense-only vs hybrid 对照。
3. 记录 dense/sparse hit count、RRF result count、wrong_scope、citation correctness、latency。

禁止：

- 不把 `retrieval_mode` 暴露成模型可随意传入的工具参数。
- 不默认打开 `hybrid_rerank`。
- 不改变 citation identity。

通过条件：

- hybrid 不增加 `wrong_scope`。
- citation correctness 不退化。
- p95 latency 不超过 R0 baseline 的门槛。

### A3：R2 query rewrite shadow 后置门

R2 不进入第一阶段。

进入 R2 前必须满足：

- R0 baseline 可复跑。
- R1 dense-only vs hybrid 有有效结果。
- 不是 rewrite 前后都搜不到。
- protected terms、scope lock、file name lock 有单测。
- `data_not_indexed` 不再是主要失败原因。

否则 R2 只能写接口草图或测试样例，不能声称 shadow 数据有意义。

## 5. B 线：PDF 解析优化步骤

来源：`docs/pdf 解析优化方案.md`

### B0：PDF baseline 样本和 MinerU health

目标：先区分环境不可用、样本问题和 parser/postprocess 问题。

动作：

1. 固定 PDF baseline 样本：原生文本、扫描或疑似扫描、图文混排、长表格、多栏版式、已知失败 PDF。
2. 检查 MinerU CLI 路径存在、可执行。
3. 用一个已知小 PDF 做 MinerU smoke。
4. 记录 parser version、postprocess version、返回码、耗时、六件套 artifact 是否存在。

通过条件：

- MinerU 不可用时报告标 `mineru_unavailable`。
- 样本损坏时报告标 `sample_invalid`。
- 不能把外部 CLI 问题误判成 PDF 优化失败。

### B1：P1 `pdf_profile_service`

目标：解析前生成轻量 `DocumentRecord.metadata.pdf_profile`。

动作：

1. 第一版优先评估 `pypdf` 做页数、加密状态、文本层抽样。
2. 只写 `DocumentRecord.metadata.pdf_profile`。
3. 不写 `quality_report.json`。
4. 不改 parser 路由。
5. `.md/.txt` 路径必须不受影响。

禁止：

- pre-parse 诊断模块不创建、不覆盖、不修补 `artifact_manifest.json`、`quality_report.json`、`chunks.json`、`tables.json`、`blocks.json`。
- `risk_flags` 只能用于诊断、展示和 eval 分组，不能自动跳过检索或拒绝回答。

通过条件：

- 原生文本 PDF 能识别为低风险或 `native_text`。
- 扫描或疑似扫描 PDF 能产生风险标记。
- 图文混排 PDF 能产生 `mixed` 或 `mixed_layout` 风险标记。
- profile 失败时主流程 degraded 或 warning，不造成非损坏 PDF 上传失败。

### B2：P2 artifact validator warning-only

目标：把 artifact schema 从约定字段变成可报告字段，但第一阶段不直接 fatal。

动作：

1. 为 `chunks.json`、`tables.json`、`blocks.json`、`quality_report.json` 增加 validator。
2. 首版只输出 warning report。
3. 按 `artifact_manifest.json` 的 `parser_version` 和 `postprocess_version` 做兼容。
4. 扫描现有 artifact，统计 pass、warning、fatal candidate。

禁止：

- 第一版不能把历史 artifact 大面积判失败。
- 不能把坏 table row 悄悄降级成普通 text chunk。
- 不能在 pass rate 和人工归类不足时切 fatal。

通过条件：

- validator report 可复跑。
- fatal candidate 有具体原因和样本路径。
- artifact 必需文件缺失能被报告。

### B3：PDF eval 小闭环

目标：先验证页码、表格和 source_ref 可回查，而不是直接暴露 Agent 工具。

动作：

1. 新增或扩展 `pdf_page_citation` evalset。
2. 新增或扩展 `pdf_table_qa` evalset。
3. 指标至少包含 parse success、index success、source_ref resolvable、page accuracy、table row score。
4. 至少保留 1 道图表或图片相关样本题，用来显式暴露当前不能理解图表内容的缺口。

通过条件：

- PDF eval 能区分 parser artifact 问题、索引问题、检索问题和回答问题。
- `source_ref.page_start/page_end` 是页码判断来源，不能从 `citation_text` 字符串解析。

### B4：P4 工具后置门

`read_document_page`、`extract_document_table`、`get_document_source` 不进入第一阶段效果验收。

进入 P4 前必须满足：

- `blocks.json` 的 page coverage 达到门槛。
- 表格样本中 `table_id/page_start/page_end/rows` 稳定。
- `source_ref_resolvable_rate` 稳定。
- 工具能通过 metadata store 找到 `DocumentRecord`。
- 工具调用前能执行 `DocumentAccessService.can_read_document(context, document)`。
- 工具接入走 `ToolExecutionFacade` / ToolGateway 规则。

`get_document_source` 是 P4b，不和 `read_document_page`、`extract_document_table` 抢第一轮。

## 6. C 线：记忆系统改造步骤

来源：`docs/记忆系统修改指南.md`

### C0：确认是否显式重开记忆线

目标：避免和当前冻结的旧记忆主线混淆。

动作：

1. 确认本次用户明确要求继续记忆线。
2. 确认旧 P6/P7 layered memory、shadow、full eval 不被顺手重启。
3. 确认 `MemoryStore`、`MemoryEvidenceStore`、`MemorySaver`、`SessionAccess` 的真实边界。
4. 统计当前 memory records 按 owner、namespace、type、status 的数量。

通过条件：

- 能说明本次做的是短期 session memory / archive / offload，不是旧长期记忆重新调参。
- 能说明 memory guidance 不是 RAG citation。

### C1：P1 `SessionMemoryStore`

目标：为 Agent prompt 恢复提供 summary + live tail，不替代用户可见聊天历史。

动作：

1. 先写 `tests/test_session_memory_store.py`。
2. 定义 `SessionMemoryStore` 逻辑接口。
3. P1 默认 Adapter 为 `SQLiteSessionMemoryStore`。
4. 生产默认复用现有 enterprise chat session owner 边界，优先同库新增表。
5. `InMemorySessionMemoryStore` 只用于单测。
6. Redis 未来只能做 read-through / write-through cache，不能做 source of truth。

禁止：

- 不新建第二套孤立 session owner。
- 不把 raw messages 直接写成 `MemoryRecord(status=active)`。
- 不绕过 `memory_mode` 默认强塞 prompt。

通过条件：

- 重启 store 后同一 `session_id` 能恢复 latest summary + live tail。
- store 抛错时 `/api/chat`、`/api/chat_stream`、`/api/aiops` 不失败，只记录 degraded。
- `memory_mode=off` 时不注入 memory。

### C2：P2 archive + summary

目标：超过阈值时归档旧上下文，prompt 只使用摘要和 live tail。

动作：

1. 先根据真实 session/tool-result 长度设定阈值。
2. 超过 `live_tail_max_messages` 后生成 archive。
3. 旧内容生成 overview / abstract。
4. prompt 只拼 summary + live tail，不无限拼 raw messages。

通过条件：

- archive 有 ref 可回查。
- summary 失败时保留原始 archive ref 和 fallback abstract。
- prompt token 增长可控。

### C3：P3 AIOps tool result offload

目标：长工具结果写 refs，planner / graph / replanner 只看到短摘要。

动作：

1. 先只接 AIOps 长工具结果，不扩到 RAG citation。
2. 每条长结果生成 `result_ref`。
3. prompt 中只放摘要。
4. `result_ref` 能回查原文。

禁止：

- 不把 offload ref 当成 RAG `SourceRef`。
- 不把 tool result summary 当成事实 citation。

通过条件：

- 长日志不会直接塞进 prompt。
- offload 关闭时仍走原始工具结果路径。
- offload 失败时 AIOps 主流程 degraded，不硬失败。

### C4：C 线后置门

下列步骤不进入第一阶段：

- P4 DiagnosisCanvas / Mermaid
- P5 长期候选抽取
- P6 memory FTS
- P7 memory vector/RRF

进入 P6/P7 前必须证明：

- active memory 数量和查询失败样本确实需要检索增强。
- lexical / hierarchical retrieval 召回不足。
- vector 只是 retrieval view，不是 source of truth。
- memory RRF trace 与 RAG RRF trace 分开。
- memory hit 不生成 RAG `SourceRef`，不污染 `citation_text`。

## 7. 推荐并行排期

### 批次 0：预检确认

批次 0 分成 0a 和 0b。0a 是纯文件级确认，今天就能做；0b 是运行时 smoke，需要 Milvus、MinerU CLI、后端服务或相关外部依赖准备好。

### 批次 0a：纯文件级确认

四线共同执行：

1. 全局预检。
2. 共享边界锁定。
3. 从 `PROJECT_STATE.md`、`data/knowledge_ingestion/*`、已有 report 文件读取当前 import gate 摘要。
4. 从已有 RAG eval report 或 `PROJECT_STATE.md` 读取当前 RAG eval 摘要。
5. 确认 RAG A0 建议测试文件是否存在。
6. 从文档和配置读取 MinerU CLI 路径、PDF baseline 样本清单和已知失败 PDF。
7. 当前 memory freeze / reopen 摘要。

产物：

- 一个静态门禁报告。
- 不改运行时代码。
- 不要求 Milvus、MinerU、后端服务已经启动。

### 批次 0b：运行时 smoke

运行时依赖准备好后执行：

1. 跑 RAG eval 或最小 retrieval smoke，确认当前报告不是旧文件误读。
2. 跑 MinerU CLI health check 和小 PDF smoke。
3. 如需人工 API smoke，确认后端是当前代码启动的进程。
4. 记录运行时不可用原因，例如 `milvus_unavailable`、`mineru_unavailable`、`backend_not_running`、`eval_env_not_ready`。

产物：

- 一个运行时 smoke 报告。
- 如果运行时依赖不可用，批次 0b 可以标为 blocked，但不阻塞批次 1 中不依赖运行时的单模块代码和单测。

### 批次 1：可以并行写代码

A 线：

- R0 baseline runner / report 整理。
- R1 retrieval mode policy shadow 的配置和 diagnostics，不改默认值。

B 线：

- `pdf_profile_service`。
- artifact validator warning-only。
- PDF baseline report。

C 线：

- `SessionMemoryStore` 接口和 SQLite Adapter。
- C0 边界确认。
- C1 `SessionMemoryStore` 模块接口、SQLite Adapter 和单测。
- C2 archive + summary 的接口草图或最小测试。
- C3 AIOps tool result offload 的接口草图或最小测试。

C 线 P0/P1 不依赖 reviewed import、indexed 文档或 MinerU，因此可以在批次 1 后独立验收模块行为。C2/P2 和 C3/P3 若要调真实阈值或接入真实长 session / tool result，再等待运行时数据和集成环境。

D 线：

- D0 shadow routing 补 `domain` / `intent` / `approval_required` / `execution_mode` 诊断字段。
- D1 数据库路由语义修正，保留 `domain=database`，只做 shadow 诊断，不改数据库确认链路。
- D2 AIOps 路由语义修正，区分 `diagnose` / `remediate`，不扩大 AIOps 工具池。
- D4 LLM 意图识别 shadow/eval，小范围、低置信度和抽样优先，不改变真实执行。

D 线 D0/D1/D2/D4 第一批只允许触碰 `app/enterprise/routing/*` 及对应 shadow/eval 测试。若需要改 `app/enterprise/rag/query_intent.py`，必须退出批次 1，转为 D3 共享边界收口。

批次 1 禁止：

- RAG R2 query rewrite shadow。
- PDF P4 Agent 工具。
- memory vector/RRF。
- schema fatal。
- 默认 hybrid/rerank/LLM answer。
- D3 RAG 内非 RAG 分流上移。
- 改真实执行路由或绕开数据库确认、权限、人审链路。

### 批次 2：数据门修复

目标：解除 RAG/PDF 效果验收瓶颈。批次 2 只约束 A 线和 B 线的效果验收，不阻塞 C 线 P0/P1 的模块验收。

动作：

1. 完成 reviewed import 的人工批准或明确拒绝。
2. 处理当前 `index_failed` PDF：修复、替换、或作为已知失败样本保留。
3. 让 RAG eval 失败不再主要由 `data_not_indexed` 主导。
4. 让 PDF baseline 能跑出 parser/artifact/index/eval 分层结果。

产物：

- reviewed import gate report。
- PDF baseline report。
- RAG R0 baseline report。

### 批次 3：后续增强

只有批次 2 通过后，才允许进入：

- RAG R2 query rewrite shadow。
- RAG R3 multi-query shadow。
- RAG R4 rerank shadow。
- D3 RAG 内非 RAG 分流上移到统一企业意图层，作为共享边界收口任务。顺序必须是 A 线 R0/R1 baseline 稳定 -> D3 收口 `QueryIntentRouter` -> A 线 R2+ 基于新边界做 query rewrite。
- PDF P3 表格页码增强。
- PDF P4a `read_document_page` / `extract_document_table`。
- Memory P2/P3 的真实阈值调优和 RAG/AIOps prompt 集成，但仍受 `memory_mode` 控制。

### 批次 4：高风险能力

只有有 eval 证据和明确需求时才允许进入：

- RAG R5 LLM answer shadow / active。
- RAG R7 bounded self-correction。
- PDF P4b `get_document_source`。
- PDF P6 多模态图表理解。
- Memory P5 candidate/review。
- Memory P6 FTS。
- Memory P7 vector/RRF。
- D5 前端路由诊断展示。
- D6 执行路由灰度。

## 8. 每条线的最小完成定义

### A 线最小完成

- R0 baseline 报告可复跑。
- R1 dense-only vs hybrid 对照可复跑。
- 默认线上行为不变。
- 权限 scope 不扩大。
- `source_ref` / citation identity 不变。
- 开发记录写明是否仍被 import gate 阻塞。

### B 线最小完成

- MinerU health 有明确结果。
- `pdf_profile` 只写 metadata。
- validator warning-only report 可复跑。
- PDF eval 至少能跑页码和表格小样本。
- 没有把 `risk_flags` 用成自动拒答依据。
- 没有提前暴露绕过权限的 artifact 工具。

### C 线最小完成

#### C0/P1 独立模块验收

- `SessionMemoryStore` 接口和默认 Adapter 有测试。
- session owner 仍复用现有 `SessionAccess` 边界。
- `memory_mode=off` 时无注入。
- store/offload 失败时主流程 degraded。
- memory guidance 不污染 RAG `SourceRef` / `citation_text`。
- 旧 P6/P7 记忆工作没有被顺手重启。

以上 C0/P1 条件不依赖 reviewed import、indexed 文档、Milvus 或 MinerU，可以在批次 1 后独立验收。

#### C2/P3 集成验收

- archive threshold 使用真实 session / tool-result 长度校准。
- tool result offload 在 AIOps 长日志路径上验证 `result_ref` 可回查。
- 接入 RAG/AIOps prompt 时仍受 `memory_mode` 控制。
- offload / summary 失败时主流程 degraded，不硬失败。

### D 线最小完成

#### D0/D1/D2/D4 第一批 shadow 诊断验收

- `app/enterprise/routing/*` 的 shadow routing 诊断字段可复跑，至少包含 `domain`、`intent`、`approval_required`、`execution_mode`。
- 数据库路由保持 `domain=database`，不绕过数据库确认链路、权限校验或审计。
- AIOps 路由能区分 `diagnose` / `remediate` 语义，但不扩大 AIOps 工具池。
- LLM 意图识别只做 shadow/eval，不改变真实执行路由。
- 不触碰 `app/enterprise/rag/query_intent.py`；一旦需要迁出 DB/权限/human_review 职责，必须转入 D3 共享边界收口。

#### D3 共享边界收口验收

- D3 只能在 A 线 R0/R1 baseline 稳定后开始。
- D3 必须先于 A 线 R2 query rewrite 完成，确保 R2 基于职责迁出后的干净 `QueryIntentRouter` 边界。
- D3 变更必须单独记录影响范围、迁移前后 intent 字段、回归测试和 shadow/eval 对照，不能夹在 RAG、数据库、PDF 或 Memory 的功能任务里。

## 9. 记录要求

每个批次结束都要更新对应记录。

RAG/PDF 相关：

- `docs/rag_fusion_development_record.md`
- `PROJECT_STATE.md`

Memory 相关：

- `docs/memory_fusion_development_record.md`
- `PROJECT_STATE.md`

记录必须包含：

- 为什么现在做这个批次。
- 改了哪些文件。
- 触碰了哪些共享边界。
- 哪些门禁通过。
- 哪些门禁仍阻塞。
- 跑了什么测试或 eval。
- 哪些能力只是代码完成，不能称为效果验收通过。

## 10. 最终判断规则

可以说：

- “三份方案和路由升级方案无根本冲突。”
- “A/B/C/D 四线可以并行写第一阶段代码。”
- “Memory P0/P1 可以先验收模块行为。”
- “RAG/PDF 第一阶段可以完成 baseline、profile、warning-only validator、shadow/eval 基础设施。”

不能说：

- “RAG 效果已经提升”，除非 before/after eval 通过。
- “PDF 解析能力已经生产可用”，除非 MinerU、artifact、index、PDF eval 都过门。
- “query rewrite shadow 有收益”，除非 R0/R1 baseline 有有效召回对照。
- “Memory 可以作为事实引用”，memory 只能是 agent guidance。
- “reviewed import 已完成”，除非 manifest review 和 import state 真的更新。

一句话执行口径：

> 四线可以并行开工，但第一阶段只做可回滚、可关闭、可观测的基础切片；RAG/PDF 效果验收必须等 reviewed import、indexed 文档、MinerU baseline 和 `data_not_indexed` 门禁解除后再判断；D3 必须等 RAG R0/R1 baseline 稳定后作为共享边界收口单独推进。

## 11. 当前执行进展

### 2026-06-08 批次 0a + C1

已完成：

- 批次 0a 纯文件级确认，报告见 `docs/记忆_ragpdf_并行开发_batch0a_static_gate_report.md`。
- A0 建议测试文件存在性确认：`tests/test_retrieval_service.py`、`tests/test_p3_hybrid_retrieval.py`、`tests/test_knowledge_search_diagnostics.py` 均存在。
- C 线 C1 模块级实现：新增 `SessionMemorySnapshot` / `SessionMemoryMessage`、`SessionMemoryStore` Protocol、`SQLiteSessionMemoryStore`、`InMemorySessionMemoryStore` 和 `tests/test_session_memory_store.py`。
- C1 仅新增短期 session memory store，没有接入 RAG/AIOps prompt，没有改变 `memory_mode=off` 行为，没有生成 RAG `SourceRef`。
- B 线 B1 metadata-only 实现：新增 `PdfProfileService`，在 `DocumentIngestionService.ingest_upload()` 的 `DocumentRecord` 构造后、metadata store 首次 upsert 前写入 `metadata.pdf_profile`；只对 PDF 生效，profile 失败时记录 `profile_status=failed` 并继续上传。
- B1 引入 `pypdf>=6.1.3,<7.0.0`，用于页数、加密状态和文本层抽样；没有引入 PyMuPDF / pdfplumber，没有修改 MinerU parser route 或 artifact 合同。
- B 线 B2 warning-only 实现：新增 `ArtifactValidatorService`，可对 artifact manifest、必需文件、JSON 结构和 `quality_report` warning/fatal candidate 生成报告；不接入 `prepare_artifacts_for_index()`，不替换 `ArtifactManifestService.validate_manifest()`。
- A 线 R0 静态 baseline：新增 `evals/knowledge_base/rag_baseline_report.py`，从已有 department RAG eval JSON 汇总 failure categories、source_ref gate 和 not_ready gate；生成 `evals/knowledge_base/reports/rag_baseline_static_summary_20260608.json` / `.md`。
- A 线 R1 policy hook：新增 `config.rag_default_retrieval_mode`，默认仍为 `dense_only`；`retrieve_knowledge()` 内部按配置构造 `RetrievalQuery.retrieval_mode`，但工具签名不暴露 `retrieval_mode` 参数，非法配置回退 `dense_only`。
- 批次 0b / B0 runtime smoke：MinerU CLI 可执行且能解析 1 页空白 PDF，输出 `blank_smoke.md` 和 `blank_smoke_content_list.json`；真实输出目录是 `out/<stem>/txt/`，因此修复 `MinerUParserAdapter` 兼容 method-named output dir。
- 当前失败业务 PDF 的临时 B0 smoke：`线上故障处理_现场设备工艺版.pdf` 在临时 metadata store / `/tmp` artifact 目录中可被 MinerU + postprocess 解析到 `index_pending`，六件套齐全，warning-only validator 为 pass；没有改真实 `uploads` 文档状态。
- B 线 PDF baseline report：新增 `evals/knowledge_base/pdf_baseline_report.py`、`tests/test_pdf_baseline_report.py`、`evals/knowledge_base/evalsets/pdf_baseline_samples_20260608.json` 和 `evals/knowledge_base/evalsets/pdf_baseline_current_failure_20260608.json`。
- 已生成 `evals/knowledge_base/reports/pdf_baseline_profile_20260608.json` / `.md`：5 个固定 PDF 样本 profile-only，`profile_status_counts={"ok": 5}`，MinerU 和 validator 均未运行。
- 已生成 `evals/knowledge_base/reports/pdf_baseline_current_failure_mineru_20260608.json` / `.md`：当前失败 PDF 在临时 metadata/artifact 目录中 `mineru_status_counts={"index_pending": 1}`、`validator_status_counts={"pass": 1}`；报告记录 `elapsed_ms`、parser config、六件套 artifact 文件名和 validator parser/postprocess version。
- PDF baseline report 的 `mineru_unavailable` 和 `sample_invalid` 分类已有单测，避免把 CLI 缺失或样本缺失误判成 parser 优化失败。
- C 线 C2/C3 模块级 scaffold：`SQLiteSessionMemoryStore` 新增 `archive_live_tail()` / `list_archives()` 和 `session_memory_archives` 表；新增 `SessionMemoryArchive`、`ToolResultRef`、`ToolResultRecord`、`SessionToolResultOffloadStore.offload_result()` / `get_result()`。
- C2/C3 当前只提供 owner-scoped archive/ref 能力，没有接入 `rag_agent_service.py`、`aiops_service.py`、planner/replanner prompt，也没有改变 `memory_mode=off` 或重启旧 P6/P7 vector/RRF。
- A 线 dense-only vs hybrid 对照 runner：新增 `evals/knowledge_base/retrieval_mode_comparison_report.py`、`tests/test_retrieval_mode_comparison_report.py` 和 `evals/knowledge_base/evalsets/retrieval_mode_comparison_samples_20260608.json`。
- 初始 `evals/knowledge_base/reports/retrieval_mode_comparison_20260608.json` / `.md` 曾记录 dense-only 与 hybrid 共 4 次调用均为 `not_ready`，阻塞错误为 `搜索失败: Collection 未初始化，请先调用 connect()`；after-retry 已通过 `VectorSearchService` 懒连接修复该 CLI/eval 初始化问题，见后续 after-retry 报告。
- B 线 PDF 页码/表格/source_ref artifact eval runner：新增 `evals/knowledge_base/pdf_page_table_eval_report.py`、`tests/test_pdf_page_table_eval_report.py` 和 `evals/knowledge_base/evalsets/pdf_page_table_eval_current_failure_20260608.json`。
- 已生成 `evals/knowledge_base/reports/pdf_page_table_eval_current_failure_20260608.json` / `.md`：当前失败 PDF 的临时 artifact 样本 `page_accuracy_passed=1/1`、`table_presence_passed=1/1`、`source_ref_resolvable_passed=0/1`、`artifact_missing_count=0`。这是 artifact-level 小闭环，不代表真实索引或 RAG citation 已通过。

当前未完成：

- 后端服务级 RAG smoke 仍未单独完成；目前 after-retry 和 18q current-scope 证据来自 CLI/eval runner 和 metadata/index 复核。
- A 线当前有效小样本 baseline 已切到 `department_rag_18q_current_scope_20260608` 并通过 18/18；20q 保留为历史审计，RAG-12/RAG-13 不再作为当前 baseline blocker。
- C2 archive summary、C3 AIOps tool result offload 已完成模块级存取 scaffold，但未接入真实 prompt/runtime，也未用真实长 session / tool result 校准阈值。
- 长期 RAG 评测体系仍未扩展；后续应补权限隔离、scope 锁定、跨库不串、citation 准确性、PDF 页码引用等系统能力题。

### 2026-06-08 验收后纠偏口径

本轮验收通过的范围是“第一阶段基础设施和模块级测试通过”，不是 RAG/PDF 效果验收通过。后续说明统一采用下面口径：

- A 线当前主链路默认仍是 `dense_only`；本轮只是新增配置化 policy hook 和 dense-only vs hybrid 对照 runner，没有把默认检索改成 hybrid，也没有把 `retrieval_mode` 暴露成模型可传工具参数。
- A 线对照 runner 的早期阻塞原因是 Milvus collection 未初始化；after-retry 已通过懒连接修复 CLI/eval 进程初始化，当前 dense-only vs hybrid 2 样本报告 `not_ready=0`、`wrong_scope=0`、`citation_incomplete=0`。这仍只是 shadow 对照基础设施，不是默认 hybrid 决策。
- B 线当前失败 PDF 已通过显式 `--apply` 走真实 workflow 修复到 `indexed`；该结论来自 metadata store、artifact validator、current_import_state 快照和 PDF page/table/source_ref after-retry report，不来自手改状态文件。
- B 线 page/table/source_ref after-retry eval 当前为 1/1，但 PDF Agent 工具和真实问答体验仍未做 P4 验收。
- C 线新增的是短期 session working-memory 的 archive/offload 模块，不是替换现有 `MemorySaver`、用户可见会话历史或长期 memory。C2/C3 未接入 prompt/runtime，不能说 AI 已经会自动使用 archive/offload。

### 2026-06-08 下一步开发顺序

优先级按 current-scope baseline 闭合后的顺序执行：

1. 20q 保留为历史审计 evalset：RAG-06/RAG-07 已作为 eval 期望问题处理；RAG-12/RAG-13 保留为 out_of_scope 证据，不再为了当前小样本 baseline 追 20/20。
2. 当前有效 baseline 是 `department_rag_18q_current_scope_20260608`：18q 排除环保监测 / 合规披露样本，复跑 18/18 passed；合并 unscoped 4q 的 baseline summary 为 22/22 passed，三个 gate 均为 false。
3. `docs/pending_pdf_review_decision_list_20260608.md` 已把 6 个唯一环保 / 合规 PDF 文件组标记为 `rejected_current_kb`；manifest 原始状态仍是 pending/disabled，但当前知识库不导入这些文件。
4. RAG-06 必须按“题目替换”记录：这次移除了一个当前 corpus 答不了的 MCP 样本，不代表系统获得了 MCP 工具排查能力；该缺口如果未来成为真实需求，应通过补资料和新增/恢复 MCP eval 解决。
5. 下一步不要继续改当前 20q 追分；应新建“评测体系扩展”任务，优先补系统能力题：权限隔离、scope 锁定、跨库不串、citation 准确性、PDF 页码引用。
6. A 线 R2/R3 仍不抢跑：只有在新的或扩展后的 evalset 证明失败来自检索表达、排序或召回，而不是 scope / corpus / 评分口径时，才进入 query rewrite、multi-query、rerank。
7. C 线等真实长 session / AIOps 长工具结果样本可用后，再做 runtime 接入和阈值校准；接入必须受 `memory_mode` 和 degraded/fallback 规则控制。

下一步开发禁止事项：

- 不直接手改 `data/knowledge_ingestion/current_import_state.json` 来制造 indexed 结论。
- 不跳过 `DocumentProcessingWorkflow` / metadata store / vector index service 的真实状态流。
- 不用 RAG-12/RAG-13 的 out_of_scope 环保样本驱动 R2 query rewrite 或 R3 multi-query；RAG-06/RAG-07 已作为 eval 期望问题处理，也不得再用来驱动检索算法变更。
- 不把 RAG-06 的 18/20 提升写成系统能力提升；它只能写成“当前 baseline 移除了一个 corpus 不覆盖的 MCP 题，并替换为当前手册可回答的 Runbook 运维题”。
- 不把 PDF artifact eval 的 1/1 page/table 结果说成 PDF 问答效果提升。
- 不把 C2/C3 archive/offload 默认注入 prompt。

### 2026-06-08 B 线受控重试 dry-run + apply 切片

已完成：

- 新增 `evals/knowledge_base/pdf_retry_report.py` 和 `tests/test_pdf_retry_report.py`。
- runner 默认 `dry_run`，只读取真实 metadata store 中的 `DocumentRecord`，判断指定 `doc_id` 是否符合受控重试条件，不调用 parser、不调用 indexer、不改 metadata。
- 显式 `--apply` 才会调用既有 `DocumentProcessingWorkflow.process_deferred_document(doc_id)`，复用 `DocumentIngestionService.process_deferred_document()`、`MinerUParserAdapter.parse_document()` 和 `VectorIndexService.index_document_record()` 的真实状态流。
- 已对当前失败 PDF 生成 dry-run 报告：`evals/knowledge_base/reports/pdf_retry_current_failure_dry_run_20260608.json` / `.md`。
- dry-run 结果为 `status=dry_run`、`would_retry=true`、`action=run_process_deferred_document`；原始文件存在，真实状态仍是 `index_failed`。
- dry-run 同时读取真实 artifact 目录并执行 warning-only validator，结果为 `artifact_validation.status=pass`、`issue_counts={"warning": 0, "fatal_candidate": 0}`。这说明当前真实 artifact 形状可以进入下一步受控重试判断，但仍不是 indexed 结论。
- 已显式执行 `--apply`，生成 `evals/knowledge_base/reports/pdf_retry_current_failure_apply_20260608.json` / `.md`。
- apply 结果为 `status=applied`、`status_before=index_failed`、`status_after=indexed`、`status_source_after=VectorIndexService._index_mineru_document_record`。
- 真实 metadata store 复核：该 PDF 当前 `doc_status=indexed`，`chunk_count=6`，所有 metadata `ChunkRecord.source_ref` 字段完整，`page_start=[1]`。
- 真实 artifact validator 复核：`artifact_status=pass`，`issue_counts={"warning": 0, "fatal_candidate": 0}`。
- `data/knowledge_ingestion/current_import_state.json` 已通过 `freeze_import_state()` 重新生成，当前 summary 为 `total_documents=3`、`status_counts={"indexed": 3}`。
- PDF page/table/source_ref after-retry 报告为 `page_accuracy_passed=1/1`、`table_presence_passed=1/1`、`source_ref_resolvable_passed=1/1`。
- A 线检索 CLI 修复 `VectorSearchService` Milvus 懒连接后，dense-only vs hybrid after-retry 报告不再 `not_ready`：dense 和 hybrid 均返回 6 个结果，`wrong_scope_count=0`、`citation_incomplete_count=0`、`not_ready_count=0`。
- RAG after-retry 报告：20q 为 16/20 passed，4 个 `answer_wrong`；unscoped 4q 为 4/4 passed；baseline gate 中 `data_not_indexed_present=false`、`source_ref_unresolvable_present=false`、`not_ready_present=false`。
- 新增 `evals/knowledge_base/rag_answer_failure_triage_report.py`、`tests/test_rag_answer_failure_triage_report.py`，生成 `evals/knowledge_base/reports/rag_answer_failure_triage_after_pdf_retry_20260608.json` / `.md`。
- triage 结果：RAG-06、RAG-07 为 `expected_doc_retrieved_keyword_gap`，目标文档 `superbiz_oncall_handbook.md` 已召回但 keyword/上下文评分只有 0.5；RAG-12、RAG-13 为 `eval_asset_pending_review_import`，相关土壤地下水/监测报告 PDF 资产仍在 `original_files_manifest.json` 中保持 `review_status=pending`、`import_enabled=false`。
- 新增 `evals/knowledge_base/rag_keyword_gap_report.py`、`tests/test_rag_keyword_gap_report.py`，生成 `evals/knowledge_base/reports/rag_keyword_gap_after_pdf_retry_20260608.json` / `.md`。
- keyword-gap 结果：RAG-06 为 `expected_keyword_absent_from_expected_doc`，`MCP` / `工具` 都不在目标手册 chunks 中，`工具` 只来自非目标检索文档；RAG-07 为 `expected_keyword_available_outside_top_context`，`API` 存在于目标手册 `c00006` / `c00009`，但当前目标文档召回 chunks 是 `c00002` / `c00011`，只覆盖了 `升级`。
- eval 期望修正：`evals/knowledge_base/evalsets/department_rag_20q.jsonl` 中 RAG-06 已从 `MCP 工具调用失败怎么排查` 改为 `常用 Runbook 索引有哪些故障处理文档`，expected keywords 改为 `Runbook` / `故障`；RAG-07 保留 `API 异常时 on-call 如何升级`，expected keywords 从 `API` / `升级` 改为 `Ack` / `升级`。
- RAG-06 硬边界：这不是系统修好了 MCP 问答，而是将一个当前 corpus 不覆盖的 MCP 题替换为当前手册可回答的 Runbook 运维题。原 MCP 问题仍作为潜在资料覆盖缺口保留在开发记录中，后续若要覆盖必须补充 MCP 资料。
- 修正后 RAG 20q 报告：`evals/knowledge_base/reports/department_rag_eval_department_rag_20q_after_eval_expectation_fix_20260608.json` / `.md` 为 18/20 passed、2 failed、`answer_wrong=2`，失败仅 RAG-12/RAG-13。
- 修正后 baseline：`evals/knowledge_base/reports/rag_baseline_after_eval_expectation_fix_20260608.json` / `.md` 合并 20q 与 unscoped 4q 后，`data_not_indexed_present=false`、`source_ref_unresolvable_present=false`、`not_ready_present=false`。
- 修正后 triage：`evals/knowledge_base/reports/rag_answer_failure_triage_after_eval_expectation_fix_20260608.json` / `.md` 显示剩余 2 个 `answer_wrong` 均为 `eval_asset_pending_review_import`。
- 修正后 keyword-gap：`evals/knowledge_base/reports/rag_keyword_gap_after_eval_expectation_fix_20260608.json` / `.md` 显示 `total_keyword_gap_rows=0`。
- 只读 review 清单：`docs/pending_pdf_review_decision_list_20260608.md` 列出 12 条 pending PDF 记录和 6 个 SHA1 去重后的唯一文件组，标注对应 `kb_id`、重复来源目录、RAG-12/RAG-13 关联关系和当前 `rejected_current_kb` 决策。

仍未完成：

- RAG 长期评测体系仍未扩展；当前 18/18 只是 3 个 indexed 文档的小样本 current-scope baseline，不代表长期充分。
- 12 个原始 PDF manifest 资产仍是 `review_status=pending`、`import_enabled=false`，但当前决策为 `rejected_current_kb`，不导入当前知识库；未来若要覆盖环保/EHS/合规，应另建 KB 范围、权限口径和 evalset。
- 当前没有把默认检索切到 hybrid，也没有把 `retrieval_mode` 暴露成模型可传工具参数。

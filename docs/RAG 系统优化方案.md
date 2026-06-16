# RAG 系统优化方案

## 1. 结论

当前 SuperBizAgent 已经不是一个只做向量检索的简单 RAG。它已经具备：

- 文档上传、解析、切块、状态流转和异步处理。
- DashScope embedding 与 Milvus 向量存储。
- 稳定的 `DocumentRecord`、`ChunkRecord`、`SourceRef`、`chunk_evidence` 证据链。
- dense 向量检索、BM25 稀疏检索、RRF 融合、可选 rerank。
- 查询意图路由、知识库 scope 选择、权限过滤和 citation verifier。
- 离线检索评估脚本与 `recall@k`、`precision@k`、`MRR` 等 IR 指标。

但如果按“更完整的 RAG 系统”要求看，当前仍有几个关键缺口：

1. `retrieve_knowledge()` 主工具默认仍走 `RetrievalQuery` 的 `dense_only`，不是默认多路召回。
2. 已有 query intent 和 scope 编排，但没有独立 query rewrite / multi-query 模块。
3. rerank 已有边界和本地 lexical baseline，但默认关闭，且还没有生产前 shadow/eval 结论。
4. 企业知识编排路径目前主要返回检索上下文，不是稳定的“检索后 LLM 生成 + 引用校验 + 失败修正”闭环。
5. 检索层指标较完整，生成层的相关性、准确性、全面性、faithfulness 和自修正验收还没有形成固定流程。

因此本方案不再只写“查询重写”，而是把它升级为 RAG 系统优化方案：

```text
先让主链路真正用上已有 hybrid 能力
再补 query rewrite / multi-query
再做 rerank shadow 与上线门槛
再补 LLM 生成、生成质量评估和有限自修正
```

## 2. 当前项目证据

### 2.1 已有能力

- `app/enterprise/rag/query_intent.py`
  - `QueryIntentRouter` 负责区分 `document_list`、`knowledge_qa`、`document_read`、`database`、`permission_request`、`human_review`、`plain_chat`。
  - `QueryIntentDecision` 已携带 `selected_kb_ids`、`selected_doc_ids`、`metadata.file_name` 和诊断字段。
- `app/enterprise/rag/retrieval_orchestrator.py`
  - `KnowledgeRetrievalOrchestrator` 根据 `knowledge_action` 调用 `list_knowledge_documents` 或 `retrieve_knowledge`。
  - `_retrieve_arguments()` 当前把原始 `query` 传给工具，没有 rewrite 层。
- `app/tools/knowledge_tool.py`
  - `retrieve_knowledge()` 负责构造 `RetrievalQuery`，并经过 `rag_adapter` / `retrieval_service` 返回结构化 artifact。
  - 当前工具签名只有 `query`、`knowledge_base_ids`、`file_name`、`doc_id`、`top_k`，没有 `retrieval_mode` 或 `rewrite_mode` 参数。
- `app/models/knowledge.py`
  - `RetrievalMode` 已有 `dense_only`、`sparse_only`、`hybrid`、`hybrid_rerank`。
  - `RetrievalQuery.retrieval_mode` 默认是 `dense_only`。
- `app/services/hybrid_search_service.py`
  - `HybridSearchService` 会执行 dense + sparse，使用 `RrfFusionService` 做 RRF 排序。
- `app/services/sparse_search_service.py`
  - `SparseSearchService` 提供 BM25 侧路召回。
- `app/services/rerank_service.py`
  - `RerankService` 已有 enabled / disabled / fallback / timeout 语义，但配置默认 `rerank_enabled=false`。
- `app/services/retrieval_service.py`
  - `RetrievalService` 负责 structured retrieval result、citation_text、context_text、parent/full-doc 粒度和 doc-level aggregation。
- `app/services/retrieval_metrics.py`
  - 已有 WeKnora 语义的 `recall_at_k`、`precision_at_k`、`mrr_at_k`、`map_at_k`、`ndcg_at_k`。

### 2.2 关键差距

| 差距 | 当前状态 | 影响 |
|---|---|---|
| 主 RAG 工具默认 dense-only | `retrieve_knowledge()` 不传 `retrieval_mode`，模型默认 `dense_only` | 已有 hybrid 能力没有稳定进入主知识问答路径 |
| query rewrite 缺失 | 只有 intent / scope routing | 中文同义词、企业术语、中英文混合问题可能召回不足 |
| multi-query 缺失 | 没有多表达候选和跨 query 融合 | 用户问题表达窄时，召回覆盖不足 |
| rerank 未上线 | rerank 边界已有，默认关闭 | 无法确认 rerank 是否提升排序，不能直接打开 |
| 生成闭环不完整 | deterministic orchestrator 直接返回 tool context，Agent fallback 才由 LLM 生成 | 企业 RAG 问答缺稳定的 prompt / answer / citation 校验链路 |
| 生成质量评估不足 | 检索评估较多，faithfulness 被记录为后续独立项 | 无法证明回答准确性、全面性和引用支撑 |
| 自修正缺失 | citation verifier 有，但无 bounded retry / regenerate 策略 | no-hit、引用失败、低置信回答不能自动修复 |

## 3. 目标和非目标

### 3.1 目标

本方案要把 RAG 从“可检索、有证据”优化成“主链路可解释、可评估、可逐步上线”的系统：

- 主链路默认检索策略可配置，优先让 `hybrid` 成为知识问答的可评估主候选。
- 在权限 scope 已锁定的前提下做 query rewrite 和 multi-query，不扩大用户可见范围。
- 让 RRF、rerank、doc-level aggregation 和 context granularity 都有清晰开关、诊断和 eval。
- 让知识问答具备稳定的 prompt 拼装、LLM 生成、引用要求和 citation verifier。
- 建立检索层 + 生成层的统一质量评估，覆盖召回、排序、引用、faithfulness、延迟和成本。
- 只允许有限自修正，且不能改变权限 scope、不能越过数据库/AIOps/人工审核边界。

### 3.2 非目标

第一轮优化不做：

- 不重写文档 ingestion / parser / chunk artifact 合同。
- 不把 RAG 和数据库、AIOps 路由合并。
- 不引入新的全局 Repository 或大规模 service 重构。
- 不默认打开外部 rerank 模型。
- 不在没有 baseline eval 的情况下直接把 rewrite / multi-query / rerank 设为线上默认。
- 不用 query rewrite 改变用户意图或扩大 `kb_id`、`doc_id`、`file_name` scope。
- 不把 `retrieval_mode`、`rewrite_mode`、`multi_query_mode` 暴露成模型可随意选择的工具参数；第一版只通过配置、preset 或企业编排层策略控制。
- 不扩大旧 `RagAgentService` / `retrieve_knowledge` 直接绑定工具的 legacy 绕行范围；涉及工具可见性和执行治理时，必须按 `ToolGateway` 接入规则另开收敛任务。

### 3.3 架构一致性约束

本方案必须服从 `docs/项目完整架构.md` 的长期架构基线。RAG 优化只加深 RAG Domain Module，不重新定义企业治理外层。

外层请求路径必须保持：

```text
FastAPI route
-> CurrentUser / RequestContext
-> ChatAdapter / RagAdapter
-> RequestGateway
-> RAG Domain Module
```

RAG 内部必须保持：

```text
RagAdapter.retrieve(context, query)
-> DocumentAccessService / PermissionService
-> RetrievalService.retrieve(query, allowed_document_ids)
-> SourceRef / ChunkEvidence / CitationVerifier
-> Audit / diagnostics / eval
```

因此后续实现要遵守：

- query rewrite / multi-query 只能发生在 `QueryIntentRouter` 已经判定为 RAG 检索类 intent 且 scope 已锁定之后。
- rewrite、multi-query、rerank、answer generation 都不能绕过 `RagAdapter.retrieve(context, query)` 的可见文档过滤。
- `RetrievalService` 继续是召回、证据组装、`context_text` 和 citation contract 的主接口；不要在新模块里重新拼接 `source_ref` 或伪造 citation。
- 新增 trace 字段必须进入现有 diagnostics / audit / eval 路径，不能形成第二套观测格式。
- 如果后续要让 Agent 直接感知 RAG 优化能力，应通过 `ToolGateway` / ToolProvider Adapter 收敛，不应继续扩大直接 tool list 绑定。

## 4. 目标链路

下面链路只描述 RAG Domain Module 内部的优化顺序，不省略外层的 `RequestGateway`、`RagAdapter`、权限过滤和 audit 要求。目标链路不是一次性全开，而是所有阶段最终要对齐到下面这条内部链路：

```text
用户问题
-> QueryIntentRouter
   判断 intent / action / handoff
   锁定 selected_kb_ids / selected_doc_ids / file_name
-> QueryOptimizationPlan
   protected terms
   query rewrite
   multi-query candidates
   retrieval mode policy
-> 多路召回
   dense vector top-N
   BM25 sparse top-N
   optional multi-query recall
-> RRF 融合排序
-> optional rerank
-> optional doc-level aggregation / context granularity
-> Prompt 拼装
   context_text
   source_ref / chunk_id
   answer rules
-> LLM 生成
-> CitationVerifier / answer quality checks
-> bounded self-correction if needed
-> 最终答案 + citations + diagnostics
```

## 5. 分阶段实施计划

### R0：当前主链路基线确认

目的：先把“现在到底怎么跑”固定下来，避免后续优化没有对照组。

要做：

1. 确认 `/api/chat`、`/api/chat_stream`、`retrieve_knowledge`、`/api/knowledge-search` 分别使用什么 retrieval mode。
2. 固化一组小型 RAG eval 问题，覆盖：
   - 流程与数字化部资料。
   - 工艺部资料。
   - 文件限定检索。
   - 无权限 / 无索引 / 无结果。
   - 中英文混合术语。
3. 记录 baseline：
   - `retrieval_mode`
   - `result_count`
   - `doc_recall@k`
   - `citation_correctness`
   - `wrong_scope`
   - `no_retrieval_hit`
   - latency p50 / p95
4. 如果资料导入仍未完成，先把 eval case 标成 `data_not_indexed` / `not_ready`，不要误判为检索策略失败。

验收：

- 能用固定命令复跑 baseline。
- 每个失败样本能区分是 `data_not_indexed`、`permission_filtered`、`retrieval_no_hit`、`answer_wrong` 还是 citation 问题。
- 不修改线上行为。

### R1：主知识问答检索模式策略

目的：让已有 hybrid 能力进入主链路评估，而不是只停留在实验和独立搜索 API。

要做：

1. 新增配置项，例如：

```text
rag_default_retrieval_mode = dense_only | hybrid | hybrid_rerank
```

2. `retrieve_knowledge()` 构造 `RetrievalQuery` 时读取默认配置，或者允许 Orchestrator 显式传入 retrieval mode。
3. 先用 `hybrid` 做 shadow 或 eval，不直接全量替换。
4. diagnostics 中记录：
   - `retrieval_mode`
   - `dense_hit_count`
   - `sparse_hit_count`
   - `hybrid_result_count`
   - `fusion_score`
   - dense / sparse rank metadata
5. 如果 `hybrid` 相比 `dense_only` 不退化，再考虑把知识问答默认改为 `hybrid`。

验收：

- `dense_only` 和 `hybrid` 能在同一 evalset 上对比。
- `hybrid` 不降低 `citation_correctness` 和 `wrong_scope`。
- `hybrid` 对 `no_retrieval_hit` 或目标文档排名有明确收益，才允许设为默认。

### R2：Query Rewrite 模块

目的：在权限 scope 已锁定的情况下，把用户问题改写成更适合召回的 query。

推荐模块：

```text
app/enterprise/rag/query_rewrite.py
```

推荐数据结构：

```python
@dataclass(frozen=True)
class RewriteCandidate:
    query: str
    strategy: str
    reason: str
    protected_terms_used: list[str]
    risk_flags: list[str]


@dataclass(frozen=True)
class RewritePlan:
    original_query: str
    active_query: str
    candidates: list[RewriteCandidate]
    protected_terms: list[str]
    protected_constraints: dict[str, list[str]]
    mode: str
    scope_locked: bool
    no_rewrite_reason: str
    rewrite_trace: dict[str, Any]
```

触发条件：

```text
decision.knowledge_action in {"retrieve", "read"}
decision.intent in {"knowledge_qa", "document_read"}
decision.handoff is None
```

必须跳过：

- `document_list`
- `database`
- `human_review`
- `permission_request`
- `plain_chat`
- 已锁定具体 `doc_id` 或 `file_name` 且 query 很短的场景

保护词来源：

| 来源 | 示例 | 规则 |
|---|---|---|
| 文件名 | `data_sync_service_cpu_db_runbook.md` | 原样保护 |
| doc_id | `doc_xxx` | scope 保护，不进入扩展 |
| kb_id | `process_digital_dept` | 部门语义方向保护 |
| 告警名 | `KubeDeploymentReplicasMismatch`、`CPUHigh` | 原样保护 |
| 技术词 | `Prometheus`、`Alertmanager`、`Kubernetes` | 可补中文解释，不能替换 |
| 英文缩写 | `PHM`、`LOTO`、`API`、`MCP` | 原样保护 |
| 编号 | 工单号、版本号、字段名 | 原样保护 |
| 引号内文本 | `"..."`、`“...”` | 原样保护 |

规则示例：

| 场景 | 原始表达 | 可补充检索表达 | 适用 scope | 风险 |
|---|---|---|---|---|
| 线上故障 | 线上故障 | 线上系统故障、生产故障、故障处理流程 | 流程与数字化部 / auto | 低 |
| 智能运维 | 智能运维 | AIOps、告警、监控、自动化运维 | 流程与数字化部 / auto | 低 |
| Pod 重启 | Pod 一直重启 | CrashLoopBackOff、容器重启、Kubernetes Pod 重启 | 流程与数字化部 / auto | 中 |
| 数据库慢 | 数据库慢 | 慢查询、DBSlowQuery、SQL 执行慢 | 流程与数字化部 / auto | 中 |
| 工艺流程 | 工艺流程 | 作业工艺、工艺规程、工艺文件 | 工艺部 / auto | 低 |
| 设备检修 | 设备检修 | 设备维护、检维修、点检 | 工艺部 / auto | 低 |
| 安全隔离 | 安全隔离 | LOTO、锁定挂牌、能源隔离 | 工艺部 / auto | 低 |
| 压力系统异常 | 压力系统异常 | 压力异常、设备压力、工艺参数异常 | 工艺部 / auto | 中 |

阶段：

1. `off`：不生成 rewrite。
2. `shadow`：生成 `RewritePlan`，真实检索仍使用原 query。
3. `rules_active`：只让低风险规则进入 `active_query`。
4. `llm_structured_shadow`：后续再考虑，不作为第一版目标。

验收：

- 每次 retrieve/read 请求都能产生或明确跳过 `rewrite_trace`。
- shadow 不改变真实检索结果。
- 保护词丢失直接失败。
- `wrong_scope` 不增加。

### R3：Multi-Query 多表达召回

目的：解决用户问题表达过窄、同义词覆盖不足、企业术语混合导致的召回问题。

要做：

1. 复用 `RewritePlan.candidates` 作为 multi-query 候选来源。
2. 第一版只允许规则生成的候选进入 multi-query shadow。
3. 每个候选 query 分别执行相同 retrieval mode。
4. 对不同 query 的召回结果做去重和 RRF 融合：

```text
(original_query dense/sparse hits)
+ (candidate_query_1 dense/sparse hits)
+ (candidate_query_2 dense/sparse hits)
-> RRF by chunk_id
-> top_k
```

5. metadata 记录：
   - `query_variant`
   - `query_variant_rank`
   - `query_variant_strategy`
   - `fusion_score`
   - `matched_query_count`

上线门槛：

- multi-query 只能在 scope locked 后运行。
- multi-query 不允许扩大 `knowledge_base_ids`、`document_ids`、`file_name`。
- 候选 query 数要有限制，例如最多 3 条，防止延迟和成本膨胀。

验收：

- 对同一 evalset 比较 original-only 与 multi-query。
- `no_retrieval_hit` 或目标文档排名提升。
- `wrong_scope`、`citation_correctness` 不退化。
- latency p95 在可接受范围。

### R4：Rerank Shadow 与上线门槛

目的：让 rerank 从“有代码边界”变成“可证明是否值得上线”。

当前状态：

- `RerankService` 已存在。
- 默认 `rerank_enabled=false`。
- 当前 scorer 是本地 lexical baseline，不是外部 cross-encoder 或训练模型。

要做：

1. 新增 rerank shadow 评估，不改变最终排序，只记录 rerank 后排序。
2. 对比：
   - hybrid
   - hybrid_rerank
   - multi-query hybrid
   - multi-query hybrid_rerank
3. 观察 rerank 是否提升：
   - `MRR@k`
   - `precision@k`
   - 目标 chunk/doc 排名
   - citation correctness
4. 如果本地 lexical rerank 不稳定，不直接上线外部模型，先定位失败样本类型。

验收：

- rerank shadow 有独立报告。
- rerank 不改变 citation identity，只改变排序。
- 只有排序收益稳定且延迟可接受时，才允许打开 `hybrid_rerank` 默认。

### R5：Prompt 拼装与 LLM 答案生成

目的：把企业知识问答从“返回检索上下文”升级为稳定的“基于证据生成答案”。

当前问题：

- deterministic orchestrator 的 `AnswerGenerator` 对 `knowledge_qa` / `document_read` 基本返回 tool result 字符串。
- Agent fallback 路径可以由 LLM 调工具生成，但不等于企业编排路径有稳定的 RAG answer pipeline。

要做：

1. 新增或加深 `AnswerGenerator` 的 RAG 生成路径。
2. 输入必须是结构化 `RetrievalResponse`，不是纯字符串。
3. Prompt 必须包含：
   - 用户问题。
   - `context_text`。
   - 每条资料的 `source_ref` / `chunk_id` / `citation_text`。
   - 禁止编造规则。
   - 无资料时必须说明没有找到相关信息。
4. 输出要求：
   - 答案主体。
   - 引用列表。
   - 每个关键结论尽量带 `[chunk: ...]` 或结构化 citation。
5. 先用配置开关启用：

```text
rag_answer_generation_mode = context_only | llm_shadow | llm_active
```

验收：

- `context_only` 保持旧行为。
- `llm_shadow` 不影响线上答案，只记录候选答案和 citation coverage。
- `llm_active` 必须通过 citation verifier 和质量 eval 后才能启用。

### R6：检索层 + 生成层评估

目的：不再只凭“看起来回答更好”判断 RAG 优化是否成功。

检索层指标：

- `recall@k`
- `precision@k`
- `MRR@k`
- `NDCG@k`
- `doc_recall@k`
- `citation_correctness`
- `wrong_scope`
- `no_retrieval_hit`
- `latency_ms`

生成层指标：

- `answer_relevance`：回答是否针对用户问题。
- `faithfulness`：回答内容是否能被引用资料支撑。
- `completeness`：是否覆盖问题关键点。
- `citation_coverage`：关键结论是否带引用。
- `unsupported_claim_count`：无引用支撑的断言数量。
- `empty_answer_rate`：有资料却没有回答的比例。
- `cost_tokens`：LLM 生成或 rewrite 成本。

要做：

1. 在 `evals/knowledge_base` 或 `evals/rag_retrieval` 下增加统一报告。
2. 把检索结果、生成答案、引用、诊断字段写入 JSON 和 Markdown。
3. 对 `data_not_indexed`、`permission_filtered`、`retrieval_no_hit`、`answer_wrong` 分开统计。
4. 先用确定性规则和人工 spot-check，小样本通过后再考虑 RAGAS / TruLens / Phoenix 这类外部评估工具。

验收：

- 每个优化阶段都有 before / after 报告。
- 不能只报平均分，必须列出失败样本和失败类别。
- 生成层不通过时，不能把 retrieval 优化标成整体成功。

### R7：有限自修正

目的：对少数明确失败场景做 bounded retry，不做无限 Agent 循环。

允许触发：

- 无结果，但当前 scope 内有 indexed 文档。
- citation verifier 失败。
- LLM 输出没有引用。
- answer quality check 发现 unsupported claims。

不允许触发：

- 权限不足。
- 数据库 / human_review / permission_request intent。
- 文档未索引或 parser/index failed。
- 用户明确锁定 `file_name` / `doc_id` 且该文档无结果时，不得扩大范围。

策略：

1. 最多一次 retry。
2. retry 只能改变 query 表达或 answer prompt，不能改变权限 scope。
3. retry trace 必须进入 diagnostics。
4. retry 后仍失败，要返回明确原因，不继续重试。

验收：

- 自修正不能扩大 scope。
- retry 次数有硬上限。
- 每次 retry 都有 `retry_reason`、`changed_fields`、`final_status`。

## 6. 阶段依赖与开发落点

下面这张表把 R0-R7 改成更接近开发清单的口径。这里列的是候选落点，真正开发时仍要先读对应文件和测试，按最小改动收窄范围。

| 阶段 | 前置条件 | 候选落点 | 测试 / 评估入口 | 最低完成产物 |
|---|---|---|---|---|
| R0 baseline | 无；但要记录当前 indexed 文档不足时的阻塞原因 | `evals/knowledge_base/run_department_rag_eval.py`、`evals/knowledge_base/evalsets/*.jsonl`、`evals/knowledge_base/reports/` | `tests/test_knowledge_base_evalsets.py`、固定 eval 命令 | `rag_baseline_<timestamp>.json/md`，包含 retrieval mode、失败类别、source_ref 可解析性、p50/p95 latency；如果资料不足，R0 也要以 `data_not_indexed` / `not_ready` 状态收口 |
| R1 retrieval mode policy | R0 可复跑；至少能区分 dense-only 与 hybrid 的同一 evalset | `app/config.py`、`app/enterprise/adapters/rag_adapter.py`、`app/enterprise/rag/retrieval_orchestrator.py`、`app/tools/knowledge_tool.py`、`app/models/knowledge.py`、`app/services/retrieval_service.py`、`app/services/hybrid_search_service.py` | `tests/test_retrieval_service.py`、`tests/test_p3_hybrid_retrieval.py`、`tests/test_knowledge_search_diagnostics.py`、RAG eval | dense-only vs hybrid 对比报告；`citation_correctness` 和 `wrong_scope` 不退化；不把 retrieval mode 做成模型可随意传入的公开工具参数 |
| R2 query rewrite shadow | R0/R1 完成；scope lock 和 protected terms 规则明确 | `app/enterprise/rag/query_rewrite.py`、`app/enterprise/rag/retrieval_orchestrator.py`、`app/enterprise/adapters/rag_adapter.py` diagnostics | 新增 `tests/test_query_rewrite.py`、扩展 `tests/test_knowledge_retrieval_orchestrator.py` | shadow trace 可见；真实检索仍使用原 query；protected terms 丢失即失败；不绕过 `RagAdapter` 的可见文档过滤 |
| R3 multi-query shadow | R2 shadow 有候选 query；R1 hybrid eval 不退化 | `app/enterprise/rag/query_rewrite.py`、`app/enterprise/rag/retrieval_orchestrator.py`、可选 `app/enterprise/rag/multi_query.py`；`app/services/hybrid_search_service.py` 只作为单 query dense/sparse/RRF 能力复用 | 新增 `tests/test_multi_query_retrieval.py`、扩展 RAG eval | original-only vs multi-query 报告；候选数量有上限；不扩大 `kb_id` / `doc_id` / `file_name` scope |
| R4 rerank shadow | R1/R3 有稳定候选集；baseline latency 已记录 | `app/services/rerank_service.py`、`app/services/hybrid_search_service.py`、`app/services/retrieval_service.py`、`app/config.py` | `tests/test_p3_rerank_service.py`、`evals/rag_retrieval/run_retrieval_eval.py` | rerank shadow 独立报告；只比较排序，不改变 citation identity；p95 latency 不越过门槛；证据字段仍由 retrieval evidence 路径统一生成 |
| R5 LLM answer shadow | R0-R4 检索链路稳定且不退化；citation verifier 可用 | `app/enterprise/rag/answer_generator.py`、`app/enterprise/rag/retrieval_orchestrator.py`、`app/enterprise/adapters/rag_adapter.py`、`app/enterprise/verifiers/*` | `tests/test_knowledge_retrieval_orchestrator.py`、`evals/rag_retrieval/run_p5_llm_eval.py` 或生成层 eval | `context_only` 保持旧行为；`llm_shadow` 只记录候选答案、citation coverage、unsupported claims；`llm_active` 必须经过 `VerificationService` / `CitationVerifier` |
| R6 evaluation | R0 已有报告；每个阶段都能输出 diagnostics | `evals/knowledge_base/run_department_rag_eval.py`、`evals/rag_retrieval/*`、`app/services/retrieval_metrics.py` | `tests/test_retrieval_metrics.py`、`tests/test_knowledge_base_evalsets.py`、阶段 eval | before/after JSON + Markdown；失败样本按 `data_not_indexed`、`permission_filtered`、`retrieval_no_hit`、`answer_wrong` 分桶 |
| R7 bounded self-correction | R5 shadow 暴露出可修复的引用/生成失败；失败原因能被分类 | `app/enterprise/rag/answer_generator.py`、`app/enterprise/rag/retrieval_orchestrator.py`、可能新增 self-correction helper | 扩展 `tests/test_knowledge_retrieval_orchestrator.py` 和生成层 eval | 最多一次 retry；不能改变权限 scope；trace 记录 `retry_reason`、`changed_fields`、`final_status` |

R5 和 R7 不进入第一优先级实现。它们只有在 R0-R4 证明检索主链路不退化后，才作为 P2 开启；否则会把“资料没索引”“检索没命中”“排序不好”和“LLM 生成错误”混在一起，导致失败不可诊断。

## 7. 推荐执行顺序

按价值和风险排序，建议这样做：

1. **R0 baseline**
   - 先确认当前默认 dense-only、已有 hybrid API、数据导入状态和 eval 失败类别。
   - 验证：baseline report 可复跑。
2. **R1 retrieval mode policy**
   - 让主知识问答可以配置使用 `hybrid`，先 eval/shadow，再决定是否默认。
   - 验证：dense vs hybrid 对比报告。
3. **R2 query rewrite shadow**
   - 接入 `QueryRewriteModule`，只记录 trace，不改变答案。
   - 验证：protected terms、skip rules、scope lock 单测。
4. **R3 multi-query shadow**
   - 复用 rewrite candidates 做多表达召回，并用 RRF 合并。
   - 验证：original-only vs multi-query 对比。
5. **R4 rerank shadow**
   - 对 hybrid / multi-query 结果做 rerank 对比。
   - 验证：排序指标和延迟报告。
6. **R5 LLM answer shadow（P2 gate）**
   - 企业编排路径生成候选答案，但不直接替换线上答案。
   - 只有 R0-R4 的检索报告稳定后才启动。
   - 验证：citation coverage、faithfulness、unsupported claims。
7. **R6/R7 active gates（R7 为 P2 gate）**
   - 只有在 eval 不退化时，逐项打开 `hybrid`、`rules_active`、`multi_query_active`、`llm_active` 和 bounded self-correction。

## 8. 配置建议

建议所有优化都通过配置显式控制：

```text
rag_default_retrieval_mode = dense_only | hybrid | hybrid_rerank
rag_query_rewrite_mode = off | shadow | rules_active
rag_multi_query_mode = off | shadow | rules_active
rag_multi_query_max_candidates = 3
rag_rerank_mode = off | shadow | active
rag_answer_generation_mode = context_only | llm_shadow | llm_active
rag_self_correction_mode = off | citation_retry | answer_retry
rag_self_correction_max_retries = 1
```

默认值建议：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rag_multi_query_mode = off
rag_rerank_mode = off
rag_answer_generation_mode = context_only
rag_self_correction_mode = off
```

等 R0/R1 eval 证明 `hybrid` 不退化后，再考虑把知识问答默认改成：

```text
rag_default_retrieval_mode = hybrid
```

为避免 6 个以上独立开关形成组合爆炸，第一版不支持任意自由组合，只支持经过评估的 preset：

| preset | retrieval | rewrite | multi-query | rerank | answer | self-correction | 用途 |
|---|---|---|---|---|---|---|---|
| `baseline` | `dense_only` | `off` | `off` | `off` | `context_only` | `off` | 记录当前主链路对照组 |
| `retrieval_shadow` | `hybrid` | `off` | `off` | `off` | `context_only` | `off` | 单独验证 hybrid 是否不退化 |
| `rewrite_shadow` | `hybrid` | `shadow` | `off` | `off` | `context_only` | `off` | 验证 rewrite trace、保护词和跳过规则 |
| `recall_shadow` | `hybrid` | `shadow` | `shadow` | `shadow` | `context_only` | `off` | 验证 rewrite + multi-query + rerank 的召回/排序收益 |
| `optimized_recall` | `hybrid` | `rules_active` | `rules_active` | `off` | `context_only` | `off` | 检索层 active 候选；rerank 是否 active 需单独批准 |
| `answer_shadow` | `hybrid` | `rules_active` | `rules_active` | `off` | `llm_shadow` | `off` | R5 候选答案评估 |

除了 preset 外，允许保留高级单项开关用于本地诊断，但项目文档和测试只承诺覆盖上表中的组合。

## 9. Trace 与诊断字段

优化后的 diagnostics 至少要包含：

```json
{
  "rag_optimization_trace": {
    "retrieval_mode": "hybrid",
    "query_rewrite_mode": "shadow",
    "multi_query_mode": "off",
    "rerank_mode": "off",
    "answer_generation_mode": "context_only",
    "original_query": "Pod 一直重启怎么办",
    "active_query": "Pod 一直重启怎么办",
    "candidate_queries": [
      {
        "query": "Pod 一直重启 CrashLoopBackOff 容器重启 Kubernetes Pod 重启",
        "strategy": "process_digital_term_expansion",
        "reason": "命中 Pod 重启术语扩展",
        "protected_terms_used": ["Pod"],
        "risk_flags": []
      }
    ],
    "protected_terms": ["Pod"],
    "protected_constraints": {
      "knowledge_base_ids": ["process_digital_dept"],
      "document_ids": [],
      "file_name": []
    },
    "scope_locked": true,
    "dense_hit_count": 12,
    "sparse_hit_count": 6,
    "hybrid_result_count": 3,
    "rerank_status": "disabled",
    "self_correction": {
      "triggered": false,
      "reason": "",
      "retry_count": 0
    },
    "trace_policy": {
      "full_trace_sampled": true,
      "sample_rate": 0.1
    }
  }
}
```

Trace 记录要有预算：

- active 路径默认只记录最小字段：mode、original query、active query、scope、result count、failure category。
- shadow 阶段可以记录完整 trace，但建议默认 10% 采样；失败样本和 eval 运行可以强制全量记录。
- 每启用一层 shadow 或 active，都要比较 p50/p95。第一版门槛建议是 p95 不超过 R0 baseline 的 1.5 倍；超过时该层只能保留在 shadow 或本地诊断。
- 规则数量要有维护上限。第一版 rules 建议不超过 30 条；超过后需要启动 v2 规则治理或 LLM structured rewrite 评估，而不是继续堆硬编码。

## 10. 最小测试用例

### 10.1 Query rewrite / scope lock

| 用户问题 | scope | 期望 |
|---|---|---|
| 中车长客数字化转型 | auto | 允许补数字化建设、流程数字化 |
| 线上故障怎么处理 | process_digital_dept | 允许补线上系统故障、故障处理流程 |
| Pod 一直重启怎么办 | process_digital_dept | 保留 Pod，允许补 CrashLoopBackOff |
| KubeDeploymentReplicasMismatch 怎么处理 | process_digital_dept | 告警名原样保留 |
| 数据库慢怎么办 | process_digital_dept | 只有 RAG intent 时才允许补慢查询、DBSlowQuery |
| 工艺流程有哪些要求 | craft_dept | 允许补作业工艺、工艺规程 |
| 设备检修怎么做 | craft_dept | 允许补设备维护、检维修、点检 |
| 压力系统异常怎么办 | craft_dept | 禁止补 Prometheus / Alertmanager |
| 申请工艺部知识库权限 | any | 不 rewrite，进入 permission_request |
| 创建一张数据库表 | any | 不 rewrite，进入 database / human_review |
| 相关文件有什么 | any | 不 rewrite，进入 document_list |
| 总结 data_sync_service_cpu_db_runbook.md | any | 保护文件名，优先文件限定检索 |

### 10.2 Retrieval mode

| 场景 | dense-only | hybrid | 期望 |
|---|---|---|---|
| 精确技术词 | 应命中 | 应命中 | hybrid 不退化 |
| 中文同义词 | 可能漏检 | 应提升 | hybrid 或 rewrite 有收益 |
| 英文告警名 | 应保留 | 应保留 | 不丢 protected term |
| 错误部门 scope | 不应跨 scope | 不应跨 scope | wrong_scope 不增加 |

### 10.3 Answer generation

| 场景 | 期望 |
|---|---|
| 检索有结果 | 答案必须基于资料，至少有引用 |
| 检索无结果 | 明确说明未找到相关信息 |
| 引用字段不完整 | verifier 失败，不生成伪 citation |
| LLM 生成无引用 | 触发一次 correction 或返回失败原因 |

## 11. 风险与防线

| 风险 | 表现 | 防线 |
|---|---|---|
| 权限扩大 | rewrite/multi-query 查到用户不该看的文档 | 不改 scope，仍走 `DocumentAccessService` / `rag_adapter` |
| 绕过企业治理外层 | 为了优化 RAG 直接从 route 或 Agent 调新模块 | 保持 `CurrentUser / RequestContext -> Adapter -> RequestGateway -> RAG Domain` 路径 |
| 绕过 ToolGateway | 把新 RAG 工具或模式直接塞进 Agent tool list | 新工具能力按 ToolProvider Adapter / ToolGateway 规则接入；legacy 路径不继续扩大 |
| 部门串线 | 工艺问题召回 AIOps 文档 | 部门规则隔离，`wrong_scope` 作为硬指标 |
| 保护词丢失 | 告警名、文件名被替换 | protected terms 单测，丢失即失败 |
| 召回变多但答案变差 | 混入无关文档 | 同时看 precision、citation、faithfulness |
| 证据链分裂 | 新模块各自拼 `source_ref` / citation | 统一复用 `RetrievalService` / SourceRef / ChunkEvidence / CitationVerifier 证据路径 |
| rerank 降级 | 相关文档被排后 | rerank shadow 先行，不默认打开 |
| LLM 编造 | 答案超出资料 | citation verifier + unsupported claim check |
| retry 失控 | 多轮自修正扩大成本 | 最多一次 retry，trace 必填 |
| 数据未导入误判 | 前后都搜不到 | `data_not_indexed` 和 `not_ready` 单独统计 |
| 配置组合爆炸 | 多开关叠加后无法覆盖测试 | 第一版只支持 preset，单项开关仅用于本地诊断 |
| shadow 延迟累积 | 用户请求 p95 明显升高 | 每层都记录 latency，对照 baseline 的 1.5 倍门槛 |
| 自修正掩盖 scope 问题 | retry 反复改 query 但仍查错范围 | `wrong_scope` / `permission_filtered` 不允许进入 retry |

## 12. 暂不做的事

第一轮不做：

- 直接默认启用 LLM rewrite。
- 直接默认启用外部 rerank 模型。
- 直接把所有知识问答改成 LLM active answer。
- 无限自修正。
- 修改 parser artifact 合同。
- 修改权限模型。
- 让 rewrite 或 multi-query 改变 `kb_id` / `doc_id` / `file_name` scope。
- 支持任意配置自由组合。
- 在 R0-R4 未稳定前启动 R5/R7 active。

## 13. 一句话总结

这次 RAG 优化的第一优先级不是“立刻加一个 LLM query rewrite”，而是把当前已有的 dense、BM25、RRF、rerank、citation、eval 能力接成可配置、可观测、可验证的主链路。查询重写是其中一个阶段，必须在权限 scope 锁定、baseline 可复跑、protected terms 可校验之后，再从 shadow 小步进入 active。

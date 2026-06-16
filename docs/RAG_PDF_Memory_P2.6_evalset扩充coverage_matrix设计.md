# RAG/PDF/Memory P2.6 evalset 扩充 coverage matrix 设计

日期：2026-06-09

状态：

```text
status = design_only
formal_evalsets_created = no
retrieval_rerank_eval_rerun = no
default_switch_eligibility = not_eligible_for_default_switch
```

## 1. 目标

P2.6 的目标不是立刻写 50 道题，而是先把“什么样的 50q 才能支持 hybrid / rerank 决策”定义清楚。

本设计输出：

- 50q / 3 evalset 的 coverage matrix。
- 样本候选清单字段。
- corpus support 检查规则。
- 正式 evalset 创建前的拒绝规则。
- 后续四模式 / rerank 复跑门槛。

本设计不做：

- 不创建正式 50q evalset 文件。
- 不重跑 retrieval / rerank eval。
- 不启用 `rag_default_retrieval_mode=hybrid`。
- 不启用 `rerank_enabled=true`。
- 不实现 P2.2 Query Rewrite。
- 不把 `retrieval_mode` 暴露给模型工具参数。

## 2. 当前事实

当前可用基线：

| 资产 | 状态 | 用途 |
|---|---|---|
| `department_rag_18q_current_scope_20260608.jsonl` | 18/18 current-scope baseline | 小样本 shadow baseline |
| `department_rag_permission_isolation_10q.jsonl` | E1 guardrail | 权限隔离回归 |
| `department_rag_scope_lock_10q.jsonl` | E1 guardrail | scope 锁定回归，当前有已知内容类 9/10 |
| `department_rag_citation_accuracy_10q.jsonl` | E1 guardrail | citation/source_ref 回归 |
| `retrieval_4mode_comparison_20260609.json` | ignored report evidence | 18q 四模式 shadow 结果 |
| PDF page/table eval | 1 PDF / 1 sample | `corpus_limited`，不可作为多 PDF 结论 |

当前 indexed corpus：

| KB | doc_id | 文档 | 当前用途 |
|---|---|---|---|
| `process_digital_dept` | `doc_6627ee79-7c85-531a-b545-55cfd5460e90` | `superbiz_oncall_handbook.md` | 运维/on-call 内容召回、citation、scope |
| `process_digital_dept` | `doc_6cc9b0b1-d8b7-58d4-a7a0-6213f7717375` | `2024_人民网聚焦中车长客数字化转型成果.md` | 数字化转型内容召回 |
| `craft_dept` | `doc_27b282ca-97c3-5170-af0a-282f2e9122a1` | `线上故障处理_现场设备工艺版.pdf` | 工艺/PDF/source_ref/table 工具 |

约束：

- 只有 3 个 indexed 文档，不能机械拆出“看起来很大”的 50q。
- pending 环保/合规 PDF 已登记为 `rejected_current_kb`，不能作为当前 retrieval/rerank 收益样本。
- 18q 四模式结果可作为 shadow baseline，不能作为默认切换依据。

## 3. Coverage Matrix

建议先形成 3 个 benefit evalset 草案，加上现有 guardrail 回归。

| 层级 | 草案 evalset | 目标样本量 | 覆盖目标 | 允许来源 | 不能计入收益的样本 |
|---|---|---:|---|---|---|
| Benefit-A | `department_rag_retrieval_content_recall_20q.jsonl` | 20 | 当前 scope 内容召回 | 3 个 indexed 文档 | out_of_scope、corpus_gap、纯权限拒绝 |
| Benefit-B | `department_rag_retrieval_sparse_hybrid_lift_15q.jsonl` | 15 | sparse/hybrid 可能带来提升的词面/缩写/编号/精确术语 | 3 个 indexed 文档 | 目标词不在文档、评分期望错误 |
| Benefit-C | `department_rag_rerank_rank_lift_15q.jsonl` | 15 | 目标文档已召回但排序靠后的 rerank 场景 | 四模式 shadow 候选结果 | 目标文档未召回、只在 synthetic rerank 中成立 |
| Guardrail-D | 现有 E1 三组 + 后续扩展 | 30+ | permission/scope/citation 不退化 | E1 evalsets | 不作为收益证明 |
| PDF-E | PDF page/table/source_ref 扩展 | 视 corpus 而定 | PDF 引用链不退化 | indexed PDF | 当前 blocked by `pdf_eval_corpus_limited` |

## 4. 候选样本字段

候选样本先写入草案清单或设计表，不直接进入正式 evalset。

最小字段：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `candidate_id` | 是 | 草案 ID，例如 `P26-A-001` |
| `target_evalset` | 是 | 目标草案 evalset |
| `query` | 是 | 用户问题 |
| `allowed_kb_ids` | 是 | 权限/scope |
| `scope` | 是 | `scoped` 或 `auto` |
| `expected_doc_ids` | 是 | Benefit 样本必须非空 |
| `expected_answer_keywords` | 是 | 必须能在目标文档或目标 chunk 中解释 |
| `failure_class` | 是 | 见第 5 节 |
| `support_doc_status` | 是 | `indexed` / `not_indexed` / `rejected_current_kb` |
| `support_check_status` | 是 | `supported` / `unsupported` / `needs_review` |
| `source_ref_expectation` | 是 | 是否要求 source_ref 可解析 |
| `exclude_from_benefit_reason` | 否 | 不能计入收益时填写 |
| `notes` | 否 | 设计备注 |

正式 evalset 字段沿用现有 runner：

- `sample_id`
- `query`
- `allowed_kb_ids`
- `expected_doc_ids`
- `expected_answer_keywords`
- `scope`
- `retrieval_mode`
- `top_k`

可增加但需要 runner 支持或忽略安全：

- `failure_class`
- `expected_source_ref_fields`
- `citation_must_resolvable`
- `retrieved_must_not_contain_kb`
- `target_kb_id`

## 5. Failure Class

Benefit 样本必须标注 failure class。

| failure_class | 用途 | 例子 | 可计入收益 |
|---|---|---|---:|
| `content_recall` | 普通内容召回 | “线上故障处理流程是什么” | 是 |
| `lexical_lift` | 关键词/词面命中可能帮助 sparse/hybrid | “Prometheus 告警” | 是 |
| `acronym` | 缩写、英文术语、大小写 | `SRE`、`API`、`Ack` | 是 |
| `identifier` | 编号、表格 ID、Runbook 名 | `t00001`、`Runbook` | 是 |
| `exact_term` | 必须匹配具体术语 | “安全隔离”“压力系统” | 是 |
| `rank_lift` | 目标文档已召回但排序靠后 | rerank 应把强相关 chunk 提前 | 是 |
| `permission_guardrail` | 权限拒绝 | 跨部门读 craft 文档 | 否 |
| `scope_guardrail` | scope 锁定 | 锁定运维库不串工艺库 | 否 |
| `citation_guardrail` | source_ref/citation 回归 | chunk_id 可解析 | 否 |
| `corpus_gap` | 语料不存在 | 未导入环保 PDF | 否 |
| `out_of_scope` | 当前助手范围外 | 环保合规问答 | 否 |
| `eval_expectation_issue` | 评分/题目设计错误 | 要求文档里不存在的关键词 | 否 |

## 6. Corpus Support 检查

正式样本创建前，每个候选必须通过 support check。

检查项：

1. `expected_doc_ids` 必须在 `data/knowledge_ingestion/current_import_state.json` 中存在且 `status=indexed`。
2. `allowed_kb_ids` 必须包含目标文档所属 KB。
3. `expected_answer_keywords` 必须能在目标文档、chunk、artifact 或人工确认的内容摘要中解释。
4. `source_ref_expectation=true` 的样本必须能解析 `kb_id/doc_id/chunk_id/page_start/source_file`。
5. PDF page/table 样本必须能在 artifact 中找到对应 `page` 或 `table_id`。
6. pending / disabled / `rejected_current_kb` 资产只能进入 backlog 或历史审计，不能进入 Benefit-A/B/C。

拒绝规则：

| 条件 | 处理 |
|---|---|
| 目标文档未 indexed | 标记 `corpus_gap`，不进入正式 benefit evalset |
| 题目依赖当前 rejected PDF | 标记 `out_of_scope` 或 backlog |
| 关键词只在非目标文档出现 | 标记 `eval_expectation_issue` |
| 题目只是原 18q 的同义重复 | 合并或拒绝 |
| 只验证权限拒绝 | 放入 guardrail，不计入 retrieval 收益 |

## 7. 草案样本分布

Benefit-A `content_recall_20q`：

| 文档 | 建议数量 | 覆盖 |
|---|---:|---|
| `superbiz_oncall_handbook.md` | 8 | 故障处理、告警、升级、值班、Runbook |
| `2024_人民网聚焦中车长客数字化转型成果.md` | 5 | 数字化、科技赋能、成果、列车 |
| `线上故障处理_现场设备工艺版.pdf` | 7 | 现场设备、工艺、压力系统、安全隔离、PDF source_ref |

Benefit-B `sparse_hybrid_lift_15q`：

| 类型 | 建议数量 | 示例方向 |
|---|---:|---|
| 英文/缩写 | 4 | `SRE`、`API`、`Ack`、`Prometheus` |
| 精确术语 | 4 | `Runbook`、`安全隔离`、`压力系统` |
| 跨中文表达 | 4 | “线上故障” vs “现场工艺异常” |
| 标题/短语匹配 | 3 | 数字化转型标题、科技赋能短语 |

Benefit-C `rerank_rank_lift_15q`：

| 来源 | 建议数量 | 要求 |
|---|---:|---|
| 18q 四模式候选结果 | 5 | 目标 doc 已召回但非 top-1 |
| 新增 content recall 候选 | 5 | dense/hybrid 均召回，但排序不同 |
| sparse/hybrid lift 候选 | 5 | hybrid candidate pool 中有可 rerank 的强弱相关差异 |

Guardrail-D：

- 继续保留现有 E1 三组作为强制回归。
- 后续扩展时优先补：
  - 模糊权限请求。
  - 跨 KB 相似文档。
  - citation 字段缺失。
  - source_ref 指向不可解析 chunk。

PDF-E：

- 当前只记录设计，不扩正式样本。
- 需要新增 indexed PDF 后再扩展。
- 当前唯一成功 PDF 可继续用于 smoke，不可伪装成多 PDF coverage。

## 8. 复跑策略

正式 evalset 创建后，按以下顺序复跑。

第一步：四模式 retrieval comparison。

```bash
uv run python -m evals.knowledge_base.retrieval_mode_comparison_report \
  --evalset evals/knowledge_base/evalsets/department_rag_retrieval_content_recall_20q.jsonl \
  --modes dense_only sparse_only hybrid hybrid_rerank \
  --output-json evals/knowledge_base/reports/retrieval_content_recall_4mode_YYYYMMDD.json \
  --output-md evals/knowledge_base/reports/retrieval_content_recall_4mode_YYYYMMDD.md
```

第二步：对 Benefit-B / Benefit-C 重复四模式复跑。

第三步：如果要评估真实 rerank active shadow，必须使用受控 report 进程临时启用 `rerank_enabled=true`，不得修改 `app/config.py` 默认值。

第四步：复跑 guardrail。

```bash
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_permission_isolation_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_permission_isolation_after_p26_YYYYMMDD.json

uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_scope_lock_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_scope_lock_after_p26_YYYYMMDD.json

uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_citation_accuracy_10q.jsonl \
  --report evals/knowledge_base/reports/department_rag_citation_accuracy_after_p26_YYYYMMDD.json
```

## 9. 通过条件

P2.6 设计通过条件：

- coverage matrix 清楚。
- 候选字段清楚。
- corpus support 检查规则清楚。
- 明确不创建正式 50q。
- 明确 P2.2 Query Rewrite 继续暂缓。

后续正式 50q / 3 evalset 通过条件：

- Benefit 样本总数至少 50，或 3 个 benefit evalset 均完成且结论一致。
- 所有 benefit 样本都有 `failure_class`。
- `wrong_scope_count=0`。
- `citation_incomplete_count=0`。
- `citation_unresolvable_count=0`。
- expected-doc / recall@5 稳定提升，建议提升幅度 > 10%。
- hybrid p95 不超过 dense-only 的 1.3 倍。
- 真实 rerank 增量 p95 < 500ms。
- retrieval default rollback 记录草案已存在。

## 10. 下一步

建议下一步不是写正式 evalset，而是生成草案候选表：

```text
next_step = create_candidate_matrix_draft
output = docs/RAG_PDF_Memory_P2.6_evalset候选样本草案.md
formal_evalsets_created = no
```

草案候选表通过人工 review 后，再进入正式 evalset 创建和复跑阶段。

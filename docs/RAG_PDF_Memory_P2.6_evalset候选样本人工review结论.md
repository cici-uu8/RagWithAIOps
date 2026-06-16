# RAG/PDF/Memory P2.6 evalset 候选样本人工 review 结论

日期：2026-06-09

状态：

```text
status = review_done_and_bc_shadow_probe_done
formal_evalsets_created = partial
created_evalsets = department_rag_retrieval_content_recall_20q.jsonl
deferred_evalsets = sparse_hybrid_lift_15q, rerank_rank_lift_15q
schema_support_check = passed
content_recall_20q_eval_rerun = yes
retrieval_lift_eval_rerun = yes_no_lift
rerank_rank_lift_eval_rerun = yes_no_rank_lift
benefit_b_effective_lift_count = 0
benefit_c_effective_rank_lift_count = 0
default_switch_eligibility = not_eligible_for_default_switch
```

## 1. Review 范围

审查对象：

- `docs/RAG_PDF_Memory_P2.6_evalset候选样本草案.md`
- `docs/RAG_PDF_Memory_P2.6_evalset扩充coverage_matrix设计.md`

核对依据：

- `data/knowledge_ingestion/current_import_state.json`
- `evals/knowledge_base/evalsets/department_rag_18q_current_scope_20260608.jsonl`
- `evals/knowledge_base/reports/retrieval_4mode_comparison_20260609.json`
- 当前 3 个 indexed 文档原文与 PDF artifact
- `evals/knowledge_base/run_department_rag_eval.py` 和 `evals/knowledge_base/retrieval_mode_comparison_report.py` 的字段要求

本文件先记录人工 review 和正式 JSONL 创建决策；当前已补充 2026-06-09 A-20q 复跑与 B/C shadow probe 结论。所有 probe 都不修改 `app/config.py`，不启用运行时默认 hybrid/rerank/rewrite。

## 2. 总体结论

| 类别 | 候选数 | Review 结论 | 是否转正式 JSONL | 理由 |
|---|---:|---|---|---|
| Benefit-A content recall | 20 | 全部通过人工 review | 是 | 目标 doc 均 indexed，关键词有当前语料支撑，适合作为内容召回正式 20q |
| Benefit-B sparse/hybrid lift | 15 | shadow probe 后降级为 observation | 否 | 0/15 证明 dense miss 且 sparse/hybrid recover，不能计入正式 lift |
| Benefit-C rerank rank lift | 15 | shadow probe 后降级为 observation | 否 | 真实 rerank 已在受控进程 applied，但 0/15 证明 expected doc 被提升 |
| Guardrail-D | 5 | 保留为回归设计 | 否 | 不计入 retrieval/rerank 收益，E1 已有三组正式 guardrail |
| PDF-E | 3 | 保留为 PDF 后续设计 | 否 | 当前只有 1 个 indexed PDF，仍是 `corpus_limited` |

正式创建：

- `evals/knowledge_base/evalsets/department_rag_retrieval_content_recall_20q.jsonl`

创建后校验：

- `load_evalset(...)` 可加载该 JSONL。
- 样本数为 20，`sample_id` 为 `P26-A-001` 到 `P26-A-020` 且唯一。
- 目标文档均在 `data/knowledge_ingestion/current_import_state.json` 中为 `indexed`。
- `expected_answer_keywords` 在目标文档原文或 PDF artifact 中逐字可解释，`missing_keyword_count=0`。

暂不创建：

- `department_rag_retrieval_sparse_hybrid_lift_15q.jsonl`
- `department_rag_rerank_rank_lift_15q.jsonl`

## 3. Benefit-A 判定

Benefit-A 20 个候选全部接受，转为正式 evalset。

接受理由：

- `expected_doc_ids` 均在 current import state 中为 `indexed`。
- `allowed_kb_ids` 与目标文档所属 KB 一致。
- `expected_answer_keywords` 能在目标文档原文、chunks 或 PDF artifact 中解释。
- 不依赖 pending / disabled / `rejected_current_kb` 资产。
- 样本目标是 content recall，不声称证明 sparse/hybrid/rerank 收益。

保留边界：

- 20q 仍只覆盖 3 个 indexed 文档。
- 通过该 evalset 只能证明当前小规模 KB 的内容召回，不支持默认检索模式切换。
- 后续复跑如果出现 `answer_wrong`，应优先检查关键词是否过严或 chunk 命中是否偏移，而不是立即调 retrieval 默认值。

## 4. Benefit-B 判定

Benefit-B 15 个候选在人工 review 后保持候选态；2026-06-09 已完成四模式 shadow probe，结论是不转正式收益 evalset。

原因：

- 15/15 当前都是 `needs_shadow_probe`。
- 它们的价值在于验证 sparse/hybrid 是否带来词面、缩写、编号、精确术语提升；这必须由四模式 probe 证明，不能靠题面判断。
- 2026-06-09 probe 结果为 `effective_lift_count=0`，15/15 verdict 均为 `no_lift`。
- dense-only 对这批候选没有出现“漏掉目标文档，而 sparse/hybrid 捞回”的有效收益样本。

需要注意的候选：

| candidate_id | Review 结论 | 原因 |
|---|---|---|
| P26-B-014 | 建议移入 PDF observation 或单独标记 | `t00001` 更像 PDF table smoke / identifier 回归，不宜作为 retrieval lift 主证据 |
| P26-B-015 | 需要重审 failure_class | 多 KB 近义语境对照更像 cross-domain semantic contrast，不是单纯 lexical_lift |

后续动作：

1. 不创建 `department_rag_retrieval_sparse_hybrid_lift_15q.jsonl`。
2. 按草案第 12 节降级为 `lexical_lift_observation_report`。
3. 若未来新增语料或候选，再重新跑 probe；只有 dense miss / sparse or hybrid hit 的有效样本达到门槛，才转正式 Benefit-B。

## 5. Benefit-C 判定

Benefit-C 15 个候选在人工 review 后保持候选态；2026-06-09 已完成受控真实 rerank shadow probe，结论是不转正式 rank_lift evalset。

主要原因：

- P2.3 的 `hybrid_rerank` 全部为 `disabled`，不能证明真实 rerank active 的排序收益。
- P2.4 只有 synthetic rerank readiness，不是真实 evalset 质量证据。
- 2026-06-09 probe 在进程内临时设置 `rerank_service.enabled=True` 后，`hybrid_rerank` 真实 applied，但 `effective_rank_lift_count=0`。
- 15 个候选里 14 个为 `no_rank_lift`，1 个为 `not_true_rerank`；没有出现 expected doc 被真实 rerank 从后排顶上来的样本。
- 当前 C 组有若干候选实际不属于纯 rank_lift。

需要重分类或重审的候选：

| candidate_id | 当前问题 | 建议 |
|---|---|---|
| P26-C-001 | 目标文档不含关键词 `线上故障`，更像 sparse/hybrid lexical lift seed | 移入 Benefit-B probe 或调整关键词 |
| P26-C-006 | `source_ref` 是系统字段，不是目标文档内容 | 移入 citation/source_ref guardrail |
| P26-C-007 | `chunk_id` / `source_ref` 是系统字段，不是目标文档内容 | 移入 citation/source_ref guardrail |
| P26-C-008 | PDF 处理失败更像 PDF/data gate 或 source_ref 回归 | 移入 PDF/guardrail observation |
| P26-C-009 到 P26-C-015 | 内容有支撑，但没有真实 rank-lift 证据 | 先做 probe，不能直接转正式 |

后续动作：

1. 不创建 `department_rag_rerank_rank_lift_15q.jsonl`。
2. 按草案第 12 节降级为 `rank_lift_observation_report`。
3. 未来若要重启 C 组，必须先重新定义 rank_lift 入选标准：目标 chunk 已在 hybrid candidate pool 中被召回，但非 top-1 或排序明显落后，并且真实 rerank 能稳定提升。

## 6. Guardrail-D / PDF-E 判定

Guardrail-D：

- 保留为回归扩展设计。
- 不创建收益 evalset。
- 与现有 E1 permission/scope/citation 三组 evalset 配合使用。

PDF-E：

- 保留为 PDF 后续设计。
- 当前不扩正式 PDF eval。
- 原因仍是 `corpus_limited`：只有 1 个 indexed PDF、1 页、1 张表。

## 7. 转正式 JSONL 决策

本轮决策：

```text
create_formal_jsonl = partial
create_benefit_a_content_recall_20q = yes
create_benefit_b_sparse_hybrid_lift_15q = no
create_benefit_c_rerank_rank_lift_15q = no
create_guardrail_d = no
create_pdf_e = no
```

下一步建议：

1. 以 A-20q 的普通 eval 和四模式 comparison 作为已完成的内容召回基线，不再重复把它当作默认切换证据。
2. 将 B/C 本轮结果记录为 observation report，不创建正式 B/C JSONL。
3. 继续保持 `default_switch_eligibility = not_eligible_for_default_switch`，不要根据 A-20q 或 B/C probe 单独推进默认切换。
4. 若要继续证明 B/C，需要先增加或重审候选语料，再重新跑 probe。

## 8. 仍然不能做的事

- 不能根据 Benefit-A 20q 切换 `rag_default_retrieval_mode`。
- 不能把 A-20q 的 20/20 结果理解成 sparse/hybrid/rerank 已证明有收益。
- 不能把 P2.4 synthetic rerank 当作真实 rank-lift 证据。
- 不能把 B/C 候选或本轮 observation report 计入正式收益。
- 不能用 1 个 PDF 的 P26-E 候选包装成多 PDF coverage。
- 不能推进 P2.2 Query Rewrite，除非扩展评测证明 query expression 是主要失败模式。

# RAG Corpus 清单6 C6-P3 Mixed 54q Retrieval Baseline

日期：2026-06-12

状态：`c6_p3_mixed_54q_retrieval_baseline_passed`

## 1. 目标

C6-P2 独立 Redis/MySQL 4q pilot 已验证新增 runbook 可被 dense-only retrieval 召回。C6-P3 在不覆盖历史 Mixed 50q 的前提下，创建派生 Mixed 54q evalset，用同一 retrieval runner 验证 30 indexed docs 阶段的新旧样本整体形状。

这一步是 retrieval-layer baseline 扩展，不是 Answer、OpenJudge/RAGAS 或 agent_behavior gate。

## 2. Evalset

新增 evalset：

```text
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl
```

来源：

- 原正式 Mixed 50q：`evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl`
- C6-P2 Redis/MySQL 4q：`evals/knowledge_base/evalsets/department_rag_c6_p2_redis_mysql_retrieval_4q.jsonl`

生成约束：

```text
sample_count = 54
unique_sample_ids = 54
first_sample = S4M-A-001
last_sample = C6P2-MYSQL-002
```

原 Mixed 50q 文件保持不变；54q 是派生 baseline，不用于覆盖历史 50q 数字。

## 3. Readiness

命令：

```text
uv run python -m evals.knowledge_base.checklist4_mixed_rag_eval_readiness_report \
  --evalset evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl \
  --output-json evals/knowledge_base/reports/checklist6_c6_p3_mixed_54q_readiness_20260612.json \
  --output-md evals/knowledge_base/reports/checklist6_c6_p3_mixed_54q_readiness_20260612.md
```

结果：

```text
status = ready_for_mixed_baseline
ready_for_mixed_baseline = true
indexed_document_count = 30
indexed_markdown_count = 18
indexed_pdf_count = 12
sample_count = 54
markdown_sample_count = 28
pdf_sample_count = 26
expression_gap_sample_count = 12
permission_scope_sample_count = 5
expected_docs_indexed = true
source_ref_resolvable = true
artifact_missing_count = 0
gaps = []
```

## 4. Baseline Result

命令：

```text
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl \
  --report evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_54q_after_c6_p2_dense_20260612.json
```

结果：

```text
total = 54
passed = 45
failed = 9
pass_rate = 83.33%
answer_wrong = 8
no_retrieval_hit = 1
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
permission_filtered_passed = 2
all_source_ref_resolvable = true
```

对比 C6-P1b Mixed 50q：

```text
existing_50q_status_changed_count = 0
c6_p2_new_samples_passed = 4/4
```

失败样本仍是原 50q 的 9 个残留失败；Redis/MySQL 新增 4 样本没有新增失败或安全边界问题。

## 5. 边界

- 不覆盖 `department_rag_mixed_markdown_pdf_50q.jsonl`。
- 不把 54q 结果写回 50q historical baseline。
- 不运行 Answer baseline。
- 不创建 Answer 50q。
- 不让 OpenJudge/RAGAS 成为主 gate。
- 不进入 agent_behavior 层。
- 不修改 `rag_default_retrieval_mode=dense_only`、`rag_query_rewrite_mode=off` 或 `rerank_enabled=false`。

## 6. 结论

C6-P3 证明：在 30 indexed docs 阶段，派生 Mixed 54q dense-only retrieval baseline 达到 45/54，新增 Redis/MySQL 样本 4/4 通过，原 Mixed 50q 样本无状态退化，source_ref/scope/citation 边界保持干净。

这满足“45/54 以上可考虑重开 Answer 层”的 retrieval 前提，但 Answer 层重启仍应作为单独阶段处理，不能由 C6-P3 自动推出 Answer 50q、prompt shadow、OpenJudge gate 或 agent_behavior acceptance。

## 7. 后续残余失败分流

Answer 30q triage-fix 和 3q sample-local `top_k=5` Answer shadow 后，Answer 层当前接受 `18/30` 作为阶段基线，不继续直接追 70%。对应的 Retrieval 残余失败分流记录在：

```text
docs/RAG_Retrieval_C6_Mixed_54q_Residual_Failure_Triage.md
```

该分流确认：

```text
mixed_54q_residual_failures = 9
all_residual_failures_from_old_50q = true
markdown_chunk_context_ranking = 3
pdf_chunk_page_table_ranking = 5
expression_or_lexical_gap = 1
rank_lift_proven_from_prior_true_rerank_probe = 0/8
sparse_or_hybrid_lift_proven = 1/9
```

因此 C6-P3 后续不应直接切换 `hybrid` / `rerank` / query rewrite 默认值。若继续 Retrieval 优化，下一步应是窄范围 `retrieval_residual_chunk_probe`：优先复核 Scoutflo PDF/table cluster 和 Markdown target-section coverage，而不是创建正式 B/C evalset 或修改默认配置。

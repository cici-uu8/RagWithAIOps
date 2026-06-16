# RAG Corpus 清单6 Observation-Only Closeout

日期：2026-06-12

状态：`c6_observation_only_28doc_baseline_stable_p1b_blocked`

## 1. 结论

C6-P1a 已把 corpus 从 18 indexed docs 扩到 28 indexed docs。由于 C6-P1b 仍等待真实 Redis/MySQL owner runbook，当前没有达到 30-50 indexed docs 的 C6 readiness 目标。

本轮只跑了 28-doc observation-only Mixed 50q baseline，用于观察 C6-P1a 导入是否给既有 50q 检索卷引入噪声。它不是 C6 readiness，也不是正式 30+ corpus baseline。

观察结果：28-doc 与 18-doc 修复后基线完全一致，未引入新的检索退化。

## 2. 输入与报告

Evalset：

- `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl`

对照报告：

- 18-doc 修复后基线：`evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_after_s4_p23_repair_20260610.json`
- 28-doc observation-only：`evals/knowledge_base/reports/department_rag_mixed_50q_on_28doc_observation_20260612.json`

运行命令：

```bash
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl \
  --report evals/knowledge_base/reports/department_rag_mixed_50q_on_28doc_observation_20260612.json
```

## 3. 结果对比

| 指标 | 18-doc 修复后基线 | 28-doc observation-only | 变化 |
|---|---:|---:|---:|
| total | 50 | 50 | 0 |
| passed | 41 | 41 | 0 |
| failed | 9 | 9 | 0 |
| answer_wrong | 8 | 8 | 0 |
| no_retrieval_hit | 1 | 1 | 0 |
| not_ready | 0 | 0 | 0 |
| asset_blocked | 0 | 0 | 0 |
| wrong_scope_count | 0 | 0 | 0 |
| citation_unresolvable_count | 0 | 0 | 0 |
| permission_filtered_passed | 2 | 2 | 0 |
| all_source_ref_resolvable | true | true | unchanged |

失败样本集合未变化：

```text
S4M-A-012
S4M-B-001
S4M-B-008
S4M-B-009
S4M-C-003
S4M-D-001
S4M-E-004
S4M-E-006
S4M-E-010
```

状态差异检查：

```text
changed_status_count = 0
changed_failure_category_count = 0
```

## 4. 判定

### 可以接受的观察结论

- C6-P1a 新增 10 个文档后，没有破坏既有 Mixed 50q 检索表现。
- 安全边界保持干净：wrong_scope、citation/source_ref、permission filtered guardrail 未退化。
- 28-doc corpus 可以作为临时观察点记录。

### 不能升级的结论

- 不能称为 C6 readiness passed，因为 indexed docs 仍是 28，小于 30-50 目标。
- 不能称为正式 30+ Mixed 50q baseline，因为 C6-P1b 真实 owner runbook 未完成。
- 不能据此创建 Answer 50q、RAGAS hard gate 或 agent_behavior acceptance。
- 不能据此修改 retrieval 默认配置、rerank、query rewrite、top_k 或 prompt。

## 5. 当前阻塞

```text
c6_p1b_status = c6_p1b_blocked_waiting_for_redis_mysql_owner_runbooks
required_sources = ["Redis high memory runbook", "MySQL slow query runbook"]
current_indexed_docs = 28
target_indexed_docs = 30-50
```

## 6. 恢复条件

拿到并 owner 批准以下真实业务 Markdown 后，恢复 C6-P1b：

- `C6-SRC-MD-001`：Redis high memory runbook
- `C6-SRC-MD-003`：MySQL slow query runbook

恢复后顺序：

1. 创建 C6-P1b 批准记录和 manifest。
2. Reviewed import & index。
3. 验证 indexed docs 达到 30+。
4. 跑 C6 readiness gate。
5. readiness 通过后，跑正式 Mixed 50q baseline。

## 7. 公开资料边界

如果长期拿不到真实 Redis/MySQL runbook，可以另开 `C6-P1c public_reference_supplement`。

P1c 必须明确：

- 公开资料是补充语料，不是内部业务 runbook。
- 公开资料不能证明业务 corpus 已成熟。
- P1c baseline 若运行，只能标注为 public-reference observation。

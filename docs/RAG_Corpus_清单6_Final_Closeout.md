# RAG Corpus 清单6 Final Closeout

日期：2026-06-12

状态：`c6_final_closeout_complete_after_mixed_54q`

## 1. 收口范围

清单6的目标是把当前 RAG corpus 从 S4/S5 使用的 18 indexed docs 扩充到至少 30 indexed docs，并验证扩充不会破坏既有 retrieval baseline。C6-P3 在不覆盖历史 Mixed 50q 的前提下，派生 Mixed 54q，把 Redis/MySQL 4q 新样本纳入新旧样本整体观察。本 closeout 只收口 corpus / retrieval 层，不收口 Answer 50q、OpenJudge gate、RAGAS 或 agent_behavior。

## 2. Corpus 结果

最终受控状态：

```text
document_records = 31
indexed_docs = 30
parsing_docs = 1
indexed_markdown_docs = 18
indexed_pdf_docs = 12
deferred_long_pdf = AWS 827-page PDF
```

阶段增量：

| 阶段 | 增量 | 结果 | 说明 |
|---|---:|---|---|
| S4/S5 baseline | - | 18 indexed docs | 12 Markdown + 6 PDF |
| C6-P1a | +10 | 28 indexed docs | 4 AIOps/DB Markdown + 6 Craft PDF |
| C6-P1b | +2 | 30 indexed docs | Redis high memory / MySQL slow query owner runbooks |
| C6-P2 | +0 | 30 indexed docs | 独立 4q pilot 验证新增 runbook retrieval |
| C6-P3 | +0 | 30 indexed docs | 派生 Mixed 54q baseline 验证新旧样本整体形状 |

注意：`data/knowledge_ingestion/current_import_state.json` 中的 `pdf_documents=13` 包含 1 个仍处于 `parsing` 的长 PDF；C6 readiness 使用的是 12 个 indexed PDF。

## 3. 验证结果

### C6-P1b readiness

报告：

```text
evals/knowledge_base/reports/checklist6_c6_p1b_mixed_50q_readiness_20260612.json
```

结果：

```text
status = ready_for_mixed_baseline
ready_for_mixed_baseline = true
indexed_document_count = 30
indexed_markdown_count = 18
indexed_pdf_count = 12
source_ref_resolvable = true
artifact_missing_count = 0
gaps = []
```

### 30-doc Mixed 50q baseline

报告：

```text
evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_after_c6_p1b_20260612.json
```

结果：

```text
total = 50
passed = 41
failed = 9
answer_wrong = 8
no_retrieval_hit = 1
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

结论：30-doc corpus 上的正式 Mixed 50q 与 S4 修复后的 18-doc baseline 同为 41/50，没有样本级退化。

### C6-P2 Redis/MySQL 4q pilot

文档：

```text
docs/RAG_Corpus_清单6_C6-P2_Redis_MySQL_retrieval_pilot.md
```

结果：

```text
total = 4
passed = 4
failed = 0
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

结论：Redis/MySQL 新增 owner runbook 能被当前 dense-only retrieval 正常召回。C6-P2 当时不合并进正式 Mixed 50q；后续 C6-P3 在单独决策下创建派生 Mixed 54q。两者都不构成 Answer 层或 agent_behavior 通过证据。

### C6-P3 derived Mixed 54q baseline

文档：

```text
docs/RAG_Corpus_清单6_C6-P3_Mixed_54q_retrieval_baseline.md
```

evalset：

```text
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl
```

结果：

```text
readiness = ready_for_mixed_baseline
total = 54
passed = 45
failed = 9
answer_wrong = 8
no_retrieval_hit = 1
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
existing_50q_status_changed_count = 0
c6_p2_new_samples_passed = 4/4
```

结论：Mixed 54q 是派生 retrieval baseline，不覆盖历史 50q。新增 Redis/MySQL 4q 全部通过；原 50q 样本状态变化为 0；失败样本仍是原 50q 的 9 个残留失败。

## 4. 边界

本阶段明确没有做以下事情：

- 不覆盖历史正式 Mixed 50q；C6-P3 的 54q 是派生 baseline。
- 不创建 Answer 50q。
- 不运行新的 Answer baseline。
- 不把 OpenJudge/RAGAS 作为主 gate。
- 不进入 agent_behavior acceptance。
- 不修改 answer prompt、top_k、hybrid/rerank/query rewrite/default retrieval mode。
- 不修改 `app/config.py` 或 `.env`。
- 不把公开 Redis/MySQL 资料当作内部 owner runbook 成熟度证据。

默认配置仍保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
```

## 5. 最终判定

C6 corpus expansion 可以阶段收口：

- corpus 从 18 indexed docs 扩到 30 indexed docs。
- C6-P1b readiness 已通过。
- 30-doc Mixed 50q baseline 稳定在 41/50。
- Redis/MySQL 新增文档 4q pilot 为 4/4。
- 派生 Mixed 54q baseline 为 45/54，原 50q 样本状态变化为 0。
- source_ref / scope / citation 边界干净。

这证明当前 corpus 扩充流程和 retrieval 层安全性是稳定的，并满足“可考虑重开 Answer 层”的 retrieval 前提；它不证明 Answer 层已经适合扩成 50q，也不证明 agent 行为层可以直接进入验收。

## 6. 下一步

默认下一步：C6 corpus/retrieval 轨道收口，不继续修改 retrieval 默认配置。若继续推进质量，应作为单独阶段重开 Answer 层验证，而不是从 C6 结果直接扩 Answer 50q 或进入 agent_behavior。

可选方向：

1. `S5 Answer revisit`：只有在明确重启 Answer 层时，才从当前 Answer/OpenJudge 记录继续；建议先做窄范围 Answer pilot，而不是直接扩 Answer 50q。
2. `C6-P4 owner-doc expansion`：补 10-15 个真实业务 runbook，再重跑 readiness + derived mixed baseline。
3. `Agent behavior design`：可先做设计，但 acceptance 不应使用 C6 retrieval 结果替代 Answer 层稳定性证据。
4. `C6-P1c public_reference_supplement`：只有长期拿不到 owner 文档时才单开，且必须标注为公开资料补充，不能作为内部业务 corpus 成熟证明。

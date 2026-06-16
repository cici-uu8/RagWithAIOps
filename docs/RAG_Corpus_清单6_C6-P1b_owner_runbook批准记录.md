# RAG Corpus 清单6 C6-P1b Owner Runbook 批准记录

日期：2026-06-12

状态：`c6_p1b_owner_runbooks_imported_30_indexed_docs`

## 1. 批次信息

- 批次名称：C6-P1b owner runbook batch
- 批准范围：2 个真实业务 Markdown runbook
- 目标：补齐 C6-P1a 后的 2+ 文档缺口，使 indexed corpus 从 28 推进到 30+
- 执行边界：只做 reviewed import / index、readiness 和 retrieval-layer baseline；不创建 Answer 50q，不运行 OpenJudge/RAGAS gate，不进入 agent_behavior 层

## 2. 批准文件

| candidate_id | source_file | kb_id | coverage | owner_approved | doc_id | indexed_chunks |
|---|---|---|---|---|---|---:|
| C6-SRC-MD-001 | `redis_high_memory_runbook.md` | process_digital_dept | Redis high memory / cache / oncall | yes | `doc_4609992d-0697-513e-945d-7a3b0dae62f4` | 9 |
| C6-SRC-MD-003 | `mysql_slow_query_runbook.md` | process_digital_dept | MySQL slow query / DBSlowQuery / oncall | yes | `doc_91ddd5b9-93bd-5c30-8a57-c7eb86a7942c` | 9 |

受控源目录：

```text
原始文件/12_清单6_corpus_expansion_round2/process_digital_dept/owner_runbooks/
```

Manifest：

- `data/knowledge_ingestion/checklist6_c6_p1b/original_files_manifest.tsv`
- `data/knowledge_ingestion/checklist6_c6_p1b/original_files_manifest_review.tsv`
- `data/knowledge_ingestion/checklist6_c6_p1b/original_files_manifest.json`

## 3. Import / Index 结果

报告：

- `evals/knowledge_base/reports/checklist6_c6_p1b_import_dry_run_20260612.json`
- `evals/knowledge_base/reports/checklist6_c6_p1b_import_apply_20260612.json`

结果：

```text
total_review_rows = 2
eligible = 2
selected = 2
imported = 2
failed = 0
```

两个 Markdown 均走现有接入链路：

```text
DocumentIngestionService.ingest_upload()
  -> DocumentIngestionService._ingest_plain_text_document
  -> VectorIndexService.index_document_record()
  -> plain_text parser
  -> MetadataStore chunks + Milvus vector index
```

## 4. Corpus 状态

C6-P1b 后的 `data/knowledge_ingestion/current_import_state.json`：

```text
total_documents = 31
indexed_documents = 30
deferred_parsing = 1  # S4 遗留 AWS IR 827-page long PDF
indexed_markdown = 18
indexed_pdf = 12
indexed_kb_count = 2
source_ref_resolvable = true
artifact_missing_count = 0
```

说明：`total_documents=31` 包含 1 个旧 long-PDF parsing 记录；当前可用于检索评测的 indexed corpus 是 30 个文档。

## 5. Readiness / Baseline

Readiness 报告：

- `evals/knowledge_base/reports/checklist6_c6_p1b_mixed_50q_readiness_20260612.json`
- `evals/knowledge_base/reports/checklist6_c6_p1b_mixed_50q_readiness_20260612.md`

Readiness 结论：

```text
status = ready_for_mixed_baseline
ready_for_mixed_baseline = true
gaps = []
```

正式 mixed 50q dense-only baseline：

- `evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_after_c6_p1b_20260612.json`

结果：

```text
total = 50
passed = 41
failed = 9
not_ready = 0
wrong_scope_count = 0
citation_unresolvable_count = 0
all_source_ref_resolvable = true
```

与 C6-P1b 前的 repaired mixed 50q baseline 对比：

```text
status_changed_count = 0
```

结论：扩充到 30 indexed docs 后，既有 mixed 50q retrieval-layer baseline 没有退化；失败形状仍是 8 个 `answer_wrong` / rank-context 覆盖问题和 1 个 `no_retrieval_hit` expression-gap seed。

## 6. 新文档召回 Sanity

额外只读 sanity 查询：

| query | expected source | result |
|---|---|---|
| Redis 内存打满 evicted keys 增长怎么办 | `redis_high_memory_runbook.md` | top-3 hit |
| MySQL 慢查询 DBSlowQuery 怎么排查 | `mysql_slow_query_runbook.md` | top-3 hit |

这只证明新文档已可被 dense-only 召回；正式 mixed 50q baseline 仍用于判断扩语料是否影响既有检索层质量。

## 7. 边界

- 不修改 `rag_default_retrieval_mode=dense_only`
- 不修改 `rag_query_rewrite_mode=off`
- 不修改 `rerank_enabled=false`
- 不创建 Answer 50q
- 不运行 Answer baseline
- 不运行 OpenJudge/RAGAS gate
- 不进入 agent_behavior 层
- 不把 C6-P1b 结果解释为 Answer 层通过

## 8. 下一步

C6-P1b 已解除 30+ indexed corpus 门槛。由于 mixed 50q retrieval baseline 没有退化，当前不需要重启 Answer 层或 agent_behavior。

更合理的下一步是二选一：

1. 继续 C6-P2，围绕 Redis/MySQL 新文档补充 retrieval-layer 样本，确认新增语料的评测覆盖。
2. 暂停 C6，保留 `41/50` retrieval baseline 和 `14/20` Answer pilot baseline，等待更多真实 owner 文档后再扩到 40-50。

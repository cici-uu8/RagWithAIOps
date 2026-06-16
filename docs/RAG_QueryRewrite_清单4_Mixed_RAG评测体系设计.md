# RAG Query Rewrite 清单 4 Mixed Markdown+PDF RAG 评测体系设计

日期：2026-06-10

状态：mixed_50q_baseline_done_s4_p22_triage_done_eval_repair_next

对应清单：`docs/RAG_QueryRewrite_语料扩充与表达缺口评测清单4.md`

50q 设计文档：`docs/RAG_QueryRewrite_清单4_Mixed_RAG_50q评测体系设计.md`

---

## 0. 结论

下一步不是直接跑 S4-P2 B/C probe，也不是马上实现 Query Rewrite。

正确顺序改为：

```text
S4-P1.5 Mixed RAG eval readiness
  -> 补齐 in-scope PDF corpus
  -> 创建 mixed Markdown+PDF evalset
  -> 跑 dense_only baseline
  -> S4-P2.1 three-layer eval system spec
  -> S4-P2.2 failure triage
  -> S4-P2.3 evalset/source_support repair
  -> 复跑 dense_only mixed baseline
  -> 再根据稳定失败决定 hybrid / rerank / Query Rewrite / PDF 工具链优先级
```

当前 readiness 结论（S4-P1.7 state repair 后）：

```text
status = ready_for_mixed_baseline
ready_for_mixed_baseline = true
indexed_document_count = 18
indexed_markdown_count = 12
indexed_pdf_count = 6
mixed_evalset_status = loaded
mixed_evalset_samples = 50
gaps = []
```

解释：

- 当前 12 个 Markdown + 6 个 PDF 已满足 mixed corpus 最低门槛。
- S4-P1.7 PDF artifact inventory 显示 6 个 indexed PDF artifact 均存在，page coverage 为 1.0，coverage gaps 为空。
- 正式 mixed 50q evalset 已创建，readiness 已通过，dense-only baseline 已执行。
- S4-P2.2 已完成 18 个失败样本分流，下一步先修 eval/source_support，再复跑 dense_only mixed baseline，不直接进入算法增强。
- AWS 827 页长 PDF 仍为 `parsing`，暂缓作为 long_pdf / stress eval 候选，不纳入首版 50q。

---

## 1. 评测体系目标

Mixed RAG eval 要回答的问题不是“某个算法看起来有没有提升”，而是：

1. 当前系统在混合文档知识库上哪里失败？
2. 失败来自哪一层：语料、检索、排序、用户表达、PDF artifact、source_ref、权限，还是最终回答？
3. 哪个增强值得做，哪个增强不能做？

因此 baseline 必须先于开发：

```text
eval readiness -> dense_only baseline -> failure triage -> targeted shadow -> active gate
```

---

## 2. Readiness Gate

新增只读 gate：

```text
evals/knowledge_base/checklist4_mixed_rag_eval_readiness_report.py
```

默认读取：

```text
data/knowledge_ingestion/current_import_state.json
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl
```

生成报告命令：

```bash
uv run python -m evals.knowledge_base.checklist4_mixed_rag_eval_readiness_report \
  --output-json evals/knowledge_base/reports/checklist4_mixed_rag_eval_readiness_20260610.json \
  --output-md evals/knowledge_base/reports/checklist4_mixed_rag_eval_readiness_20260610.md
```

进入 mixed baseline 前必须满足：

| Gate | 最低要求 | 当前 |
|---|---:|---:|
| indexed documents | >= 10 | 18 |
| indexed KB count | >= 2 | 2 |
| indexed Markdown docs | >= 5 | 12 |
| indexed PDF docs | >= 5 | 6 |
| source_ref resolvable | true | true |
| PDF artifact missing | 0 | 0 |
| mixed evalset total samples | >= 50 | 50 |
| Markdown samples | >= 20 | 24 |
| PDF samples | >= 15 | 26 |
| expression-gap samples | >= 10 | 10 |
| permission/scope samples | >= 5 | 5 |

当前阻塞项：

```text
none
```

---

## 3. Mixed Evalset 结构

目标文件：

```text
evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl
```

建议 50q 初版结构：

| 类别 | 数量 | 文档格式 | 目的 |
|---|---:|---|---|
| MD content recall | 15 | Markdown | 验证 runbook / handbook 普通内容召回 |
| PDF content recall | 10 | PDF | 验证 PDF 正文内容召回 |
| PDF page/source_ref | 5 | PDF | 验证页码、chunk、source_ref 可回查 |
| PDF table/structured evidence | 5 | PDF | 验证表格或结构化块是否可引用 |
| expression-gap | 10 | MD + PDF | 验证口语化、缩写、中英混用、症状描述不标准 |
| permission/scope/citation guardrail | 5 | MD + PDF | 验证不串 KB、不泄露、citation/source_ref 不退化 |

样本必须包含：

| 字段 | 要求 |
|---|---|
| `sample_id` | 稳定唯一 ID |
| `query` | 原始用户问法 |
| `expected_doc_ids` | 必须已 indexed |
| `expected_answer_keywords` | 必须能从 source support 找到 |
| `allowed_kb_ids` | 明确允许范围 |
| `forbidden_kb_ids` | 有 scope 风险时必须填写 |
| `failure_class` | `content_recall` / `pdf_page_source_ref` / `pdf_table` / `expression_gap` / `permission_scope` |
| `document_format` | `md` / `pdf` |
| `source_support` | 原文路径、artifact、页码或表格依据 |
| `citation_must_resolvable` | 需要 citation/source_ref gate 时为 true |
| `expected_page` | PDF page 类样本必填 |
| `expected_table_id` | PDF table 类样本必填 |

禁止：

- 不允许 source support 不存在的想象型样本进入正式 JSONL。
- 不允许把同一个 PDF 拆成大量近似题来伪造 coverage。
- 不允许把 out-of-scope 环保/合规/监测 PDF 混入当前 oncall/process_digital/craft eval。

---

## 4. Baseline 与失败分流

只有 readiness report 为 `ready_for_mixed_baseline` 后，才跑 dense-only baseline。

Baseline 命令模板：

```bash
uv run python -m evals.knowledge_base.run_department_rag_eval \
  --evalset evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_50q.jsonl \
  --report evals/knowledge_base/reports/department_rag_mixed_markdown_pdf_50q_dense_baseline_20260610.json
```

然后按 failure class 决策：

| Baseline 失败 | 优先处理 | 不能直接做什么 |
|---|---|---|
| dense no-hit，sparse/hybrid hit | S4-P2 Benefit-B probe | 不能直接切 hybrid 默认 |
| expected doc 命中但 rank 靠后 | S4-P2 Benefit-C rerank shadow | 不能直接开 rerank |
| 用户表达差导致 no-hit | S4-P3/P4 expression-gap eval，再做 Query Rewrite shadow | 不能直接 active rewrite |
| PDF page/table/source_ref 错 | PDF artifact / source_ref / page-table eval 优先 | 不要用 query rewrite 掩盖 PDF 问题 |
| wrong_scope / permission leak | 权限/scope gate 优先 | 不允许任何 retrieval active |
| citation/source_ref 不可解析 | evidence/source_ref 修复优先 | 不允许默认切换 |

当前 S4-P2.2 分流结果：

```text
eval_design_issue = 9
rank_gap = 8
confirmed_expression_gap = 1
retrieval_gap = 0
pdf_artifact_issue = 0
next_required = S4-P2.3 evalset_source_support_repair
default_switch_eligibility = not_eligible_for_default_switch
```

解释：

- 当前没有 Benefit-B 的纯 `retrieval_gap` 证据。
- 当前有 8 个 `rank_gap`，但只够作为 observation-only C-probe 候选池，不能证明 rerank 有稳定收益。
- 当前只有 1 个 `confirmed_expression_gap`，不足以创建正式 Query Rewrite evalset。
- 当前没有 PDF artifact 缺失证据，不应先修 parser / artifact。

---

## 5. 开发决策门槛

任何增强都必须由 baseline failure 触发：

| 增强 | 触发条件 | 证据 |
|---|---|---|
| hybrid | dense miss + sparse/hybrid recover >= 10q | B probe |
| rerank | true rerank rank lift >= 10q | C probe |
| Query Rewrite | confirmed expression_gap >= 10q，rewrite 无 protected-term harm | expression-gap shadow |
| PDF 工具链增强 | PDF page/table/source_ref failure 明确存在 | PDF eval + artifact inventory |
| source_ref/evidence 修复 | citation_unresolvable 或 source_ref_missing | citation/source_ref gate |

如果 mixed baseline 不满足触发条件：

```text
do_not_build_algorithmic_enhancement = true
keep_defaults = dense_only / rewrite_off / rerank_false
```

---

## 6. 当前下一步

当前正式 mixed baseline 已完成，S4-P2.2 失败分流也已完成。

下一步要做：

1. 先修 9 个 `eval_design_issue` 的 `source_support`、`expected_answer_keywords`、page/table scoring。
2. 复跑 dense-only mixed 50q baseline，确认剩余失败是否仍存在。
3. 如果复验后仍有 10+ 稳定 `rank_gap`，再设计 C-probe / rerank shadow。
4. 如果复验后出现 10+ `confirmed_expression_gap`，再设计 Query Rewrite shadow evalset。
5. 如果复验后出现 PDF artifact 问题，再优先修 PDF parser / artifact。

本轮暂缓：

- 不继续推动 AWS 827 页长 PDF 解析。
- 不做 Query Rewrite / hybrid / rerank 功能增强。
- 不直接创建 B/C 正式 JSONL。

默认配置继续保持：

```text
rag_default_retrieval_mode = dense_only
rag_query_rewrite_mode = off
rerank_enabled = false
```

---

## 7. 给小白解释

现在我们不是在问“要不要让搜索更聪明”。

我们先要把考试卷设计对。

以前考卷大部分是 Markdown，就像只考课本里的文字题。可是实际工作里还有 PDF，PDF 里有页码、表格、版式、引用位置，这些风险 Markdown 测不出来。

所以现在要先做一张混合考卷：

- 一部分题来自 Markdown。
- 一部分题来自 PDF 正文。
- 一部分题专门测 PDF 页码和表格。
- 一部分题测用户说得不标准。
- 一部分题测权限和引用。

只有这张考卷准备好，并且先用默认 dense-only 跑出失败，我们才知道下一步该修哪里。

如果失败是“关键词搜不到”，再看 hybrid。
如果失败是“排得太靠后”，再看 rerank。
如果失败是“用户说法太口语”，再看 Query Rewrite。
如果失败是“PDF 页码或表格错”，就先修 PDF。

这比直接上算法慢一点，但不会把问题修歪。

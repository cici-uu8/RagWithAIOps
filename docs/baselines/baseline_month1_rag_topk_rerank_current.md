# Baseline: Month1 RAG Top-K / Rerank Current

Baseline ID: `BASE-M1-RAG-TOPK-RERANK-CURRENT-20260618`

Date: 2026-06-18

Phase: Month1 Week3 Day0

Module: RAG retrieval / rerank shadow gate

## Scope

Record the locked Month1 Week3 Day0 baseline before any top_k or rerank candidate is considered for promotion.

This baseline is shadow-eval only. It does not change runtime defaults.

## Runtime Defaults

| Setting | Baseline Value | Evidence |
|---|---|---|
| `rag_default_retrieval_mode` | `dense_only` | `app/config.py`, `tests/test_checklist2_production_defaults.py` |
| `rag_query_rewrite_mode` | `off` | `app/config.py`, `tests/test_checklist2_production_defaults.py` |
| `rerank_enabled` | `false` | `app/config.py`, `tests/test_checklist2_production_defaults.py` |
| `rag_top_k` | `3` | `app/config.py`, `docs/baselines/baseline_month1_retrieval_defaults.md` |
| `retrieval_top_k` in this gate | `3` | `evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_20260618.json` |
| `rerank_mode` in this gate | `off` | same raw report |
| `final_context_k` in this gate | `3` | same raw report |

## Representative Eval Inputs

| Item | Value |
|---|---|
| Evalset | `evals/knowledge_base/evalsets/department_rag_mixed_markdown_pdf_54q_after_c6_p2.jsonl` |
| Sample count | 54 |
| Corpus state | 30 indexed docs = 18 Markdown + 12 PDF |
| Raw report JSON | `evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_20260618.json` |
| Raw report Markdown | `evals/knowledge_base/reports/month1_topk_rerank_shadow_matrix_54q_20260618.md` |
| Prior answer shadow reference | `evals/knowledge_base/reports/department_rag_answer_3q_top_k5_shadow_20260612.json` |

## Baseline Metrics

| Metric | Baseline Value | Meaning |
|---|---:|---|
| `passed` | 45 / 54 | Current default pass shape in this deterministic proxy gate |
| `failed` | 9 / 54 | Residual failures still exist before corpus expansion |
| `pass_rate` | 83.33% | Current shadow baseline |
| `pool_expected_doc_hit_rate` | 94.44% | First-stage retrieval baseline |
| `final_expected_doc_hit_rate` | 94.44% | No rerank loss in baseline |
| `pool_recall_at_k_avg` | 2.5741 | Candidate-pool recall baseline |
| `final_recall_at_k_avg` | 2.5741 | Final-context recall baseline |
| `answer_score_avg` | 0.8287 | Deterministic answer proxy baseline |
| `retrieval_pool_miss_count` | 3 | True recall ceiling cases before rerank discussion |
| `context_pollution_count` | 0 | Baseline has no observed context-pollution sample |
| `wrong_scope_count` | 0 | Safety gate clean |
| `source_ref_incomplete_count` | 0 | Citation/source gate clean |
| `latency_p95_ms` | 488 | Shadow engineering baseline |
| `context_tokens_p95` | 1091 | Context cost baseline |

## Gate Meaning

- Any candidate must beat this baseline without introducing `wrong_scope`, `source_ref` regression, or new answer-proxy collapse.
- If a candidate only improves candidate-pool recall but worsens final-context quality, it is not promotable.
- If first-stage retrieval misses the expected doc, that failure stays classified as retrieval ceiling, not rerank failure.

## Decision

Decision: `baseline-accepted`

Reason:

- The baseline matches the locked production posture for Month1 Week3 Day0.
- It is representative enough to judge `retrieval_top_k / rerank_top_n / final_context_k` candidates.
- It preserves the existing default while allowing shadow-only comparison.
